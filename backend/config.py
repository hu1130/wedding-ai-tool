"""配置管理"""
import os
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _strip_env_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_env_files() -> None:
    """Load local .env files without overriding real environment variables."""
    for path in (PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"):
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8-sig") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                if not key or key in os.environ:
                    continue
                os.environ[key] = _strip_env_quotes(value)


load_env_files()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass
class Settings:
    # 阿里云百炼 API Key（通义万相 + AI试衣）
    aliyun_api_key: str = os.getenv("ALIYUN_DASHSCOPE_API_KEY", "").strip()

    # 应用配置
    upload_dir: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    output_dir: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    app_code: str = field(default_factory=lambda: os.getenv("APP_CODE", "wedding_ai_tool").strip() or "wedding_ai_tool")
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development").strip().lower() or "development")
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "").strip())
    max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
    max_task_retries: int = field(default_factory=lambda: max(0, _env_int("MAX_TASK_RETRIES", 2)))
    task_retry_delay_seconds: int = field(
        default_factory=lambda: max(0, _env_int("TASK_RETRY_DELAY_SECONDS", 3))
    )
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").strip() or "INFO")
    rate_limit_enabled: bool = field(default_factory=lambda: _env_bool("RATE_LIMIT_ENABLED", False))
    max_create_tasks_per_hour: int = field(
        default_factory=lambda: max(0, _env_int("MAX_CREATE_TASKS_PER_HOUR", 60))
    )
    max_create_tasks_per_day: int = field(
        default_factory=lambda: max(0, _env_int("MAX_CREATE_TASKS_PER_DAY", 200))
    )
    max_uploads_per_hour: int = field(
        default_factory=lambda: max(0, _env_int("MAX_UPLOADS_PER_HOUR", 120))
    )

    # Object storage. Local keeps existing uploads/outputs directories.
    object_storage_mode: str = os.getenv(
        "OBJECT_STORAGE_MODE",
        os.getenv("STORAGE_BACKEND", "local"),
    ).strip().lower()
    object_storage_local_root: str = os.getenv("OBJECT_STORAGE_LOCAL_ROOT", str(PROJECT_ROOT)).strip()
    oss_endpoint: str = os.getenv("OSS_ENDPOINT", "").strip()
    oss_bucket: str = os.getenv("OSS_BUCKET", "").strip()
    oss_access_key_id: str = os.getenv("OSS_ACCESS_KEY_ID", "").strip()
    oss_access_key_secret: str = os.getenv("OSS_ACCESS_KEY_SECRET", "").strip()
    oss_public_base_url: str = os.getenv("OSS_PUBLIC_BASE_URL", "").strip()

    # Cleanup is disabled by default so local development never removes files
    # unless the operator explicitly enables it or runs a forced cleanup script.
    cleanup_enabled: bool = field(default_factory=lambda: _env_bool("CLEANUP_ENABLED", False))
    upload_retention_days: int = field(
        default_factory=lambda: _env_int("UPLOAD_RETENTION_DAYS", 30)
    )
    output_retention_days: int = field(
        default_factory=lambda: _env_int("OUTPUT_RETENTION_DAYS", 30)
    )
    deleted_record_retention_days: int = field(
        default_factory=lambda: _env_int("DELETED_RECORD_RETENTION_DAYS", 30)
    )

    # Lightweight auth for MVP deployment. Disabled by default for local dev.
    auth_mode: str = field(default_factory=lambda: os.getenv("AUTH_MODE", "local").strip().lower() or "local")
    auth_enabled: bool = field(default_factory=lambda: _env_bool("AUTH_ENABLED", False))
    admin_username: str = field(default_factory=lambda: os.getenv("ADMIN_USERNAME", "admin").strip())
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))
    app_users_json: str = field(default_factory=lambda: os.getenv("APP_USERS_JSON", "").strip())
    auth_token_secret: str = field(default_factory=lambda: os.getenv("AUTH_TOKEN_SECRET", "").strip())
    auth_token_ttl_seconds: int = field(
        default_factory=lambda: _env_int("AUTH_TOKEN_TTL_SECONDS", 12 * 60 * 60)
    )
    auth_cookie_secure: bool = field(default_factory=lambda: _env_bool("AUTH_COOKIE_SECURE", False))
    user_center_base_url: str = field(default_factory=lambda: os.getenv("USER_CENTER_BASE_URL", "").strip().rstrip("/"))
    user_center_login_url: str = field(default_factory=lambda: os.getenv("USER_CENTER_LOGIN_URL", "").strip())
    user_center_client_id: str = field(default_factory=lambda: os.getenv("USER_CENTER_CLIENT_ID", "").strip())
    user_center_client_secret: str = field(default_factory=lambda: os.getenv("USER_CENTER_CLIENT_SECRET", "").strip())
    user_center_sso_exchange_path: str = field(
        default_factory=lambda: os.getenv("USER_CENTER_SSO_EXCHANGE_PATH", "/api/v1/sso/exchange").strip() or "/api/v1/sso/exchange"
    )
    user_center_callback_success_path: str = field(
        default_factory=lambda: os.getenv("USER_CENTER_CALLBACK_SUCCESS_PATH", "/").strip() or "/"
    )

    # 场景预设
    scenes: dict = field(default_factory=lambda: {
        "教堂": "婚礼教堂，庄严神圣，彩色玻璃窗，鲜花装饰",
        "海边": "海边沙滩，日落黄昏，海浪拍岸，浪漫氛围",
        "花园": "欧洲花园，玫瑰盛开，喷泉，绿植拱门",
        "中式庭院": "中式园林，红灯笼，木质亭台，古典风格",
        "城堡": "欧式城堡，古典大厅，水晶吊灯，奢华风格",
        "森林": "森林深处，阳光透过树叶，野花遍地，自然风格",
        "影棚": "高端婚纱摄影影棚，柔和棚拍灯光，纯净浅色背景，时尚杂志质感",
        "天台夜景": "城市天台夜景，远处灯光虚化，香槟色氛围灯，现代高级感",
    })


settings = Settings()
