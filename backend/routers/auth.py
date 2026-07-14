"""Authentication endpoints."""

from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.config import settings
from backend.security.auth import (
    AUTH_COOKIE_NAME,
    AuthConfigError,
    AuthUser,
    LoginRequest,
    LoginResponse,
    UserPublic,
    create_platform_login,
    current_user_from_request,
    exchange_platform_ticket,
    is_platform_sso_mode,
    login_user,
    parse_access_token,
    to_public_user,
    token_from_request,
)
from backend.storage import database

router = APIRouter(prefix="/api/auth", tags=["auth"])
platform_router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
        max_age=max(0, settings.auth_token_ttl_seconds),
    )


def _safe_next_path(next_path: str) -> str:
    value = (next_path or "/").strip()
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _with_query_params(url: str, params: dict[str, str]) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in params.items():
        query.setdefault(key, value)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def _platform_callback_url(request: Request, next_path: str) -> str:
    callback_base = str(request.url_for("platform_sso_callback"))
    return _with_query_params(callback_base, {"next": _safe_next_path(next_path)})


def _build_platform_login_url(request: Request, next_path: str) -> str:
    login_url = settings.user_center_login_url.strip()
    if not login_url:
        raise AuthConfigError("USER_CENTER_LOGIN_URL is required for platform SSO login")

    safe_next = _safe_next_path(next_path)
    callback_url = _platform_callback_url(request, safe_next)
    replacements = {
        "{callback}": quote(callback_url, safe=""),
        "{callback_raw}": callback_url,
        "{next}": quote(safe_next, safe=""),
        "{next_raw}": safe_next,
        "{app_code}": quote(settings.app_code, safe=""),
        "{app_code_raw}": settings.app_code,
    }
    if any(token in login_url for token in replacements):
        for token, value in replacements.items():
            login_url = login_url.replace(token, value)
        return login_url

    return _with_query_params(
        login_url,
        {
            "callback": callback_url,
            "next": safe_next,
            "app_code": settings.app_code,
        },
    )


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, response: Response):
    if is_platform_sso_mode():
        raise HTTPException(403, detail="Password login is disabled in platform SSO mode")
    result = login_user(req)
    _set_auth_cookie(response, result.access_token)
    return result


@router.get("/login-url")
async def login_url(request: Request, next: str = Query("/", alias="next")):
    safe_next = _safe_next_path(next)
    if not settings.auth_enabled:
        return {
            "auth_enabled": False,
            "auth_mode": settings.auth_mode,
            "login_url": safe_next,
        }
    if not is_platform_sso_mode():
        raise HTTPException(404, detail="Platform SSO is not enabled")
    return {
        "auth_enabled": True,
        "auth_mode": settings.auth_mode,
        "login_url": _build_platform_login_url(request, safe_next),
    }


@router.get("/session")
async def session(request: Request):
    if not settings.auth_enabled:
        return {
            "auth_enabled": False,
            "auth_mode": settings.auth_mode,
            "authenticated": False,
            "user": None,
        }

    token = token_from_request(request)
    if not token:
        return {
            "auth_enabled": True,
            "auth_mode": settings.auth_mode,
            "authenticated": False,
            "user": None,
        }

    try:
        user = parse_access_token(token)
    except HTTPException:
        return {
            "auth_enabled": True,
            "auth_mode": settings.auth_mode,
            "authenticated": False,
            "user": None,
        }

    return {
        "auth_enabled": True,
        "auth_mode": settings.auth_mode,
        "authenticated": True,
        "user": to_public_user(user),
    }


@router.get("/start")
async def start_login(request: Request, next: str = Query("/", alias="next")):
    safe_next = _safe_next_path(next)
    if not settings.auth_enabled:
        return RedirectResponse(url=safe_next)
    if not is_platform_sso_mode():
        return RedirectResponse(url="/auth/error?" + urlencode({"code": "AUTH_REQUIRED"}))
    try:
        return RedirectResponse(url=_build_platform_login_url(request, safe_next))
    except AuthConfigError as exc:
        return RedirectResponse(
            url="/auth/error?" + urlencode({"code": "SERVICE_UNAVAILABLE", "message": str(exc)})
        )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    user: AuthUser = Depends(current_user_from_request),
):
    token = token_from_request(request)
    if token:
        try:
            parsed = parse_access_token(token)
            if parsed.session_id:
                database.revoke_tool_session(parsed.session_id)
        except HTTPException:
            pass
    elif user.session_id:
        database.revoke_tool_session(user.session_id)
    response.delete_cookie(AUTH_COOKIE_NAME)
    return {"success": True}


@router.get("/me", response_model=UserPublic)
async def me(user: AuthUser = Depends(current_user_from_request)):
    return to_public_user(user)


@platform_router.get("/platform")
async def platform_sso_callback(
    ticket: str = Query(..., min_length=1),
    next: str = Query("", alias="next"),
):
    if not is_platform_sso_mode():
        raise HTTPException(404, detail="Platform SSO is not enabled")

    try:
        identity = await exchange_platform_ticket(ticket)
        result = create_platform_login(identity)
    except AuthConfigError as exc:
        return RedirectResponse(
            url="/auth/error?" + urlencode({"code": "SERVICE_UNAVAILABLE", "message": str(exc)})
        )
    except HTTPException as exc:
        code = "AUTH_REQUIRED" if exc.status_code == 401 else "NO_PERMISSION"
        return RedirectResponse(url="/auth/error?" + urlencode({"code": code}))

    target = next or settings.user_center_callback_success_path or "/"
    if not target.startswith("/"):
        target = "/"
    response = RedirectResponse(url=target)
    _set_auth_cookie(response, result.access_token)
    return response


@platform_router.get("/error", response_class=HTMLResponse)
async def auth_error_page(
    code: str = Query("AUTH_REQUIRED"),
    message: str = Query(""),
):
    safe_code = code if code in {
        "AUTH_REQUIRED",
        "NO_PERMISSION",
        "TICKET_EXPIRED",
        "TICKET_USED",
        "APP_NOT_AVAILABLE",
        "SERVICE_UNAVAILABLE",
    } else "AUTH_REQUIRED"
    display = message or {
        "AUTH_REQUIRED": "Login is required or the session has expired.",
        "NO_PERMISSION": "You do not have permission to access this tool.",
        "TICKET_EXPIRED": "The login ticket has expired.",
        "TICKET_USED": "The login ticket has already been used.",
        "APP_NOT_AVAILABLE": "This tool is unavailable.",
        "SERVICE_UNAVAILABLE": "The login service is temporarily unavailable.",
    }[safe_code]
    return f"""
    <!doctype html>
    <html lang="zh-CN">
      <head>
        <meta charset="utf-8" />
        <title>{safe_code}</title>
        <style>
          body {{ font-family: Arial, sans-serif; margin: 48px; color: #1f2933; }}
          main {{ max-width: 560px; }}
          h1 {{ font-size: 24px; margin-bottom: 12px; }}
          p {{ line-height: 1.6; }}
        </style>
      </head>
      <body>
        <main>
          <h1>{safe_code}</h1>
          <p>{display}</p>
        </main>
      </body>
    </html>
    """
