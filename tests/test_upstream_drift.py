import ast
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from scripts.patch_workerd_android import restore_target_runner
from scripts.prepare_python_recipe import refresh_mimetypes_patch


MIME_PATHS = '''knownfiles = [
    "/etc/mime.types",
    "/usr/local/etc/mime.types",                # Apache 1.3
    ]
'''
MIME_PATCH = '''--- a/Lib/mimetypes.py
+++ b/Lib/mimetypes.py
@@ -1,4 +1,5 @@
 knownfiles = [
     "/etc/mime.types",
     "/usr/local/etc/mime.types",                # Apache 1.3
+    "@TERMUX_PREFIX@/etc/mime.types",           # Termux
     ]
'''
OTHER_PATCH = '''--- a/Lib/posixpath.py
+++ b/Lib/posixpath.py
@@ -1 +1 @@
-defpath = '/bin:/usr/bin'
+defpath = '@TERMUX_PREFIX@/bin'
'''


class MimePatchTests(unittest.TestCase):
    def make_source(self, text):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:xz") as archive:
            data = text.encode()
            member = tarfile.TarInfo("Python-3.14.10/Lib/mimetypes.py")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        return output.getvalue()

    def test_patch_applies_to_legacy_and_guarded_sources_without_reverting_guard(self):
        for guarded in (False, True):
            with self.subTest(guarded=guarded), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                recipe = root / "packages/python"
                recipe.mkdir(parents=True)
                patch = recipe / "0001-fix-hardcoded-paths.patch"
                patch.write_text(MIME_PATCH + OTHER_PATCH)
                original = MIME_PATHS
                if guarded:
                    original = ('if sys.platform == "win32":\n    knownfiles = []\nelse:\n'
                                + "".join("    " + line for line in MIME_PATHS.splitlines(True)))
                source = self.make_source(original)
                refresh_mimetypes_patch(root, source, "3.14.10")
                first = patch.read_bytes()
                self.assertTrue(patch.read_text().endswith(OTHER_PATCH))
                refresh_mimetypes_patch(root, source, "3.14.10")
                self.assertEqual(patch.read_bytes(), first)
                (root / "Lib").mkdir()
                target = root / "Lib/mimetypes.py"
                target.write_text(original)
                (root / "Lib/posixpath.py").write_text("defpath = '/bin:/usr/bin'\n")
                subprocess.run(["git", "apply", "--verbose", str(patch)], cwd=root, check=True,
                               capture_output=True, text=True)
                parsed = ast.parse(target.read_text())
                if guarded:
                    self.assertIsInstance(parsed.body[0], ast.If)
                    self.assertEqual(ast.literal_eval(parsed.body[0].body[0].value), [])
                    paths = ast.literal_eval(parsed.body[0].orelse[0].value)
                else:
                    paths = ast.literal_eval(parsed.body[0].value)
                self.assertEqual(paths, ["/etc/mime.types", "/usr/local/etc/mime.types",
                                         "@TERMUX_PREFIX@/etc/mime.types"])

    def test_unknown_source_or_downstream_changes_fail_without_writing(self):
        for source, patch_text in (("knownfiles = make_paths()\n", MIME_PATCH),
                                   (MIME_PATHS, MIME_PATCH.replace("# Termux", "# changed"))):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                recipe = root / "packages/python"
                recipe.mkdir(parents=True)
                patch = recipe / "0001-fix-hardcoded-paths.patch"
                patch.write_text(patch_text)
                before = patch.read_bytes()
                with self.assertRaises(RuntimeError):
                    refresh_mimetypes_patch(root, self.make_source(source), "3.14.10")
                self.assertEqual(before, patch.read_bytes())


class TargetRunnerTests(unittest.TestCase):
    def make_tree(self, root):
        (root / "build/config").mkdir(parents=True)
        config = root / "build/config/BUILD.bazel"
        bundle = root / "build/wd_js_bundle.bzl"
        config.write_text('load("@bazel_skylib//rules:common_settings.bzl", "string_flag")\n')
        bundle.write_text(
            'load("@bazel_skylib//rules:common_settings.bzl", "BuildSettingInfo")\n'
            '        command = ctx.executable._tool.path + " $@",\n'
            '        "_v8_flags": attr.label(default = "//build/config:compile_cache_v8_flags"),\n'
        )
        return config, bundle

    def test_restores_the_flag_and_consumer_idempotently(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, bundle = self.make_tree(root)
            restore_target_runner(root)
            first = (config.read_bytes(), bundle.read_bytes())
            self.assertEqual(config.read_text().count('name = "target_run_under"'), 1)
            self.assertIn('default = "//build/config:target_run_under"', bundle.read_text())
            self.assertIn('ctx.attr._target_run_under[BuildSettingInfo].value', bundle.read_text())
            self.assertIn('"$@"', bundle.read_text())
            restore_target_runner(root)
            self.assertEqual(first, (config.read_bytes(), bundle.read_bytes()))

    def test_unknown_command_fails_before_either_file_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config, bundle = self.make_tree(root)
            bundle.write_text(bundle.read_text().replace('" $@"', '" changed"'))
            before = (config.read_bytes(), bundle.read_bytes())
            with self.assertRaisesRegex(RuntimeError, "Unknown workerd"):
                restore_target_runner(root)
            self.assertEqual(before, (config.read_bytes(), bundle.read_bytes()))


if __name__ == "__main__":
    unittest.main()
