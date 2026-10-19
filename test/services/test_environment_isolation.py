"""Test chạy trong thư mục tạm, không chạm vào config.toml và storage thật."""

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.utils import utils

PROJECT_ROOT = os.path.abspath(Path(__file__).parent.parent.parent)


class TestEnvironmentIsolation(unittest.TestCase):
    def test_config_and_storage_point_outside_the_project(self):
        self.assertEqual(os.environ.get("MPT_TESTING"), "1")
        self.assertNotEqual(
            os.path.abspath(config.config_file), os.path.abspath(config._DEFAULT_CONFIG_FILE)
        )
        for path in (config.config_file, utils.storage_dir()):
            self.assertFalse(os.path.abspath(path).startswith(PROJECT_ROOT + os.sep), path)

    def test_test_config_has_no_real_credentials(self):
        # config.toml tạm chép từ config.example.toml: không có khoá của người dùng.
        self.assertEqual(config._cfg.get("telegram", {}).get("bot_token", ""), "")
        self.assertFalse(config.app.get("pixabay_api_keys"))
        self.assertFalse(config.app.get("openai_api_key"))

    def test_save_config_refuses_the_real_config_file(self):
        with TemporaryDirectory() as temp_dir:
            # Giả lập "file thật" trong thư mục tạm để không bao giờ chạm file thật.
            real_path = Path(temp_dir) / "config.toml"
            real_path.write_text("[app]\nvideo_source = \"pixabay\"\n", encoding="utf-8")
            config.app["isolation_guard_test"] = "must-not-be-saved"
            try:
                with (
                    patch.object(config, "_DEFAULT_CONFIG_FILE", str(real_path)),
                    patch.object(config, "config_file", str(real_path)),
                ):
                    with self.assertRaises(RuntimeError):
                        config.save_config()
            finally:
                config.app.pop("isolation_guard_test", None)

            self.assertEqual(
                real_path.read_text(encoding="utf-8"), "[app]\nvideo_source = \"pixabay\"\n"
            )


if __name__ == "__main__":
    unittest.main()
