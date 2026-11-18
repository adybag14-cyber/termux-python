"""Keep Pyodide's build-time Node tool out of the Android configuration."""
import ast
from pathlib import Path
import tempfile
import unittest

from scripts.patch_workerd_android import use_pyodide_patcher_runfiles


LEGACY_RULES = Path("src/pyodide/helpers.bzl")
BUNDLE_RULES = Path("src/pyodide/bundle/python_bundles.bzl")


# Shape used by workerd v1.20261001.1 (src/pyodide/helpers.bzl).
PYODIDE_ACTION = '''def _python_bundle(version):
    js_run_binary(
        name = "pyodide.asm.mjs@rule@" + version,
        srcs = [upstream_asm_mjs],
        outs = [patched_asm_mjs],
        args = [
            "--version", version,
            "--input", _bin_relative_path(upstream_asm_mjs),
            "--output", _bin_relative_path(patched_asm_mjs),
        ],
        mnemonic = "PatchPyodideAsm",
        tool = Label("//src/pyodide/tools:patch_pyodide_asm"),
    )
'''

# workerd v1.20261116.1 moved the rule into the bundle package.
BUNDLE_ACTION = PYODIDE_ACTION.replace("//src/pyodide/tools:patch_pyodide_asm", ":patch_pyodide_asm")


class PyodideToolTests(unittest.TestCase):
    def test_only_disables_target_configured_execroot_data(self):
        for relative_path, action in ((LEGACY_RULES, PYODIDE_ACTION), (BUNDLE_RULES, BUNDLE_ACTION)):
            with self.subTest(path=relative_path), tempfile.TemporaryDirectory() as directory:
                tree = Path(directory)
                path = tree / relative_path
                path.parent.mkdir(parents=True)
                text = "# Upstream line-number drift\n" * 30 + action
                path.write_text(text, encoding="utf-8")
                if relative_path == BUNDLE_RULES:
                    helpers_text = "def pyodide_static():\n    pass\n"
                    (tree / LEGACY_RULES).write_text(helpers_text, encoding="utf-8")

                use_pyodide_patcher_runfiles(tree)
                patched = path.read_text(encoding="utf-8")
                before = ast.parse(text).body[0].body[0].value
                after = ast.parse(patched).body[0].body[0].value
                extra = after.keywords.pop()
                self.assertEqual(extra.arg, "use_execroot_entry_point")
                self.assertIs(ast.literal_eval(extra.value), False)
                self.assertEqual(ast.dump(before), ast.dump(after))
                if relative_path == BUNDLE_RULES:
                    self.assertEqual((tree / LEGACY_RULES).read_text(encoding="utf-8"), helpers_text)
                use_pyodide_patcher_runfiles(tree)
                self.assertEqual(path.read_text(encoding="utf-8"), patched)

    def test_unknown_or_ambiguous_upstream_drift_fails_without_writing(self):
        variants = [
            PYODIDE_ACTION.replace("patch_pyodide_asm", "different_tool"),
            PYODIDE_ACTION + PYODIDE_ACTION,
            PYODIDE_ACTION.replace("    )\n", "        use_execroot_entry_point = True,\n    )\n"),
        ]
        for text in variants:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                tree = Path(directory)
                path = tree / LEGACY_RULES
                path.parent.mkdir(parents=True)
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    use_pyodide_patcher_runfiles(tree)
                self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_rule_in_both_locations_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            helpers = tree / LEGACY_RULES
            bundles = tree / BUNDLE_RULES
            bundles.parent.mkdir(parents=True)
            helpers.write_text(PYODIDE_ACTION, encoding="utf-8")
            bundles.write_text(BUNDLE_ACTION, encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "Ambiguous Pyodide patch tool"):
                use_pyodide_patcher_runfiles(tree)
            self.assertEqual(helpers.read_text(encoding="utf-8"), PYODIDE_ACTION)
            self.assertEqual(bundles.read_text(encoding="utf-8"), BUNDLE_ACTION)


if __name__ == "__main__":
    unittest.main()
