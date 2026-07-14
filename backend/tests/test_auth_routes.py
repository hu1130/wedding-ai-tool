import importlib
import os
import unittest
from urllib.parse import parse_qs, urlparse

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover
    FastAPI = None
    TestClient = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None


AUTH_ROUTE_ENV_KEYS = {
    "APP_CODE",
    "AUTH_ENABLED",
    "AUTH_MODE",
    "USER_CENTER_LOGIN_URL",
}


@unittest.skipIf(TestClient is None, f"FastAPI test dependencies unavailable: {FASTAPI_IMPORT_ERROR}")
class AuthRouteTest(unittest.TestCase):
    def setUp(self):
        self.original_env = {key: os.environ.get(key) for key in AUTH_ROUTE_ENV_KEYS}

    def tearDown(self):
        for key, original in self.original_env.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original
        self._build_client()

    def _build_client(self, **env) -> TestClient:
        for key in AUTH_ROUTE_ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in env.items():
            if value is not None:
                os.environ[key] = value

        import backend.config as config_module
        import backend.security.auth as auth_module
        import backend.routers.auth as auth_router_module

        importlib.reload(config_module)
        importlib.reload(auth_module)
        auth_router_module = importlib.reload(auth_router_module)

        app = FastAPI()
        app.include_router(auth_router_module.router)
        app.include_router(auth_router_module.platform_router)
        return TestClient(app)

    def test_login_url_uses_user_center_template(self):
        client = self._build_client(
            AUTH_ENABLED="true",
            AUTH_MODE="platform_sso",
            APP_CODE="wedding_ai_tool",
            USER_CENTER_LOGIN_URL="https://login.example/sso?redirect={callback}&app={app_code}",
        )

        response = client.get("/api/auth/login-url?next=/works")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertTrue(payload["auth_enabled"])
        self.assertEqual("platform_sso", payload["auth_mode"])

        login_url = payload["login_url"]
        parsed = urlparse(login_url)
        params = parse_qs(parsed.query)
        self.assertEqual("login.example", parsed.netloc)
        self.assertEqual(["wedding_ai_tool"], params["app"])
        self.assertIn("/auth/platform", params["redirect"][0])
        self.assertIn("next=%2Fworks", params["redirect"][0])

    def test_session_returns_unauthenticated_without_401(self):
        client = self._build_client(
            AUTH_ENABLED="true",
            AUTH_MODE="platform_sso",
            APP_CODE="wedding_ai_tool",
            USER_CENTER_LOGIN_URL="https://login.example/sso?callback={callback}",
        )

        response = client.get("/api/auth/session")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertTrue(payload["auth_enabled"])
        self.assertFalse(payload["authenticated"])
        self.assertIsNone(payload["user"])

    def test_start_login_sanitizes_external_next_url(self):
        client = self._build_client(
            AUTH_ENABLED="true",
            AUTH_MODE="platform_sso",
            APP_CODE="wedding_ai_tool",
            USER_CENTER_LOGIN_URL="https://login.example/sso?callback={callback}",
        )

        response = client.get(
            "/api/auth/start?next=https://evil.example/phish",
            follow_redirects=False,
        )

        self.assertEqual(307, response.status_code)
        location = response.headers["location"]
        params = parse_qs(urlparse(location).query)
        self.assertEqual("login.example", urlparse(location).netloc)
        self.assertIn("next=%2F", params["callback"][0])
        self.assertNotIn("evil.example", params["callback"][0])

    def test_start_login_reports_missing_user_center_login_url(self):
        client = self._build_client(
            AUTH_ENABLED="true",
            AUTH_MODE="platform_sso",
            APP_CODE="wedding_ai_tool",
        )

        response = client.get("/api/auth/start?next=/works", follow_redirects=False)

        self.assertEqual(307, response.status_code)
        location = response.headers["location"]
        self.assertIn("/auth/error", location)
        self.assertIn("SERVICE_UNAVAILABLE", location)


if __name__ == "__main__":
    unittest.main()
