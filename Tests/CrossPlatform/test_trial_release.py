import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("trial_release", ROOT / "packaging" / "trial_release.py")
trial_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial_release)


class TrialReleaseTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        root = pathlib.Path(temporary.name)
        (root / "dist").mkdir()
        (root / "release.json").write_text(json.dumps({"version": "2.0.0", "build": 7}), encoding="utf-8")
        (root / "dist" / "SvnFlow-macOS-arm64-2.0.0-7.zip").write_bytes(b"trial-package")
        return temporary, root

    def test_publish_requires_approval_for_exact_archive(self):
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        with self.assertRaisesRegex(RuntimeError, "尚未确认"):
            trial_release.verify(root)
        trial_release.approve(root)
        trial_release.verify(root)
        (root / "dist" / "SvnFlow-macOS-arm64-2.0.0-7.zip").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "不匹配"):
            trial_release.verify(root)

    def test_version_change_invalidates_approval(self):
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        trial_release.approve(root)
        (root / "release.json").write_text(json.dumps({"version": "2.0.1", "build": 8}), encoding="utf-8")
        (root / "dist" / "SvnFlow-macOS-arm64-2.0.1-8.zip").write_bytes(b"next")
        with self.assertRaisesRegex(RuntimeError, "不匹配"):
            trial_release.verify(root)


if __name__ == "__main__":
    unittest.main()
