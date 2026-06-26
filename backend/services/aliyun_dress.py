"""阿里云百炼 AI试衣 aitryon-plus 服务"""
import asyncio
import base64
import os
from typing import Optional

import httpx

from backend.config import settings


class AliyunTryOnService:
    """阿里云 AI试衣（aitryon-plus）服务"""

    API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/image2image/image-synthesis"
    MAX_POLL_ATTEMPTS = 150

    def __init__(self):
        self.api_key = settings.aliyun_api_key.strip()
        if not self.api_key:
            raise ValueError("ALIYUN_DASHSCOPE_API_KEY 未设置")

    async def try_on(
        self,
        model_image_path: str,
        garment_image_path: str,
        output_dir: str,
        restore_face: bool = True,
    ) -> Optional[str]:
        """
        AI试衣：将衣服穿到模特身上

        参数:
            model_image_path: 模特图片路径
            garment_image_path: 服装图片路径
            output_dir: 输出目录
            restore_face: 是否保留模特人脸
        返回:
            输出图片路径
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }

        with open(model_image_path, "rb") as f:
            model_b64 = base64.b64encode(f.read()).decode("utf-8")
        with open(garment_image_path, "rb") as f:
            garment_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "model": "aitryon-plus",
            "input": {
                "person_image_url": f"data:image/jpeg;base64,{model_b64}",
                "top_garment_url": f"data:image/jpeg;base64,{garment_b64}",
                # 婚纱是连衣裙/整裙。只传 top 会让模型把裙摆重绘成短裙；
                # 同图同时传 top/bottom 能更稳定保留全身裙廓形。
                "bottom_garment_url": f"data:image/jpeg;base64,{garment_b64}",
            },
            "parameters": {
                "restore_face": restore_face,
            },
        }

        async with httpx.AsyncClient(timeout=180) as client:
            # 提交异步任务
            resp = await client.post(self.API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            result = resp.json()

            task_id = result.get("output", {}).get("task_id")
            if not task_id:
                raise Exception(f"AI试衣提交失败: {result.get('message', str(result))}")

            # 轮询结果
            status_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
            for _ in range(self.MAX_POLL_ATTEMPTS):
                status_resp = await client.get(status_url, headers={
                    "Authorization": f"Bearer {self.api_key}",
                })
                status_resp.raise_for_status()
                status_result = status_resp.json()
                status = status_result.get("output", {}).get("task_status")

                if status == "SUCCEEDED":
                    img_url = status_result.get("output", {}).get("image_url")
                    if img_url:
                        img_resp = await client.get(img_url)
                        img_resp.raise_for_status()
                        output_path = os.path.join(output_dir, "tryon_result.jpg")
                        with open(output_path, "wb") as f:
                            f.write(img_resp.content)
                        return output_path
                    raise Exception(f"AI试衣成功但未返回图片地址: {status_result}")
                    break
                elif status == "FAILED":
                    output = status_result.get("output", {})
                    err = output.get("message", "未知错误")
                    code = output.get("code", "FAILED")
                    raise Exception(f"AI试衣失败[{code}]: {err}; DashScope task_id={task_id}")

                await asyncio.sleep(2)

            raise TimeoutError(f"AI试衣任务轮询超时; DashScope task_id={task_id}")

        return None
