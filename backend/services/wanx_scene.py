"""通义万相图生图 — 场景/姿势生成服务"""
import asyncio
import base64
import os
from typing import Optional

import httpx

from backend.config import settings
from backend.models.clothing import WEDDING_GOWN, get_clothing_type_config, is_wedding_clothing


FACE_ARTIFACT_NEGATIVE_PROMPT = (
    "贴脸，抠图头像，头像像贴纸，脸部硬边，头发边缘硬边，脸部边缘光晕，"
    "脸和脖子断裂，头身不连接，头部比例过大，脸部光线不一致，肤色不一致，"
    "五官漂移，身份变化，过度美颜，pasted face, cutout head, sticker face, hard face edge, "
    "halo around head, disconnected neck, floating head, mismatched face lighting, mismatched skin tone"
)

WEDDING_GOWN_STYLE_PROMPT = (
    "婚纱必须是同一件完整婚纱，严格保留原始领口、肩袖、腰线、裙摆轮廓、"
    "裙长、拖尾、面料质感、蕾丝或纱面纹理和装饰细节；"
    "不要简化成普通白裙、晚礼服或通勤连衣裙，不要改变婚纱款式比例。"
)

WEDDING_GOWN_FLOOR_LENGTH_PROMPT = (
    "必须保持长款拖地婚纱，裙摆从腰部自然连续展开并覆盖双腿直到地面，"
    "拖尾和落地长度清晰可见；全身构图里脚和完整裙摆都在画面内，"
    "不裁切裙摆，不露出小腿。"
)

BASE_WEDDING_GOWN_NEGATIVE_PROMPT = (
    "短裙，及膝裙，迷你裙，茶歇裙，普通连衣裙，普通白裙，晚礼服，短款礼服，通勤裙，"
    "露出膝盖，露出小腿，裙摆被截断，裙摆断开，裙摆被裁切，拖尾消失，裙摆变窄，"
    "改变婚纱廓形，改变婚纱款式，简化蕾丝，错误领口，错误腰线，错误裙摆，"
    "换脸，脸部变形，身体比例失真，手部畸形，多余手指，扭曲，变形，模糊，"
    "低质量，水印，文字，logo"
)

REFERENCE_GOWN_NEGATIVE_PROMPT = (
    "两条裙子，双层裙，短裙外面套长裙，上下两件裙子，保留原短裙，"
    "没有完全替换原服装，胸口和裙摆不连接，腰部断层"
)


def build_wedding_gown_negative_prompt(reference_mode: bool = False) -> str:
    """Return the wedding-specific negative prompt shared by generation paths."""
    parts = [BASE_WEDDING_GOWN_NEGATIVE_PROMPT]
    if reference_mode:
        parts.insert(0, REFERENCE_GOWN_NEGATIVE_PROMPT)
    parts.append(FACE_ARTIFACT_NEGATIVE_PROMPT)
    return "，".join(part.strip("，") for part in parts if part)


GENERIC_CLOTHING_NEGATIVE_PROMPT = (
    "wrong clothing category, changed garment design, changed garment color, changed fabric, "
    "missing sleeves, missing trouser legs, incomplete replacement, original clothing still visible, "
    "distorted buttons, distorted pattern, malformed hands, distorted body, low quality, text, logo, watermark"
)

REFERENCE_CLOTHING_NEGATIVE_PROMPT = (
    "duplicated outfit, two different outfits, layered wrong garment, incomplete outfit transfer, "
    "garment floating away from body, copied product photo background"
)


def build_clothing_negative_prompt(clothing_type: str | None, reference_mode: bool = False) -> str:
    """Return a negative prompt for the requested clothing type."""
    if is_wedding_clothing(clothing_type):
        return build_wedding_gown_negative_prompt(reference_mode=reference_mode)

    config = get_clothing_type_config(clothing_type)
    parts = [config.negative_prompt, GENERIC_CLOTHING_NEGATIVE_PROMPT]
    if reference_mode:
        parts.insert(0, REFERENCE_CLOTHING_NEGATIVE_PROMPT)
    parts.append(FACE_ARTIFACT_NEGATIVE_PROMPT)
    return ", ".join(part.strip(" ,，;；") for part in parts if part)


