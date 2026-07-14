"""SQLAlchemy persistence helpers for MySQL production and local tests.

The production path is MySQL via ``DATABASE_URL``. SQLite is kept only as a
local/test fallback so unit tests and developer machines do not need RDS.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator, Optional
from urllib.parse import quote_plus, unquote, urlparse

from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    Index,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    inspect,
    or_,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool


_DB_LOCK = threading.RLock()
_ENGINE_CACHE: dict[str, Engine] = {}
_SCHEMA_READY: set[str] = set()

DEFAULT_TENANT_ID = "dev"
DEFAULT_PLATFORM_USER_ID = "dev"
DEFAULT_LOCAL_USER_ID = "dev"
DEFAULT_APP_CODE = "wedding_ai_tool"
SHARED_ASSET_VISIBILITIES = ("shared", "public", "tenant")

metadata = MetaData()

storage_meta = Table(
    "storage_meta",
    metadata,
    Column("key", String(191), primary_key=True),
    Column("value", Text, nullable=False),
)

terminal_user_binding = Table(
    "terminal_user_binding",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant_id", String(64), nullable=False),
    Column("platform_user_id", String(64), nullable=False),
    Column("local_user_id", String(64), nullable=False),
    Column("app_code", String(64), nullable=False, default=DEFAULT_APP_CODE),
    Column("roles_json", Text, nullable=False, default="[]"),
    Column("status", String(16), nullable=False, default="active"),
    Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
    UniqueConstraint("tenant_id", "platform_user_id", name="uk_tenant_platform_user"),
    Index("idx_terminal_user_binding_local", "local_user_id"),
    Index("idx_terminal_user_binding_tenant_status", "tenant_id", "status"),
)

tool_sessions = Table(
    "tool_sessions",
    metadata,
    Column("session_id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("platform_user_id", String(64), nullable=False),
    Column("local_user_id", String(64), nullable=False),
    Column("username", String(128), nullable=False, default=""),
    Column("app_code", String(64), nullable=False, default=DEFAULT_APP_CODE),
    Column("roles_json", Text, nullable=False, default="[]"),
    Column("expires_at", BigInteger, nullable=False),
    Column("revoked_at", String(32), nullable=False, default=""),
    Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
    Index("idx_tool_sessions_identity", "tenant_id", "platform_user_id"),
    Index("idx_tool_sessions_expires", "expires_at"),
)

tasks = Table(
    "tasks",
    metadata,
    Column("task_id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False, default=DEFAULT_TENANT_ID),
    Column("platform_user_id", String(64), nullable=False, default=DEFAULT_PLATFORM_USER_ID),
    Column("local_user_id", String(64), nullable=False, default=DEFAULT_LOCAL_USER_ID),
    Column("app_code", String(64), nullable=False, default=DEFAULT_APP_CODE),
    Column("status", String(32), nullable=False, default="pending"),
    Column("record_json", Text, nullable=False),
    Column("created_at", String(32), nullable=False, default=""),
    Column("updated_at", String(32), nullable=False),
    Index("idx_tasks_tenant_created", "tenant_id", "created_at"),
    Index("idx_tasks_user_created", "tenant_id", "platform_user_id", "created_at"),
    Index("idx_tasks_status_created", "tenant_id", "status", "created_at"),
)

assets = Table(
    "assets",
    metadata,
    Column("asset_id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False, default=DEFAULT_TENANT_ID),
    Column("platform_user_id", String(64), nullable=False, default=DEFAULT_PLATFORM_USER_ID),
    Column("local_user_id", String(64), nullable=False, default=DEFAULT_LOCAL_USER_ID),
    Column("category", String(32), nullable=False, default="uncategorized"),
    Column("file_id", String(255), nullable=False, default=""),
    Column("filename", String(255), nullable=False, default=""),
    Column("visibility", String(16), nullable=False, default="personal"),
    Column("deleted_at", String(32), nullable=False, default=""),
    Column("record_json", Text, nullable=False),
    Column("created_at", String(32), nullable=False, default=""),
    Column("updated_at", String(32), nullable=False),
    Index("idx_assets_tenant_category", "tenant_id", "category", "created_at"),
    Index("idx_assets_tenant_user", "tenant_id", "platform_user_id", "created_at"),
    Index("idx_assets_file_category", "tenant_id", "file_id", "category"),
)

quality_reviews = Table(
    "quality_reviews",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant_id", String(64), nullable=False, default=DEFAULT_TENANT_ID),
    Column("platform_user_id", String(64), nullable=False, default=DEFAULT_PLATFORM_USER_ID),
    Column("local_user_id", String(64), nullable=False, default=DEFAULT_LOCAL_USER_ID),
    Column("task_id", String(64), nullable=False),
    Column("record_json", Text, nullable=False),
    Column("created_at", String(32), nullable=False, default=""),
    Column("updated_at", String(32), nullable=False),
    UniqueConstraint("tenant_id", "task_id", name="uk_quality_review_tenant_task"),
    Index("idx_quality_reviews_tenant_updated", "tenant_id", "updated_at"),
)

business_logs = Table(
    "business_logs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant_id", String(64), nullable=False, default=DEFAULT_TENANT_ID),
    Column("platform_user_id", String(64), nullable=False, default=DEFAULT_PLATFORM_USER_ID),
    Column("local_user_id", String(64), nullable=False, default=DEFAULT_LOCAL_USER_ID),
    Column("trace_id", String(64), nullable=False, default=""),
    Column("action", String(64), nullable=False),
    Column("resource_type", String(64), nullable=False, default=""),
    Column("resource_id", String(128), nullable=False, default=""),
    Column("record_json", Text, nullable=False, default="{}"),
    Column("created_at", String(32), nullable=False),
    Index("idx_business_logs_tenant_created", "tenant_id", "created_at"),
    Index("idx_business_logs_trace", "trace_id"),
)


EXPECTED_TABLE_NAMES = tuple(table.name for table in metadata.sorted_tables)


def now_iso() -> str:
    return datetime.now().isoformat()


def backend_root() -> str:
    return os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def default_database_path() -> str:
    return os.path.join(backend_root(), "data", "app.db")


def default_sqlite_url(path: Optional[str] = None) -> str:
    resolved = os.path.abspath(path or default_database_path())
    return "sqlite:///" + resolved.replace("\\", "/")


def has_configured_database() -> bool:
    return bool(os.environ.get("DATABASE_URL") or os.environ.get("SQLITE_DB_PATH"))


def resolve_database_path(db_path: Optional[str] = None) -> str:
    url = resolve_database_url(db_path)
    parsed = urlparse(url)
    if parsed.scheme.startswith("sqlite"):
        path = unquote(parsed.path or "")
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path
    return url


def resolve_database_url(db_path: Optional[str] = None) -> str:
    if db_path:
        if "://" in db_path:
            return db_path
        return default_sqlite_url(db_path)

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        return database_url

    sqlite_path = os.environ.get("SQLITE_DB_PATH", "").strip()
    if sqlite_path:
        return default_sqlite_url(sqlite_path)

    return default_sqlite_url()


def is_mysql_url(url: Optional[str] = None) -> bool:
    return (url or resolve_database_url()).split(":", 1)[0].startswith("mysql")


def build_mysql_url(
    *,
    user: str,
    password: str,
    host: str,
    database: str,
    port: int = 3306,
    charset: str = "utf8mb4",
) -> str:
    return (
        f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{database}?charset={charset}"
    )


def _engine_for(db_path: Optional[str] = None) -> Engine:
    url = resolve_database_url(db_path)
    with _DB_LOCK:
        engine = _ENGINE_CACHE.get(url)
        if engine is not None:
            return engine

        is_sqlite = url.startswith("sqlite")
        connect_args = {"check_same_thread": False} if is_sqlite else {}
        engine_kwargs: dict[str, Any] = {
            "future": True,
            "pool_pre_ping": True,
            "connect_args": connect_args,
        }
        if is_sqlite:
            engine_kwargs["poolclass"] = NullPool
        engine = create_engine(url, **engine_kwargs)
        _ENGINE_CACHE[url] = engine
        return engine


def reset_engine_cache() -> None:
    with _DB_LOCK:
        for engine in _ENGINE_CACHE.values():
            engine.dispose()
        _ENGINE_CACHE.clear()
        _SCHEMA_READY.clear()


@contextmanager
def connect(db_path: Optional[str] = None) -> Iterator[Any]:
    initialize(db_path)
    engine = _engine_for(db_path)
    with engine.begin() as conn:
        yield conn


def initialize(db_path: Optional[str] = None) -> None:
    url = resolve_database_url(db_path)
    with _DB_LOCK:
        if url in _SCHEMA_READY:
            return

        if url.startswith("sqlite"):
            path = resolve_database_path(db_path)
            if path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

        engine = _engine_for(db_path)
        metadata.create_all(engine)
        _ensure_existing_columns(engine)
        _SCHEMA_READY.add(url)


def schema_status(db_path: Optional[str] = None) -> dict[str, Any]:
    """Return a safe schema summary without exposing connection credentials."""
    initialize(db_path)
    engine = _engine_for(db_path)
    table_names = set(inspect(engine).get_table_names())
    expected = set(EXPECTED_TABLE_NAMES)
    missing = sorted(expected - table_names)
    return {
        "ok": not missing,
        "database": "mysql" if is_mysql_url(resolve_database_url(db_path)) else "sqlite",
        "expected_tables": sorted(expected),
        "actual_tables": sorted(table_names),
        "missing_tables": missing,
    }


def _ensure_existing_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if "tasks" in inspector.get_table_names():
        _ensure_columns(
            engine,
            "tasks",
            {
                "tenant_id": "VARCHAR(64) NOT NULL DEFAULT 'dev'",
                "platform_user_id": "VARCHAR(64) NOT NULL DEFAULT 'dev'",
                "local_user_id": "VARCHAR(64) NOT NULL DEFAULT 'dev'",
                "app_code": "VARCHAR(64) NOT NULL DEFAULT 'wedding_ai_tool'",
                "status": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
            },
        )
    if "assets" in inspector.get_table_names():
        _ensure_columns(
            engine,
            "assets",
            {
                "tenant_id": "VARCHAR(64) NOT NULL DEFAULT 'dev'",
                "platform_user_id": "VARCHAR(64) NOT NULL DEFAULT 'dev'",
                "local_user_id": "VARCHAR(64) NOT NULL DEFAULT 'dev'",
                "visibility": "VARCHAR(16) NOT NULL DEFAULT 'personal'",
            },
        )


def _ensure_columns(engine: Engine, table_name: str, columns: dict[str, str]) -> None:
    existing = {column["name"] for column in inspect(engine).get_columns(table_name)}
    missing = [(name, ddl) for name, ddl in columns.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}"))


def _json_dumps(record: dict) -> str:
    return json.dumps(record or {}, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str) -> dict:
    data = json.loads(value or "{}")
    return data if isinstance(data, dict) else {}


def _scope_value(value: Optional[str], default: str) -> str:
    return (value or default).strip() or default


def normalize_record_scope(record: dict) -> dict:
    scoped = dict(record or {})
    scoped["tenant_id"] = _scope_value(scoped.get("tenant_id"), DEFAULT_TENANT_ID)
    scoped["platform_user_id"] = _scope_value(scoped.get("platform_user_id"), DEFAULT_PLATFORM_USER_ID)
    scoped["local_user_id"] = _scope_value(scoped.get("local_user_id"), DEFAULT_LOCAL_USER_ID)
    scoped["app_code"] = _scope_value(scoped.get("app_code"), DEFAULT_APP_CODE)
    return scoped


def _row_record(row: Any) -> Optional[dict]:
    if row is None:
        return None
    record = _json_loads(row.record_json)
    for field in ("tenant_id", "platform_user_id", "local_user_id", "app_code"):
        if hasattr(row, field):
            record[field] = getattr(row, field) or record.get(field, "")
    return record


def get_metadata(key: str, db_path: Optional[str] = None) -> Optional[str]:
    with connect(db_path) as conn:
        row = conn.execute(
            select(storage_meta.c.value).where(storage_meta.c.key == key)
        ).first()
    return str(row.value) if row else None


def set_metadata(key: str, value: str, db_path: Optional[str] = None) -> None:
    initialize(db_path)
    engine = _engine_for(db_path)
    with engine.begin() as conn:
        if engine.dialect.name == "mysql":
            conn.execute(
                text(
                    """
                    INSERT INTO storage_meta(`key`, value)
                    VALUES (:key, :value)
                    ON DUPLICATE KEY UPDATE value = VALUES(value)
                    """
                ),
                {"key": key, "value": value},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO storage_meta(key, value)
                    VALUES (:key, :value)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """
                ),
                {"key": key, "value": value},
            )


