import importlib
import json
import os
import unittest

try:
    from fastapi import Depends, FastAPI, HTTPException
    from fastapi.security import HTTPAuthorizationCredentials
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover
    Depends = None
    FastAPI = None
    HTTPException = Exception
    HTTPAuthorizationCredentials = None
    TestClient = None
    FASTAPI_IMPORT_ERROR = exc
else:
    FASTAPI_IMPORT_ERROR = None


AUTH_ENV_KEYS = {
    "AUTH_ENABLED",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "APP_USERS_JSON",
    "AUTH_TOKEN_SECRET",
    "AUTH_TOKEN_TTL_SECONDS",
}


@unittest.skipIf(TestClient is None, f"FastAPI test dependencies unavailable: {FASTAPI_IMPORT_ERROR}")
class AuthTest(unittest.TestCase):
    def setUp(self):
        self.original_env = {key: os.environ.get(key) for key in AUTH_ENV_KEYS}

    def tearDown(self):
        for key in AUTH_ENV_KEYS:
            original = self.original_env[key]
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original
        self._reload_auth()

    def _reload_auth(self, **env):
        for key in AUTH_ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in env.items():
            if value is not None:
                os.environ[key] = value

        import backend.config as config_module
        import backend.security.auth as auth_module

        importlib.reload(config_module)
        return importlib.reload(auth_module)

    def test_auth_disabled_returns_dev_user(self):
        auth = self._reload_auth(AUTH_ENABLED="false")

        user = auth.current_user(None)

        self.assertFalse(auth.is_auth_enabled())
        self.assertEqual("dev", user.user_id)
        self.assertEqual("anonymous", user.username)
        self.assertFalse(user.is_authenticated)

    def test_admin_credentials_issue_and_parse_token(self):
        auth = self._reload_auth(
            AUTH_ENABLED="true",
            ADMIN_USERNAME="owner",
            ADMIN_PASSWORD="test-password",
            AUTH_TOKEN_SECRET="test-token-secret",
        )

        user = auth.authenticate_user("owner", "test-password")
        self.assertIsNotNone(user)
        self.assertEqual("owner", user.user_id)

        token = auth.create_access_token(user)
        parsed_user = auth.parse_access_token(token)

        self.assertEqual("owner", parsed_user.username)
        self.assertEqual("owner", parsed_user.user_id)

        app = FastAPI()

        @app.get("/protected")
        def protected(current=Depends(auth.current_user)):
            return {"user_id": current.user_id, "username": current.username}

        client = TestClient(app)
        response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(200, response.status_code)
        self.assertEqual({"user_id": "owner", "username": "owner"}, response.json())

    def test_wrong_password_rejected(self):
        auth = self._reload_auth(
            AUTH_ENABLED="true",
            ADMIN_USERNAME="owner",
            ADMIN_PASSWORD="test-password",
            AUTH_TOKEN_SECRET="test-token-secret",
        )

        self.assertIsNone(auth.authenticate_user("owner", "wrong-password"))
        with self.assertRaises(HTTPException) as ctx:
            auth.login_user(auth.LoginRequest(username="owner", password="wrong-password"))
        self.assertEqual(401, ctx.exception.status_code)

    def test_invalid_or_missing_token_rejected_when_enabled(self):
        auth = self._reload_auth(
            AUTH_ENABLED="true",
            ADMIN_USERNAME="owner",
            ADMIN_PASSWORD="test-password",
            AUTH_TOKEN_SECRET="test-token-secret",
        )

        with self.assertRaises(HTTPException) as missing_ctx:
            auth.current_user(None)
        self.assertEqual(401, missing_ctx.exception.status_code)

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid.token")
        with self.assertRaises(HTTPException) as invalid_ctx:
            auth.current_user(credentials)
        self.assertEqual(401, invalid_ctx.exception.status_code)

    def test_expired_token_rejected(self):
        auth = self._reload_auth(
            AUTH_ENABLED="true",
            ADMIN_USERNAME="owner",
            ADMIN_PASSWORD="test-password",
            AUTH_TOKEN_SECRET="test-token-secret",
        )
        user = auth.authenticate_user("owner", "test-password")
        token = auth.create_access_token(user, ttl_seconds=-1)

        with self.assertRaises(HTTPException) as ctx:
            auth.parse_access_token(token)

        self.assertEqual(401, ctx.exception.status_code)
        self.assertEqual("Token expired", ctx.exception.detail)

    def test_app_users_json_supplies_user_id(self):
        users = [
            {
                "username": "alice",
                "password": "alice-password",
                "user_id": "tenant_alice",
            }
        ]
        auth = self._reload_auth(
            AUTH_ENABLED="true",
            APP_USERS_JSON=json.dumps(users),
            AUTH_TOKEN_SECRET="test-token-secret",
        )

        user = auth.authenticate_user("alice", "alice-password")
        self.assertIsNotNone(user)
        self.assertEqual("tenant_alice", user.user_id)

        response = auth.login_user(auth.LoginRequest(username="alice", password="alice-password"))
        self.assertEqual("bearer", response.token_type)
        self.assertEqual("tenant_alice", response.user.user_id)
        self.assertEqual("alice", auth.parse_access_token(response.access_token).username)


if __name__ == "__main__":
    unittest.main()
