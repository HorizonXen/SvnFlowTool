import contextlib
import importlib.util
import io
import json
import pathlib
import unittest
from unittest.mock import Mock, patch


ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("windows_entry", ROOT / "packaging" / "windows_entry.py")
windows_entry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(windows_entry)


class WindowsEntryTests(unittest.TestCase):
    def test_version_comes_from_release_json(self):
        release = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(windows_entry.main(["--version"]), 0)
        self.assertEqual(output.getvalue().strip(), f"SvnFlow {release['version']} ({release['build']})")

    def test_merge_command_dispatches_to_shared_engine(self):
        with patch.object(windows_entry.runpy, "run_module") as run:
            self.assertEqual(windows_entry.main(["merge", "audit", "--folder", "report"]), 0)
        run.assert_called_once_with("branch_sync", run_name="__main__")

    def test_unknown_command_is_rejected(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(windows_entry.main(["unsupported"]), 2)

    def test_no_argument_windows_launch_waits_for_user(self):
        terminal_input = Mock()
        terminal_input.isatty.return_value = True
        with (
            patch.object(windows_entry.sys, "platform", "win32"),
            patch.object(windows_entry.sys, "stdin", terminal_input),
            patch("builtins.input", return_value="") as wait_for_enter,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(windows_entry.main([]), 0)
        wait_for_enter.assert_called_once()


if __name__ == "__main__":
    unittest.main()
