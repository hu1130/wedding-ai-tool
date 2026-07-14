"""图片处理工具"""
import io
import os
import uuid

from PIL import Image

from backend.config import settings
from backend.storage.object_storage import get_object_storage
from backend.utils.media import image_media_type_from_path

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


async def save_upload(
    file_bytes: bytes,
    filename: str,
    subdir: str = "",
    content_type: str = "application/octet-stream",
) -> str:
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

    storage_key = f"uploads/{subdir}/{save_name}" if subdir else save_name
    get_object_storage().save_bytes(storage_key, file_bytes, content_type)

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
    if os.path.exists(resolved):
        return resolved

    storage = get_object_storage()
    if storage.exists(filename):
        os.makedirs(upload_root, exist_ok=True)
        with open(resolved, "wb") as f:
            f.write(storage.get_bytes(filename))
        return resolved

    raise FileNotFoundError("文件不存在")


def persist_output_file(file_path: str) -> str:
    """Persist a generated output file to object storage and return its storage key."""
    if not file_path or not os.path.isfile(file_path):
        raise FileNotFoundError("输出文件不存在")
    storage_key = os.path.relpath(file_path, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    storage_key = storage_key.replace(os.sep, "/")
    with open(file_path, "rb") as f:
        get_object_storage().save_bytes(
            storage_key,
            f.read(),
            image_media_type_from_path(file_path),
        )
    return storage_key


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