def upsert_task_record(record: dict, db_path: Optional[str] = None) -> None:
    record = normalize_record_scope(record)
    task_id = record.get("task_id")
    if not task_id:
        raise ValueError("Task record is missing task_id")

    now = now_iso()
    payload = {
        "task_id": task_id,
        "tenant_id": record["tenant_id"],
        "platform_user_id": record["platform_user_id"],
        "local_user_id": record["local_user_id"],
        "app_code": record["app_code"],
        "status": record.get("status", "pending"),
        "record_json": _json_dumps(record),
        "created_at": record.get("created_at", ""),
        "updated_at": now,
    }
    _upsert_by_pk(tasks, payload, ["task_id"], db_path=db_path)


def get_task_record(
    task_id: str,
    tenant_id: Optional[str] = None,
    platform_user_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    with connect(db_path) as conn:
        query = select(tasks).where(tasks.c.task_id == task_id)
        if tenant_id:
            query = query.where(tasks.c.tenant_id == tenant_id)
        if platform_user_id:
            query = query.where(tasks.c.platform_user_id == platform_user_id)
        row = conn.execute(query).first()
    return _row_record(row)


def list_task_records(
    tenant_id: Optional[str] = None,
    platform_user_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    with connect(db_path) as conn:
        query = select(tasks).order_by(tasks.c.created_at.desc())
        if tenant_id:
            query = query.where(tasks.c.tenant_id == tenant_id)
        if platform_user_id:
            query = query.where(tasks.c.platform_user_id == platform_user_id)
        rows = conn.execute(query).all()
    return [_row_record(row) for row in rows if _row_record(row) is not None]


def delete_task_record(
    task_id: str,
    tenant_id: Optional[str] = None,
    platform_user_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    with connect(db_path) as conn:
        query = select(tasks).where(tasks.c.task_id == task_id)
        if tenant_id:
            query = query.where(tasks.c.tenant_id == tenant_id)
        if platform_user_id:
            query = query.where(tasks.c.platform_user_id == platform_user_id)
        row = conn.execute(query).first()
        if row is None:
            return None
        conn.execute(delete(tasks).where(tasks.c.task_id == row.task_id))
    return _row_record(row)


def upsert_asset_record(record: dict, db_path: Optional[str] = None) -> None:
    record = normalize_record_scope(record)
    asset_id = record.get("asset_id")
    if not asset_id:
        raise ValueError("Asset record is missing asset_id")

    now = now_iso()
    payload = {
        "asset_id": asset_id,
        "tenant_id": record["tenant_id"],
        "platform_user_id": record["platform_user_id"],
        "local_user_id": record["local_user_id"],
        "category": record.get("category", "uncategorized"),
        "file_id": record.get("file_id", ""),
        "filename": record.get("filename", ""),
        "visibility": record.get("visibility", "personal"),
        "deleted_at": record.get("deleted_at", ""),
        "record_json": _json_dumps(record),
        "created_at": record.get("created_at", ""),
        "updated_at": now,
    }
    _upsert_by_pk(assets, payload, ["asset_id"], db_path=db_path)


def get_asset_record(
    asset_id: str,
    tenant_id: Optional[str] = None,
    platform_user_id: Optional[str] = None,
    include_shared: bool = False,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    with connect(db_path) as conn:
        query = select(assets).where(assets.c.asset_id == asset_id)
        if tenant_id:
            query = query.where(assets.c.tenant_id == tenant_id)
        if platform_user_id:
            user_filter = assets.c.platform_user_id == platform_user_id
            if include_shared:
                user_filter = or_(user_filter, assets.c.visibility.in_(SHARED_ASSET_VISIBILITIES))
            query = query.where(user_filter)
        row = conn.execute(query).first()
    return _row_record(row)


def list_asset_records(
    category: Optional[str] = None,
    include_deleted: bool = False,
    tenant_id: Optional[str] = None,
    platform_user_id: Optional[str] = None,
    include_shared: bool = False,
    db_path: Optional[str] = None,
) -> list[dict]:
    with connect(db_path) as conn:
        query = select(assets).order_by(assets.c.created_at.desc())
        if tenant_id:
            query = query.where(assets.c.tenant_id == tenant_id)
        if platform_user_id:
            user_filter = assets.c.platform_user_id == platform_user_id
            if include_shared:
                user_filter = or_(user_filter, assets.c.visibility.in_(SHARED_ASSET_VISIBILITIES))
            query = query.where(user_filter)
        if category:
            query = query.where(assets.c.category == category)
        if not include_deleted:
            query = query.where((assets.c.deleted_at.is_(None)) | (assets.c.deleted_at == ""))
        rows = conn.execute(query).all()
    return [_row_record(row) for row in rows if _row_record(row) is not None]


def soft_delete_asset_record(
    asset_id: str,
    deleted_at: str,
    tenant_id: Optional[str] = None,
    platform_user_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    record = get_asset_record(
        asset_id,
        tenant_id=tenant_id,
        platform_user_id=platform_user_id,
        db_path=db_path,
    )
    if record is None or record.get("deleted_at"):
        return None

    record = dict(record)
    record["deleted_at"] = deleted_at
    upsert_asset_record(record, db_path=db_path)
    return record


def delete_asset_record(
    asset_id: str,
    tenant_id: Optional[str] = None,
    platform_user_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    with connect(db_path) as conn:
        query = select(assets).where(assets.c.asset_id == asset_id)
        if tenant_id:
            query = query.where(assets.c.tenant_id == tenant_id)
        if platform_user_id:
            query = query.where(assets.c.platform_user_id == platform_user_id)
        row = conn.execute(query).first()
        if row is None:
            return None
        conn.execute(delete(assets).where(assets.c.asset_id == row.asset_id))
    return _row_record(row)


def upsert_quality_review_record(record: dict, db_path: Optional[str] = None) -> None:
    record = normalize_record_scope(record)
    task_id = record.get("task_id")
    if not task_id:
        raise ValueError("Quality review record is missing task_id")

    now = now_iso()
    payload = {
        "tenant_id": record["tenant_id"],
        "platform_user_id": record["platform_user_id"],
        "local_user_id": record["local_user_id"],
        "task_id": task_id,
        "record_json": _json_dumps(record),
        "created_at": record.get("created_at", ""),
        "updated_at": record.get("updated_at") or now,
    }
    _upsert_by_unique(
        quality_reviews,
        payload,
        ["tenant_id", "task_id"],
        db_path=db_path,
    )


def get_quality_review_record(
    task_id: str,
    tenant_id: Optional[str] = None,
    platform_user_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    with connect(db_path) as conn:
        query = select(quality_reviews).where(quality_reviews.c.task_id == task_id)
        if tenant_id:
            query = query.where(quality_reviews.c.tenant_id == tenant_id)
        if platform_user_id:
            query = query.where(quality_reviews.c.platform_user_id == platform_user_id)
        row = conn.execute(query).first()
    return _row_record(row)


def list_quality_review_records(
    tenant_id: Optional[str] = None,
    platform_user_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    with connect(db_path) as conn:
        query = select(quality_reviews).order_by(quality_reviews.c.updated_at.desc())
        if tenant_id:
            query = query.where(quality_reviews.c.tenant_id == tenant_id)
        if platform_user_id:
            query = query.where(quality_reviews.c.platform_user_id == platform_user_id)
        rows = conn.execute(query).all()
    return [_row_record(row) for row in rows if _row_record(row) is not None]


def get_terminal_user_binding(
    tenant_id: str,
    platform_user_id: str,
    db_path: Optional[str] = None,
) -> Optional[dict]:
    with connect(db_path) as conn:
        row = conn.execute(
            select(terminal_user_binding).where(
                terminal_user_binding.c.tenant_id == tenant_id,
                terminal_user_binding.c.platform_user_id == platform_user_id,
            )
        ).first()
    return dict(row._mapping) if row else None


def upsert_terminal_user_binding(
    *,
    tenant_id: str,
    platform_user_id: str,
    app_code: str,
    roles: Optional[list[str]] = None,
    status: str = "active",
    db_path: Optional[str] = None,
) -> dict:
    tenant_id = _scope_value(tenant_id, DEFAULT_TENANT_ID)
    platform_user_id = _scope_value(platform_user_id, DEFAULT_PLATFORM_USER_ID)
    app_code = _scope_value(app_code, DEFAULT_APP_CODE)
    existing = get_terminal_user_binding(tenant_id, platform_user_id, db_path=db_path)
    now = now_iso()
    local_user_id = existing["local_user_id"] if existing else f"tool_{uuid.uuid4().hex}"
    payload = {
        "tenant_id": tenant_id,
        "platform_user_id": platform_user_id,
        "local_user_id": local_user_id,
        "app_code": app_code,
        "roles_json": _json_dumps({"roles": roles or []}),
        "status": status,
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
    }
    _upsert_by_unique(
        terminal_user_binding,
        payload,
        ["tenant_id", "platform_user_id"],
        db_path=db_path,
    )
    return get_terminal_user_binding(tenant_id, platform_user_id, db_path=db_path) or payload


def create_tool_session(
    *,
    tenant_id: str,
    platform_user_id: str,
    local_user_id: str,
    username: str,
    app_code: str,
    roles: Optional[list[str]],
    expires_at: int,
    db_path: Optional[str] = None,
) -> dict:
    now = now_iso()
    session_id = uuid.uuid4().hex
    payload = {
        "session_id": session_id,
        "tenant_id": tenant_id,
        "platform_user_id": platform_user_id,
        "local_user_id": local_user_id,
        "username": username or platform_user_id,
        "app_code": app_code or DEFAULT_APP_CODE,
        "roles_json": _json_dumps({"roles": roles or []}),
        "expires_at": int(expires_at),
        "revoked_at": "",
        "created_at": now,
        "updated_at": now,
    }
    _upsert_by_pk(tool_sessions, payload, ["session_id"], db_path=db_path)
    return payload


def get_tool_session(session_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    with connect(db_path) as conn:
        row = conn.execute(
            select(tool_sessions).where(tool_sessions.c.session_id == session_id)
        ).first()
    if not row:
        return None
    data = dict(row._mapping)
    try:
        data["roles"] = _json_loads(data.get("roles_json", "{}")).get("roles", [])
    except Exception:
        data["roles"] = []
    return data


def revoke_tool_session(session_id: str, db_path: Optional[str] = None) -> bool:
    session = get_tool_session(session_id, db_path=db_path)
    if not session:
        return False
    session["revoked_at"] = now_iso()
    session["updated_at"] = session["revoked_at"]
    _upsert_by_pk(tool_sessions, session, ["session_id"], db_path=db_path)
    return True


def insert_business_log(record: dict, db_path: Optional[str] = None) -> None:
    record = normalize_record_scope(record)
    payload = {
        "tenant_id": record["tenant_id"],
        "platform_user_id": record["platform_user_id"],
        "local_user_id": record["local_user_id"],
        "trace_id": record.get("trace_id", ""),
        "action": record.get("action", ""),
        "resource_type": record.get("resource_type", ""),
        "resource_id": record.get("resource_id", ""),
        "record_json": _json_dumps(record),
        "created_at": record.get("created_at") or now_iso(),
    }
    with connect(db_path) as conn:
        conn.execute(business_logs.insert().values(**payload))


def _upsert_by_pk(table: Table, payload: dict, key_columns: list[str], db_path: Optional[str]) -> None:
    _upsert_by_unique(table, payload, key_columns, db_path=db_path)


def _upsert_by_unique(
    table: Table,
    payload: dict,
    key_columns: list[str],
    db_path: Optional[str],
) -> None:
    initialize(db_path)
    engine = _engine_for(db_path)
    with engine.begin() as conn:
        if engine.dialect.name == "mysql":
            assignments = ", ".join(
                f"{name} = VALUES({name})"
                for name in payload.keys()
                if name not in key_columns and name != "id"
            )
            columns = ", ".join(f"`{name}`" for name in payload.keys())
            values = ", ".join(f":{name}" for name in payload.keys())
            conn.execute(
                text(
                    f"INSERT INTO {table.name} ({columns}) VALUES ({values}) "
                    f"ON DUPLICATE KEY UPDATE {assignments}"
                ),
                payload,
            )
            return

        try:
            conn.execute(table.insert().values(**payload))
        except IntegrityError:
            conditions = [table.c[name] == payload[name] for name in key_columns]
            update_payload = {
                key: value
                for key, value in payload.items()
                if key not in key_columns and key != "id"
            }
            conn.execute(table.update().where(*conditions).values(**update_payload))