def _face_identity_prompt(subject: str) -> str:
    return (
        f"严格保留{subject}的五官、脸型、发型、发际线、表情、年龄感和身份特征，"
        "不要换脸，不要改变面部相似度，不要过度美颜；"
    )


def _floor_length_prompt(force_floor_length: bool) -> str:
    if force_floor_length:
        return (
            f"{WEDDING_GOWN_FLOOR_LENGTH_PROMPT}"
            "如果当前图片或参考图里出现及膝裙、露腿或裙摆缺失，必须修正为完整拖地婚纱。"
        )
    return (
        "保留参考婚纱原本的裙长、拖尾、裙摆体量和服装结构；"
        "如果参考婚纱是长款或带拖尾，不得缩短成及膝裙、短裙或普通连衣裙。"
    )


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
        clothing_type: str = WEDDING_GOWN,
    ) -> Optional[str]:
        """Generate an empty background for stable compositing."""
        model = "wan2.7-image" if resolution == "1k" else "wan2.7-image-pro"
        size = "1024*1024" if resolution == "1k" else "2048*2048"
        scene_desc = self._scene_description(scene_name, scene_prompt)
        config = get_clothing_type_config(clothing_type)
        background_category = (
            "wedding photography" if is_wedding_clothing(clothing_type) else "fashion photography"
        )
        prompt = (
            f"Empty luxury {background_category} background, "
            f"{scene_desc}, "
            "full body portrait composition, realistic depth of field, elegant lighting, "
            f"no people, no person, no model, no mannequin, no {config.garment_name}, "
            "no clothing, no garment, no outfit, no face, no body, no text, no logo, no watermark."
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
                    "dress, gown, suit, garment, outfit, text, logo, watermark, low quality, distorted"
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
        face_prompt = _face_identity_prompt("输入图片中人物") if preserve_face else ""
        face_blend_prompt = self._face_blend_prompt() if preserve_face else ""
        floor_length_prompt = _floor_length_prompt(force_floor_length)
        return (
            f"婚纱照，{scene_desc}，一位{gender}穿着当前图片中的白色婚纱，"
            f"{face_prompt}"
            f"{face_blend_prompt}"
            f"{WEDDING_GOWN_STYLE_PROMPT}"
            "以当前图片中的婚纱为唯一服装参考，不要重新设计成其他裙子；"
            f"{floor_length_prompt}"
            f"姿势要求：{pose}，动作自然，身体比例真实，全身人像构图，头发、脸、手、脚和完整裙摆都清晰，"
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
        face_prompt = _face_identity_prompt("第一张图中模特") if preserve_face else ""
        face_blend_prompt = self._face_blend_prompt() if preserve_face else ""
        pose_mode_prompt = {
            "stable": "动作优先保持第一张图的自然站姿，不做夸张姿势变化，不缩短婚纱；",
            "light": "只允许轻微动作变化，手臂和身体可以自然调整，但不要大幅转身、坐下、改变人物身份或缩短婚纱；",
            "experimental": "按照姿势要求生成更明显的动作，但必须优先保证人脸相似度、身体比例、婚纱完整性和拖地长度；",
        }.get(pose_mode, "动作自然，人物身份、婚纱完整性和拖地长度优先；")
        length_prompt = _floor_length_prompt(force_floor_length)
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
            f"{WEDDING_GOWN_STYLE_PROMPT}"
            f"{pose_reference_prompt}"
            f"{length_prompt}"
            "必须完全替换第一张图里的原服装，不要保留原短裙，不要在短裙外面再加一层长裙，"
            "画面中只能有一条连续完整的婚纱，从胸口到裙摆自然连接。"
            f"动作控制：{pose_mode_prompt}姿势要求：{pose}。"
            f"拍摄场景：{scene_desc}。"
            f"一位{gender}，全身人像构图，脚和裙摆都在画面内，高清细节，柔光，电影质感。"
        )

    def build_clothing_scene_prompt(
        self,
        scene_name: str,
        clothing_type: str = WEDDING_GOWN,
        gender: str = "女性",
        pose: str = "保持原姿势",
        preserve_face: bool = True,
        force_floor_length: bool = False,
        scene_prompt: Optional[str] = None,
    ) -> str:
        """Build a scene prompt while keeping wedding as the primary path."""
        if is_wedding_clothing(clothing_type):
            return self.build_scene_prompt(
                scene_name=scene_name,
                gender=gender,
                pose=pose,
                preserve_face=preserve_face,
                force_floor_length=force_floor_length,
                scene_prompt=scene_prompt,
            )

        config = get_clothing_type_config(clothing_type)
        scene_desc = self._scene_description(scene_name, scene_prompt)
        face_prompt = (
            "Keep the exact face identity, facial features, hairstyle, hairline, expression and age cues "
            "from the input image. Do not swap the face or over-beautify it. "
            if preserve_face
            else ""
        )
        return (
            f"Realistic fashion try-on photo, {scene_desc}. "
            f"The person in the input image is wearing the same {config.garment_name} from the current image. "
            f"{face_prompt}"
            f"{config.style_prompt}. "
            "Use the current image as the only clothing reference, keep the garment category, color, material, "
            "proportions, sleeves, hem, closures and visible details. "
            "Fully replace the original clothing, do not redesign the outfit into another category. "
            f"Pose requirement: {pose}. Natural body proportions, full-body portrait composition, "
            "clear face, hair, hands, feet and complete outfit, realistic lighting, high detail."
        )

    def build_reference_clothing_prompt(
        self,
        scene_name: str,
        clothing_type: str = WEDDING_GOWN,
        gender: str = "女性",
        pose: str = "保持原姿势",
        preserve_face: bool = True,
        pose_mode: str = "stable",
        force_floor_length: bool = False,
        scene_prompt: Optional[str] = None,
        has_pose_reference: bool = False,
    ) -> str:
        """Build a prompt for model + product-clothing multi-reference generation."""
        if is_wedding_clothing(clothing_type):
            return self.build_reference_gown_prompt(
                scene_name=scene_name,
                gender=gender,
                pose=pose,
                preserve_face=preserve_face,
                pose_mode=pose_mode,
                force_floor_length=force_floor_length,
                scene_prompt=scene_prompt,
                has_pose_reference=has_pose_reference,
            )

        config = get_clothing_type_config(clothing_type)
        scene_desc = self._scene_description(scene_name, scene_prompt)
        face_prompt = (
            "Keep the exact face identity, facial features, hairstyle, hairline, expression and age cues "
            "from the first reference image. Do not copy identity from other references. "
            if preserve_face
            else ""
        )
        pose_mode_prompt = {
            "stable": "Keep the first reference image's natural standing posture with only minimal changes.",
            "light": "Allow a small natural pose change while preserving identity, body proportion and outfit structure.",
            "experimental": "Follow the requested pose more clearly, but prioritize face identity and realistic outfit fit.",
        }.get(pose_mode, "Use a natural pose while preserving identity and outfit structure.")
        pose_reference_prompt = (
            "The third reference image is only for body direction, arm position and overall pose. "
            "Do not copy its face, hairstyle, clothing, background, color palette or identity. "
            if has_pose_reference
            else ""
        )
        return (
            f"Generate one realistic fashion try-on image from {'three' if has_pose_reference else 'two'} references. "
            f"The first reference is the model: {face_prompt}keep natural body proportions. "
            f"The second reference is the only {config.garment_name} style reference; make the model wear that same outfit. "
            f"{config.style_prompt}. "
            f"{pose_reference_prompt}"
            "Completely replace the original clothing from the first image, keep one coherent outfit attached naturally "
            "to the body, and preserve the garment color, fabric, category, sleeves, hem, closures and details. "
            f"Pose control: {pose_mode_prompt} Pose requirement: {pose}. "
            f"Scene: {scene_desc}. "
            "Full-body portrait composition, feet and complete outfit visible, realistic lighting, high detail."
        )
