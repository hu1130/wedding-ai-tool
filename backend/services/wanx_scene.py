"""通义万相图生图 — 场景/姿势生成服务"""
import asyncio
import base64
import os
from typing import Optional

import httpx

from backend.config import settings


class WanxSceneService:
    """通义万相图生图服务"""

    API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation"
    MAX_POLL_ATTEMPTS = 150

    def __init__(self):
        self.api_key = settings.aliyun_api_key.strip()
        if not self.api_key:
            raise ValueError("ALIYUN_DASHSCOPE_API_KEY 未设置")

    def _encode_image(self, image_path: str) -> str:
        """将图片转为 base64"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    @staticmethod
    def _image_extension(image_bytes: bytes) -> str:
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"
        if image_bytes.startswith(b"\xff\xd8"):
            return ".jpg"
        if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return ".webp"
        return ".jpg"

    @staticmethod
    def _scene_description(scene_name: str, scene_prompt: Optional[str] = None) -> str:
        custom_prompt = (scene_prompt or "").strip()
        if custom_prompt:
            return custom_prompt
        return settings.scenes.get(scene_name, scene_name)

    async def generate_scene(
        self,
        input_image_path: str,
        prompt: str,
        output_dir: str,
        resolution: str = "1k",
        negative_prompt: str = "扭曲，变形，模糊，低质量，水印，文字",
        reference_image_paths: Optional[list[str]] = None,
    ) -> Optional[str]:
        """
        图生图：换背景+姿势变化

        参数:
            input_image_path: 输入图片路径（换装完成后的图片）
            prompt: 场景描述
            output_dir: 输出目录
            resolution: 分辨率 (1k/2k)
            negative_prompt: 负面提示词
        返回:
            输出图片路径
        """
        model = "wan2.7-image" if resolution == "1k" else "wan2.7-image-pro"
        size = "1024*1024" if resolution == "1k" else "2048*2048"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }

        content = [{"image": f"data:image/jpeg;base64,{self._encode_image(input_image_path)}"}]
        for reference_path in reference_image_paths or []:
            content.append({"image": f"data:image/jpeg;base64,{self._encode_image(reference_path)}"})
        content.append({"text": prompt})

        payload = {
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ],
            },
            "parameters": {
                "size": size,
                "n": 1,
                "negative_prompt": negative_prompt,
            },
        }

        async with httpx.AsyncClient(timeout=180) as client:
            # 提交任务
            resp = await client.post(self.API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            result = resp.json()

            # 通义万相返回 task_id，需要轮询结果
            task_id = result.get("output", {}).get("task_id")
            if not task_id:
                raise Exception(f"通义万相提交失败: {result}")

            # 轮询任务状态
            status_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
            for _ in range(self.MAX_POLL_ATTEMPTS):
                status_resp = await client.get(status_url, headers=headers)
                status_resp.raise_for_status()
                status_result = status_resp.json()
                status = status_result.get("output", {}).get("task_status")

                if status == "SUCCEEDED":
                    choices = status_result.get("output", {}).get("choices", [])
                    content = []
                    if choices:
                        content = choices[0].get("message", {}).get("content", [])
                    img_url = next(
                        (item.get("image") for item in content if isinstance(item, dict) and item.get("image")),
                        None,
                    )
                    if img_url:
                        img_resp = await client.get(img_url)
                        img_resp.raise_for_status()

                        extension = self._image_extension(img_resp.content)
                        output_path = os.path.join(output_dir, f"scene_{resolution}{extension}")
                        with open(output_path, "wb") as f:
                            f.write(img_resp.content)
                        return output_path
                    raise Exception(f"通义万相成功但未返回图片地址: {status_result}")
                elif status == "FAILED":
                    output = status_result.get("output", {})
                    err = output.get("message", "未知错误")
                    code = output.get("code", "FAILED")
                    raise Exception(f"通义万相生成失败[{code}]: {err}; DashScope task_id={task_id}")

                await asyncio.sleep(2)

            raise TimeoutError(f"通义万相任务轮询超时; DashScope task_id={task_id}")

        return None

    async def generate_background(
        self,
        scene_name: str,
        output_dir: str,
        resolution: str = "1k",
        scene_prompt: Optional[str] = None,
    ) -> Optional[str]:
        """Generate an empty wedding background for stable compositing."""
        model = "wan2.7-image" if resolution == "1k" else "wan2.7-image-pro"
        size = "1024*1024" if resolution == "1k" else "2048*2048"
        scene_desc = self._scene_description(scene_name, scene_prompt)
        prompt = (
            "Empty luxury wedding photography background, "
            f"{scene_desc}, "
            "full body portrait composition, realistic depth of field, elegant lighting, "
            "no people, no person, no bride, no groom, no model, no mannequin, "
            "no dress, no face, no body, no text, no logo, no watermark."
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        payload = {
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt}],
                    }
                ],
            },
            "parameters": {
                "size": size,
                "n": 1,
                "negative_prompt": (
                    "people, person, bride, groom, model, mannequin, human, face, body, "
                    "dress, text, logo, watermark, low quality, distorted"
                ),
            },
        }

        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(self.API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            result = resp.json()

            task_id = result.get("output", {}).get("task_id")
            if not task_id:
                raise Exception(f"背景生成提交失败: {result}")

            status_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
            for _ in range(self.MAX_POLL_ATTEMPTS):
                status_resp = await client.get(status_url, headers=headers)
                status_resp.raise_for_status()
                status_result = status_resp.json()
                status = status_result.get("output", {}).get("task_status")

                if status == "SUCCEEDED":
                    choices = status_result.get("output", {}).get("choices", [])
                    content = []
                    if choices:
                        content = choices[0].get("message", {}).get("content", [])
                    img_url = next(
                        (item.get("image") for item in content if isinstance(item, dict) and item.get("image")),
                        None,
                    )
                    if img_url:
                        img_resp = await client.get(img_url)
                        img_resp.raise_for_status()
                        extension = self._image_extension(img_resp.content)
                        output_path = os.path.join(output_dir, f"background_{resolution}{extension}")
                        with open(output_path, "wb") as f:
                            f.write(img_resp.content)
                        return output_path
                    raise Exception(f"背景生成成功但未返回图片地址: {status_result}")
                elif status == "FAILED":
                    output = status_result.get("output", {})
                    err = output.get("message", "未知错误")
                    code = output.get("code", "FAILED")
                    raise Exception(f"背景生成失败[{code}]: {err}; DashScope task_id={task_id}")

                await asyncio.sleep(2)

            raise TimeoutError(f"背景生成任务轮询超时; DashScope task_id={task_id}")

        return None

    @staticmethod
    def _face_blend_prompt() -> str:
        return (
            "保留人物身份相似度，但必须把脸、脖子、头发边缘重新融入最终场景的光线和阴影；"
            "面部肤色、亮度、清晰度、颗粒感和背景光源一致，头部与脖子肩膀自然连接，"
            "发丝边缘柔和真实，不能像抠图头像或贴纸。"
        )

    def build_scene_prompt(
        self,
        scene_name: str,
        gender: str = "女性",
        pose: str = "保持原姿势",
        preserve_face: bool = True,
        force_floor_length: bool = False,
        scene_prompt: Optional[str] = None,
    ) -> str:
        """根据场景名构建提示词"""
        scene_desc = self._scene_description(scene_name, scene_prompt)
        face_prompt = (
            "严格保留输入图片中人物的五官、脸型、发型、表情和身份特征，不要换脸，不要改变面部相似度，"
            if preserve_face
            else ""
        )
        face_blend_prompt = self._face_blend_prompt() if preserve_face else ""
        floor_length_prompt = (
            "必须呈现长款拖地婚纱，裙摆从腰部自然展开并覆盖双腿直到地面，"
            "保留大裙摆、拖尾和落地长度；如果当前图片里裙子是及膝裙或露腿，"
            "必须修正为完整拖地婚纱，不允许短裙、不允许迷你裙、不允许普通连衣裙，"
            if force_floor_length
            else ""
        )
        return (
            f"婚纱照，{scene_desc}，一位{gender}穿着当前图片中的白色婚纱，"
            f"{face_prompt}"
            f"{face_blend_prompt}"
            f"严格保留原有婚纱的款式、领口、腰线、裙长、裙摆轮廓和蕾丝纹理，"
            f"不要把长款婚纱改成短裙，不要改变服装结构，"
            f"{floor_length_prompt}"
            f"姿势要求：{pose}，动作自然，身体比例真实，"
            f"面带自然微笑，高清细节，柔光，电影质感"
        )

    def build_reference_gown_prompt(
        self,
        scene_name: str,
        gender: str = "女性",
        pose: str = "保持原姿势",
        preserve_face: bool = True,
        pose_mode: str = "stable",
        force_floor_length: bool = False,
        scene_prompt: Optional[str] = None,
        has_pose_reference: bool = False,
    ) -> str:
        """Build prompt for model + product-gown multi-reference generation."""
        scene_desc = self._scene_description(scene_name, scene_prompt)
        face_prompt = (
            "严格保留第一张图中模特的五官、脸型、发型、表情和身份特征，不要换脸，"
            if preserve_face
            else ""
        )
        face_blend_prompt = self._face_blend_prompt() if preserve_face else ""
        pose_mode_prompt = {
            "stable": "动作优先保持第一张图的自然站姿，不做夸张姿势变化；",
            "light": "只允许轻微动作变化，手臂和身体可以自然调整，但不要大幅转身、坐下或改变人物身份；",
            "experimental": "按照姿势要求生成更明显的动作，但必须优先保证人脸相似度、身体比例和婚纱完整性；",
        }.get(pose_mode, "动作自然，人物身份和婚纱完整性优先；")
        length_prompt = (
            "必须保持长款拖地婚纱，裙摆从腰部自然展开并覆盖双腿直到地面，保留拖尾和落地长度，"
            "不允许变成及膝裙、短裙或普通连衣裙。"
            if force_floor_length
            else "保留第二张图原本的裙长、裙摆体量和服装结构。"
        )
        pose_reference_prompt = (
            "第三张图是动作参考，只参考身体朝向、手臂位置、手与裙摆关系和整体姿态；"
            "不要复制第三张图的人脸、发型、服装、背景、颜色或人物身份。"
            if has_pose_reference
            else ""
        )
        return (
            f"根据{'三' if has_pose_reference else '两'}张参考图生成一张真实婚纱照。"
            f"第一张图是模特参考，{face_prompt}{face_blend_prompt}保留自然站姿和身体比例；"
            "第二张图是唯一的婚纱款式参考，必须让模特穿第二张图里的同一件婚纱，"
            "保留原始领口、腰线、裙摆轮廓、面料质感、蕾丝或纱面纹理。"
            f"{pose_reference_prompt}"
            f"{length_prompt}"
            "必须完全替换第一张图里的原服装，不要保留原短裙，不要在短裙外面再加一层长裙，"
            "画面中只能有一条连续完整的婚纱，从胸口到裙摆自然连接。"
            f"动作控制：{pose_mode_prompt}姿势要求：{pose}。"
            f"拍摄场景：{scene_desc}。"
            f"一位{gender}，全身人像构图，脚和裙摆都在画面内，高清细节，柔光，电影质感。"
        )
