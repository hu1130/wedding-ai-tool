import importlib
import os
import tempfile
import unittest

from backend.models.asset import AssetLibrary
from backend.models.quality_review import QualityReview
from backend.models.task import Task
from backend.storage import database


class TenantIsolationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_env = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SQLITE_DB_PATH": os.environ.get("SQLITE_DB_PATH"),
            "AUTH_ENABLED": os.environ.get("AUTH_ENABLED"),
            "AUTH_MODE": os.environ.get("AUTH_MODE"),
            "AUTH_TOKEN_SECRET": os.environ.get("AUTH_TOKEN_SECRET"),
            "APP_CODE": os.environ.get("APP_CODE"),
        }
        self.old_task_data_file = Task.DATA_FILE
        self.old_asset_data_file = AssetLibrary.DATA_FILE
        os.environ.pop("DATABASE_URL", None)
        os.environ["SQLITE_DB_PATH"] = os.path.join(self.temp_dir.name, "tenant.db")
        Task.DATA_FILE = os.path.join(self.temp_dir.name, "tasks.json")
        AssetLibrary.DATA_FILE = os.path.join(self.temp_dir.name, "assets.json")
        database.reset_engine_cache()

    def tearDown(self):
        Task.DATA_FILE = self.old_task_data_file
        AssetLibrary.DATA_FILE = self.old_asset_data_file
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        database.reset_engine_cache()
        self.temp_dir.cleanup()

    def test_tasks_assets_and_reviews_are_tenant_scoped(self):
        task_a = Task(
            task_id="same_business_id_a",
            name="tenant a",
            tenant_id="tenant_a",
            platform_user_id="user_a",
            local_user_id="local_a",
        )
        task_a.save()
        task_b = Task(
            task_id="same_business_id_b",
            name="tenant b",
            tenant_id="tenant_b",
            platform_user_id="user_b",
            local_user_id="local_b",
        )
        task_b.save()

        self.assertIsNotNone(Task.get("same_business_id_a", tenant_id="tenant_a"))
        self.assertIsNone(Task.get("same_business_id_a", tenant_id="tenant_b"))
        self.assertEqual(["same_business_id_a"], [item.task_id for item in Task.list_internal("tenant_a")])
        self.assertEqual(["same_business_id_b"], [item.task_id for item in Task.list_internal("tenant_b")])

        asset_a = AssetLibrary.create(
            "a.png",
            "a.png",
            "dress",
            tenant_id="tenant_a",
            platform_user_id="user_a",
            local_user_id="local_a",
        )
        asset_b = AssetLibrary.create(
            "b.png",
            "b.png",
            "dress",
            tenant_id="tenant_b",
            platform_user_id="user_b",
            local_user_id="local_b",
        )

        self.assertIsNotNone(AssetLibrary.get(asset_a["asset_id"], tenant_id="tenant_a"))
        self.assertIsNone(AssetLibrary.get(asset_a["asset_id"], tenant_id="tenant_b"))
        self.assertEqual([asset_a["asset_id"]], [item["asset_id"] for item in AssetLibrary.list_all(tenant_id="tenant_a")])
        self.assertEqual([asset_b["asset_id"]], [item["asset_id"] for item in AssetLibrary.list_all(tenant_id="tenant_b")])

        QualityReview.upsert(
            "same_business_id_a",
            face_score=5,
            dress_score=5,
            pose_score=4,
            background_score=4,
            tenant_id="tenant_a",
            platform_user_id="user_a",
            local_user_id="local_a",
        )
        self.assertIsNotNone(QualityReview.get("same_business_id_a", tenant_id="tenant_a"))
        self.assertIsNone(QualityReview.get("same_business_id_a", tenant_id="tenant_b"))

    def test_same_tenant_users_are_scoped(self):
        task_a = Task(
            task_id="tenant_shared_user_a",
            name="user a task",
            tenant_id="tenant_shared",
            platform_user_id="user_a",
            local_user_id="local_a",
        )
        task_a.save()
        task_b = Task(
            task_id="tenant_shared_user_b",
            name="user b task",
            tenant_id="tenant_shared",
            platform_user_id="user_b",
            local_user_id="local_b",
        )
        task_b.save()

        self.assertIsNotNone(
            Task.get(
                "tenant_shared_user_a",
                tenant_id="tenant_shared",
                platform_user_id="user_a",
            )
        )
        self.assertIsNone(
            Task.get(
                "tenant_shared_user_a",
                tenant_id="tenant_shared",
                platform_user_id="user_b",
            )
        )
        self.assertEqual(
            ["tenant_shared_user_a"],
            [
                item.task_id
                for item in Task.list_internal(
                    tenant_id="tenant_shared",
                    platform_user_id="user_a",
                )
            ],
        )
        self.assertIsNone(
            Task.delete(
                "tenant_shared_user_a",
                tenant_id="tenant_shared",
                platform_user_id="user_b",
            )
        )
        self.assertIsNotNone(Task.get("tenant_shared_user_a", tenant_id="tenant_shared"))

        asset_a = AssetLibrary.create(
            "a-private.png",
            "a-private.png",
            "model",
            tenant_id="tenant_shared",
            platform_user_id="user_a",
            local_user_id="local_a",
        )
        asset_b = AssetLibrary.create(
            "b-private.png",
            "b-private.png",
            "model",
            tenant_id="tenant_shared",
            platform_user_id="user_b",
            local_user_id="local_b",
        )
        shared_asset = AssetLibrary.create(
            "shared-dress.png",
            "shared-dress.png",
            "dress",
            tenant_id="tenant_shared",
            platform_user_id="user_a",
            local_user_id="local_a",
            visibility="shared",
        )

        self.assertIsNone(
            AssetLibrary.get(
                asset_a["asset_id"],
                tenant_id="tenant_shared",
                platform_user_id="user_b",
            )
        )
        self.assertIsNotNone(
            AssetLibrary.get(
                shared_asset["asset_id"],
                tenant_id="tenant_shared",
                platform_user_id="user_b",
                include_shared=True,
            )
        )
        self.assertEqual(
            [asset_b["asset_id"]],
            [
                item["asset_id"]
                for item in AssetLibrary.list_all(
                    category="model",
                    tenant_id="tenant_shared",
                    platform_user_id="user_b",
                )
            ],
        )
        self.assertIsNone(
            AssetLibrary.delete(
                asset_a["asset_id"],
                tenant_id="tenant_shared",
                platform_user_id="user_b",
            )
        )
        self.assertIsNotNone(AssetLibrary.get(asset_a["asset_id"], tenant_id="tenant_shared"))

        QualityReview.upsert(
            "tenant_shared_user_a",
            face_score=5,
            dress_score=5,
            pose_score=4,
            background_score=4,
            tenant_id="tenant_shared",
            platform_user_id="user_a",
            local_user_id="local_a",
        )
        self.assertIsNotNone(
            QualityReview.get(
                "tenant_shared_user_a",
                tenant_id="tenant_shared",
                platform_user_id="user_a",
            )
        )
        self.assertIsNone(
            QualityReview.get(
                "tenant_shared_user_a",
                tenant_id="tenant_shared",
                platform_user_id="user_b",
            )
        )
        with self.assertRaises(ValueError):
            QualityReview.upsert(
                "tenant_shared_user_a",
                face_score=5,
                dress_score=5,
                pose_score=4,
                background_score=4,
                tenant_id="tenant_shared",
                platform_user_id="user_b",
                local_user_id="local_b",
            )

    def test_platform_sso_binding_and_session_token(self):
        os.environ["AUTH_ENABLED"] = "true"
        os.environ["AUTH_MODE"] = "platform_sso"
        os.environ["AUTH_TOKEN_SECRET"] = "test-secret"
        os.environ["APP_CODE"] = "wedding_ai_tool"
        database.reset_engine_cache()

        import backend.config as config_module
        import backend.security.auth as auth_module

        importlib.reload(config_module)
        auth = importlib.reload(auth_module)

        identity = auth.platform_identity_from_payload(
            {
                "tenant_id": "tenant_a",
                "platform_user_id": "platform_user_a",
                "username": "Alice",
                "roles": ["owner"],
                "app_code": "wedding_ai_tool",
            }
        )
        login = auth.create_platform_login(identity)
        parsed = auth.parse_access_token(login.access_token)

        self.assertEqual("tenant_a", parsed.tenant_id)
        self.assertEqual("platform_user_a", parsed.platform_user_id)
        self.assertTrue(parsed.local_user_id.startswith("tool_"))
        self.assertEqual(["owner"], parsed.roles)

        binding = database.get_terminal_user_binding("tenant_a", "platform_user_a")
        self.assertEqual(parsed.local_user_id, binding["local_user_id"])


if __name__ == "__main__":
    unittest.main()
