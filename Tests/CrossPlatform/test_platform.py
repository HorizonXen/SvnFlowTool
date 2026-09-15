import importlib
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in os.sys.path:
    os.sys.path.insert(0, str(SCRIPTS))

import platform_lock
import platform_settings


class PlatformSettingsTests(unittest.TestCase):
    def test_explicit_json_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "config.json"
            expected = [{"id": "dev-1", "path": str(pathlib.Path(folder) / "dev")}]
            path.write_text(json.dumps({"fixedCopies": expected}), encoding="utf-8")
            previous = os.environ.get("SVNFLOW_CONFIG")
            os.environ["SVNFLOW_CONFIG"] = str(path)
            try:
                importlib.reload(platform_settings)
                self.assertEqual(platform_settings.fixed_copies(), expected)
            finally:
                if previous is None:
                    os.environ.pop("SVNFLOW_CONFIG", None)
                else:
                    os.environ["SVNFLOW_CONFIG"] = previous
                importlib.reload(platform_settings)

    def test_manual_merge_roles_and_dynamic_names(self):
        copies = [
            {"id": "custom-a", "role": "source", "path": r"C:\SVN\Branch\Develop"},
            {"id": "custom-b", "role": "target", "path": r"C:\SVN\Branch\Stable"},
        ]
        with patch.object(platform_settings, "fixed_copies", return_value=copies):
            self.assertEqual(platform_settings.merge_copies(), (copies[0], copies[1]))
        self.assertEqual(platform_settings.endpoint_name(copies[0]["path"], "源目录"), "Develop")
        self.assertEqual(platform_settings.endpoint_name("/sample/Branch/Release/", "目标目录"), "Release")

    def test_same_manual_directory_is_rejected(self):
        copies = [
            {"id": "custom-a", "role": "dev", "path": "/wc/same"},
            {"id": "custom-b", "role": "release", "path": "/wc/same/"},
        ]
        with patch.object(platform_settings, "fixed_copies", return_value=copies):
            with self.assertRaisesRegex(RuntimeError, "两个不同"):
                platform_settings.merge_copies()


class PlatformLockTests(unittest.TestCase):
    def test_lock_can_be_acquired(self):
        with tempfile.TemporaryDirectory() as folder:
            with (pathlib.Path(folder) / "operation.lock").open("a+") as stream:
                platform_lock.try_lock(stream)
                platform_lock.unlock(stream)


if __name__ == "__main__":
    unittest.main()
