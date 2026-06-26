"""图片处理工具"""
import io
import os
import uuid

from PIL import Image

from backend.config import settings

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


async def save_upload(file_bytes: bytes, filename: str, subdir: str = "") -> str:
    """保存上传文件到 uploads 目录，返回服务端生成的文件 ID。"""
    ext = os.path.splitext(filename or "")[1].lower() or ".jpg"
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("不支持的图片格式")

    save_name = f"{uuid.uuid4().hex}{ext}"

    save_dir = settings.upload_dir
    if subdir:
        save_dir = os.path.join(save_dir, subdir)
    os.makedirs(save_dir, exist_ok=True)

    save_path = os.path.join(save_dir, save_name)
    with open(save_path, "wb") as f:
        f.write(file_bytes)

    return save_name


def resolve_upload_path(file_id: str) -> str:
    """把上传文件 ID 解析到 uploads 内的绝对路径。"""
    if not file_id:
        raise ValueError("文件 ID 不能为空")

    filename = os.path.basename(file_id)
    if filename != file_id:
        raise ValueError("非法文件 ID")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("不支持的图片格式")

    upload_root = os.path.abspath(settings.upload_dir)
    resolved = os.path.abspath(os.path.join(upload_root, filename))
    if os.path.commonpath([upload_root, resolved]) != upload_root:
        raise ValueError("非法文件路径")
    if not os.path.exists(resolved):
        raise FileNotFoundError("文件不存在")

    return resolved


def validate_image(file_bytes: bytes) -> bool:
    """验证图片是否有效"""
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.verify()
        return True
    except Exception:
        return False


def get_image_size(file_path: str) -> tuple[int, int]:
    """获取图片尺寸"""
    with Image.open(file_path) as img:
        return img.size
