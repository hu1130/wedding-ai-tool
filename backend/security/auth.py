"""Authentication primitives for local development and platform SSO.

Production should use ``AUTH_MODE=platform_sso``. The local password flow is
kept only for development and automated tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from backend.config import settings
from backend.storage import database


TOKEN_TYPE = "bearer"
AUTH_COOKIE_NAME = "wedding_auth_token"
_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    username: str
    is_authenticated: bool = True
    tenant_id: str = database.DEFAULT_TENANT_ID
    platform_user_id: str = database.DEFAULT_PLATFORM_USER_ID
    local_user_id: str = database.DEFAULT_LOCAL_USER_ID
    roles: list[str] = field(default_factory=list)
    app_code: str = database.DEFAULT_APP_CODE
    session_id: str = ""

    def storage_scope(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "platform_user_id": self.platform_user_id,
            "local_user_id": self.local_user_id,
            "app_code": self.app_code,
        }


@dataclass(frozen=True)
class _ConfiguredUser:
    username: str
    password: str
    user_id: str


@dataclass(frozen=True)
class PlatformIdentity:
    tenant_id: str
    platform_user_id: str
    username: str = ""
    roles: list[str] = field(default_factory=list)
    app_code: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class UserPublic(BaseModel):
    user_id: str
    username: str
    is_authenticated: bool = True
    tenant_id: str = database.DEFAULT_TENANT_ID
    platform_user_id: str = database.DEFAULT_PLATFORM_USER_ID
    local_user_id: str = database.DEFAULT_LOCAL_USER_ID
    roles: list[str] = []
    app_code: str = database.DEFAULT_APP_CODE


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = TOKEN_TYPE
    expires_at: int
    user: UserPublic


class AuthConfigError(RuntimeError):
    """Raised when environment-provided auth configuration is invalid."""


def is_auth_enabled() -> bool:
    return bool(settings.auth_enabled)


def is_platform_sso_mode() -> bool:
    return settings.auth_mode == "platform_sso"


def development_user() -> AuthUser:
    return AuthUser(
        user_id=database.DEFAULT_LOCAL_USER_ID,
        username="anonymous",
        is_authenticated=False,
        tenant_id=database.DEFAULT_TENANT_ID,
        platform_user_id=database.DEFAULT_PLATFORM_USER_ID,
        local_user_id=database.DEFAULT_LOCAL_USER_ID,
        roles=[],
        app_code=settings.app_code,
    )


def _unauthorized(detail: str = "Invalid or missing credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str = "Forbidden") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _default_user_id(username: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_.-]+", "_", username.strip()).strip("._-")
    return value.lower() or "user"


def _coerce_user_record(username: str, value: Any) -> Optional[_ConfiguredUser]:
    username = (username or "").strip()
    if not username:
        return None

    password = ""
    user_id = _default_user_id(username)

    if isinstance(value, str):
        password = value
    elif isinstance(value, dict):
        password = str(value.get("password") or "")
        user_id = str(value.get("user_id") or user_id).strip() or user_id
    else:
        return None

    if not password:
        return None
    return _ConfiguredUser(username=username, password=password, user_id=user_id)


def _users_from_json(raw_json: str) -> dict[str, _ConfiguredUser]:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise AuthConfigError("APP_USERS_JSON is not valid JSON") from exc

    records: list[_ConfiguredUser] = []
    if isinstance(data, dict):
        for username, value in data.items():
            record = _coerce_user_record(str(username), value)
            if record:
                records.append(record)
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            username = str(item.get("username") or "")
            record = _coerce_user_record(username, item)
            if record:
                records.append(record)
    else:
        raise AuthConfigError("APP_USERS_JSON must be an object or a list")

    return {record.username: record for record in records}


def configured_users() -> dict[str, _ConfiguredUser]:
    raw_users = (settings.app_users_json or "").strip()
    if raw_users:
        return _users_from_json(raw_users)

    username = (settings.admin_username or "").strip()
    password = settings.admin_password or ""
    record = _coerce_user_record(username, {"password": password, "user_id": _default_user_id(username)})
    return {record.username: record} if record else {}


def authenticate_user(username: str, password: str) -> Optional[AuthUser]:
    if is_platform_sso_mode():
        return None

    users = configured_users()
    record = users.get((username or "").strip())
    if not record:
        return None
    if not hmac.compare_digest(record.password, password or ""):
        return None
    return AuthUser(
        user_id=record.user_id,
        username=record.username,
        is_authenticated=True,
        tenant_id=database.DEFAULT_TENANT_ID,
        platform_user_id=record.user_id,
        local_user_id=record.user_id,
        roles=["admin"] if record.username == settings.admin_username else [],
        app_code=settings.app_code,
    )


def _token_secret() -> str:
    return settings.auth_token_secret or settings.admin_password or "local-dev-auth-secret"


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _sign(payload: str) -> str:
    signature = hmac.new(
        _token_secret().encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _b64encode(signature)


def issue_access_token(
    user: AuthUser,
    ttl_seconds: Optional[int] = None,
    session_id: str = "",
) -> tuple[str, int]:
    now = int(time.time())
    ttl = settings.auth_token_ttl_seconds if ttl_seconds is None else int(ttl_seconds)
    expires_at = now + ttl
    payload = {
        "sub": user.username,
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "platform_user_id": user.platform_user_id,
        "local_user_id": user.local_user_id,
        "roles": user.roles,
        "app_code": user.app_code,
        "sid": session_id or user.session_id,
        "iat": now,
        "exp": expires_at,
    }
    encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{encoded_payload}.{_sign(encoded_payload)}", expires_at


def create_access_token(user: AuthUser, ttl_seconds: Optional[int] = None) -> str:
    token, _ = issue_access_token(user, ttl_seconds=ttl_seconds)
    return token


def _payload_from_token(token: str) -> dict:
    if not token or "." not in token:
        raise _unauthorized()

    encoded_payload, signature = token.split(".", 1)
    if not hmac.compare_digest(_sign(encoded_payload), signature):
        raise _unauthorized()

    try:
        payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise _unauthorized() from exc
    if not isinstance(payload, dict):
        raise _unauthorized()
    return payload


def parse_access_token(token: str, now: Optional[int] = None) -> AuthUser:
    payload = _payload_from_token(token)
    current_time = int(time.time()) if now is None else now
    try:
        expires_at = int(payload.get("exp"))
    except (TypeError, ValueError) as exc:
        raise _unauthorized() from exc

    if expires_at <= current_time:
        raise _unauthorized("Token expired")

    session_id = str(payload.get("sid") or "")
    if session_id:
        session = database.get_tool_session(session_id)
        if not session or session.get("revoked_at"):
            raise _unauthorized("Session expired")
        if int(session.get("expires_at") or 0) <= current_time:
            raise _unauthorized("Session expired")
        return AuthUser(
            user_id=session["local_user_id"],
            username=session.get("username") or session["platform_user_id"],
            is_authenticated=True,
            tenant_id=session["tenant_id"],
            platform_user_id=session["platform_user_id"],
            local_user_id=session["local_user_id"],
            roles=list(session.get("roles") or []),
            app_code=session.get("app_code") or settings.app_code,
            session_id=session_id,
        )

    if is_platform_sso_mode():
        raise _unauthorized("Platform session required")

    username = str(payload.get("sub") or "")
    user_id = str(payload.get("user_id") or "")
    record = configured_users().get(username)
    if not record or record.user_id != user_id:
        raise _unauthorized()

    return AuthUser(
        user_id=user_id,
        username=username,
        is_authenticated=True,
        tenant_id=str(payload.get("tenant_id") or database.DEFAULT_TENANT_ID),
        platform_user_id=str(payload.get("platform_user_id") or user_id),
        local_user_id=str(payload.get("local_user_id") or user_id),
        roles=list(payload.get("roles") or []),
        app_code=str(payload.get("app_code") or settings.app_code),
    )


def login_user(req: LoginRequest) -> LoginResponse:
    if is_platform_sso_mode():
        raise _forbidden("Password login is disabled in platform SSO mode")

    user = authenticate_user(req.username, req.password)
    if not user:
        raise _unauthorized("Invalid username or password")

    token, expires_at = issue_access_token(user)
    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user=to_public_user(user),
    )


def to_public_user(user: AuthUser) -> UserPublic:
    return UserPublic(
        user_id=user.user_id,
        username=user.username,
        is_authenticated=user.is_authenticated,
        tenant_id=user.tenant_id,
        platform_user_id=user.platform_user_id,
        local_user_id=user.local_user_id,
        roles=list(user.roles or []),
        app_code=user.app_code,
    )


def current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthUser:
    if not is_auth_enabled():
        return development_user()

    if not credentials or credentials.scheme.lower() != TOKEN_TYPE or not credentials.credentials:
        raise _unauthorized("Authentication required")

    return parse_access_token(credentials.credentials)


def current_user_from_request(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthUser:
    if not is_auth_enabled():
        return development_user()

    token = token_from_request(request, credentials)
    if not token:
        raise _unauthorized("Authentication required")

    return parse_access_token(token)


def token_from_request(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None,
) -> str:
    if credentials and credentials.scheme.lower() == TOKEN_TYPE and credentials.credentials:
        return credentials.credentials
    return request.cookies.get(AUTH_COOKIE_NAME, "")


async def exchange_platform_ticket(ticket: str) -> PlatformIdentity:
    if not settings.user_center_base_url:
        raise AuthConfigError("USER_CENTER_BASE_URL is required for platform SSO")
    if not settings.user_center_client_id or not settings.user_center_client_secret:
        raise AuthConfigError("USER_CENTER_CLIENT_ID and USER_CENTER_CLIENT_SECRET are required")

    url = f"{settings.user_center_base_url}{settings.user_center_sso_exchange_path}"
    payload = {
        "ticket": ticket,
        "app_code": settings.app_code,
        "client_id": settings.user_center_client_id,
        "client_secret": settings.user_center_client_secret,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=payload)
    if response.status_code >= 400:
        raise _unauthorized("SSO ticket exchange failed")

    data = response.json()
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    return platform_identity_from_payload(data)


def platform_identity_from_payload(payload: dict[str, Any]) -> PlatformIdentity:
    tenant_id = str(
        payload.get("tenant_id")
        or payload.get("tenantId")
        or payload.get("tenant")
        or ""
    ).strip()
    platform_user_id = str(
        payload.get("platform_user_id")
        or payload.get("platformUserId")
        or payload.get("user_id")
        or payload.get("userId")
        or ""
    ).strip()
    if not tenant_id or not platform_user_id:
        raise AuthConfigError("SSO response is missing tenant_id or platform_user_id")

    raw_roles = payload.get("roles") or payload.get("role_codes") or payload.get("roleCodes") or []
    if isinstance(raw_roles, str):
        roles = [role.strip() for role in raw_roles.split(",") if role.strip()]
    elif isinstance(raw_roles, list):
        roles = [str(role).strip() for role in raw_roles if str(role).strip()]
    else:
        roles = []

    username = str(
        payload.get("username")
        or payload.get("display_name")
        or payload.get("displayName")
        or platform_user_id
    ).strip()
    app_code = str(payload.get("app_code") or payload.get("appCode") or settings.app_code).strip()
    return PlatformIdentity(
        tenant_id=tenant_id,
        platform_user_id=platform_user_id,
        username=username,
        roles=roles,
        app_code=app_code or settings.app_code,
    )


def create_platform_login(identity: PlatformIdentity) -> LoginResponse:
    binding = database.upsert_terminal_user_binding(
        tenant_id=identity.tenant_id,
        platform_user_id=identity.platform_user_id,
        app_code=identity.app_code or settings.app_code,
        roles=identity.roles,
        status="active",
    )
    if binding.get("status") != "active":
        raise _forbidden("User binding is disabled")

    now = int(time.time())
    expires_at = now + settings.auth_token_ttl_seconds
    session = database.create_tool_session(
        tenant_id=identity.tenant_id,
        platform_user_id=identity.platform_user_id,
        local_user_id=binding["local_user_id"],
        username=identity.username or identity.platform_user_id,
        app_code=identity.app_code or settings.app_code,
        roles=identity.roles,
        expires_at=expires_at,
    )
    user = AuthUser(
        user_id=session["local_user_id"],
        username=session["username"],
        is_authenticated=True,
        tenant_id=session["tenant_id"],
        platform_user_id=session["platform_user_id"],
        local_user_id=session["local_user_id"],
        roles=identity.roles,
        app_code=session["app_code"],
        session_id=session["session_id"],
    )
    token, token_expires_at = issue_access_token(user, session_id=session["session_id"])
    return LoginResponse(
        access_token=token,
        expires_at=token_expires_at,
        user=to_public_user(user),
    )
