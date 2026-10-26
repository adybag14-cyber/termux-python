import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_python_recipe import prepare_current_build_system


class HostPythonHelperTests(unittest.TestCase):
    def make_tree(self, root, number="0008"):
        helper = root / "scripts/build/setup/termux_setup_build_python.sh"
        helper.parent.mkdir(parents=True)
        (root / "packages/python").mkdir(parents=True)
        helper.write_text(
            'termux_setup_build_python() {\n'
            f'\tfor f in "$TERMUX_SCRIPTDIR"/packages/python/{number}-fix-ctypes-util-find_library.patch; do\n'
            '\t\tcat "$f"\n\tdone\n}\ntermux_setup_build_python\n', encoding="utf-8",
        )
        return helper

    def test_renumbered_upstream_loops_and_idempotence(self):
        for number in ("0007", "0008", "0012"):
            with self.subTest(number=number), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                helper = self.make_tree(root, number)
                prepare_current_build_system(root, "3.14")
                first = helper.read_bytes()
                self.assertIn(b"[0-9][0-9][0-9][0-9]-fix-ctypes", first)
                self.assertEqual(first.count(b'[[ -f "$f" ]] || continue'), 1)
                prepare_current_build_system(root, "3.14")
                self.assertEqual(first, helper.read_bytes())

    @unittest.skipUnless(shutil.which("bash"), "bash is required")
    def test_historical_patch_number_and_absent_patch_execute_safely(self):
        with tempfile.TemporaryDirectory(prefix="python helper ") as td:
            root = Path(td)
            helper = self.make_tree(root, "0007")
            patch = root / "packages/python/0008-fix-ctypes-util-find_library.patch"
            patch.write_text("historical patch\n", encoding="utf-8")
            prepare_current_build_system(root, "3.14")
            env = dict(os.environ, TERMUX_SCRIPTDIR=str(root))
            result = subprocess.run(["bash", "-e", str(helper)], env=env, text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout, "historical patch\n")
            patch.unlink()
            result = subprocess.run(["bash", "-e", str(helper)], env=env, text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout, "")

    def test_unknown_or_ambiguous_layout_is_rejected_without_writing(self):
        for mode in ("unknown", "duplicate"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                helper = self.make_tree(root)
                text = helper.read_text()
                helper.write_text(text.replace("fix-ctypes", "new-patch") if mode == "unknown" else text + text)
                before = helper.read_bytes()
                with self.assertRaisesRegex(RuntimeError, "unknown layout"):
                    prepare_current_build_system(root, "3.14")
                self.assertEqual(before, helper.read_bytes())


if __name__ == "__main__":
    unittest.main()
