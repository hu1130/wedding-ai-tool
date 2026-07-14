import os
import tempfile
import unittest

from backend.storage.object_storage import (
    LocalObjectStorage,
    ObjectStorageConfig,
    create_object_storage,
    normalize_storage_key,
)


class ObjectStorageTest(unittest.TestCase):
    def test_local_storage_saves_reads_exists_and_deletes_upload_compatible_keys(self):
        with tempfile.TemporaryDirectory() as root:
            storage = LocalObjectStorage(root=root)

            saved_key = storage.save_bytes("bride.png", b"image-bytes", "image/png")

            self.assertEqual("uploads/bride.png", saved_key)
            self.assertTrue(os.path.exists(os.path.join(root, "uploads", "bride.png")))
            self.assertTrue(storage.exists("bride.png"))
            self.assertEqual(b"image-bytes", storage.get_bytes("bride.png"))
            with storage.open("bride.png") as f:
                self.assertEqual(b"image-bytes", f.read())
            self.assertEqual("/storage/uploads/bride.png", storage.public_url("bride.png"))
            self.assertEqual(storage.public_url("bride.png"), storage.presigned_url("bride.png"))
            self.assertTrue(storage.delete("bride.png"))
            self.assertFalse(storage.exists("bride.png"))
            self.assertFalse(storage.delete("bride.png"))

    def test_local_storage_preserves_outputs_keys(self):
        with tempfile.TemporaryDirectory() as root:
            storage = LocalObjectStorage(root=root)

            saved_key = storage.save_bytes("outputs/task-1/final.jpg", b"final", "image/jpeg")

            self.assertEqual("outputs/task-1/final.jpg", saved_key)
            self.assertTrue(os.path.exists(os.path.join(root, "outputs", "task-1", "final.jpg")))
            self.assertEqual(b"final", storage.get_bytes("outputs/task-1/final.jpg"))

    def test_normalize_storage_key_rejects_unsafe_paths(self):
        self.assertEqual("uploads/file.jpg", normalize_storage_key("file.jpg"))
        self.assertEqual("outputs/task/final.jpg", normalize_storage_key(r"outputs\task\final.jpg"))

        for key in ("", "../x.jpg", "uploads/../x.jpg", "/tmp/x.jpg", "C:/tmp/x.jpg"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    normalize_storage_key(key)

    def test_create_object_storage_defaults_to_local_without_oss_dependency(self):
        with tempfile.TemporaryDirectory() as root:
            storage = create_object_storage(ObjectStorageConfig(mode="local", local_root=root))

            saved_key = storage.save_bytes("sample.webp", b"webp", "image/webp")

            self.assertEqual("uploads/sample.webp", saved_key)
            self.assertEqual(b"webp", storage.get_bytes(saved_key))

    def test_oss_mode_validates_required_config_without_network(self):
        with self.assertRaisesRegex(ValueError, "OSS_ENDPOINT"):
            create_object_storage(ObjectStorageConfig(mode="oss"))

        config = ObjectStorageConfig(
            mode="oss",
            oss_endpoint="https://oss-cn-example.aliyuncs.com",
            oss_bucket="wedding-test",
            oss_access_key_id="test-access-key-id",
            oss_access_key_secret="test-access-key-secret",
            oss_public_base_url="https://cdn.example.test/media",
        )

        storage = create_object_storage(config)
        self.assertEqual(
            "https://cdn.example.test/media/uploads/sample.png",
            storage.public_url("sample.png"),
        )

    def test_invalid_storage_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "OBJECT_STORAGE_MODE"):
            create_object_storage(ObjectStorageConfig(mode="ftp"))


if __name__ == "__main__":
    unittest.main()
