"""Keep Pyodide's build-time Node tool out of the Android configuration."""
import ast
from pathlib import Path
import tempfile
import unittest

from scripts.patch_workerd_android import use_pyodide_patcher_runfiles


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


class PyodideToolTests(unittest.TestCase):
    def test_only_disables_target_configured_execroot_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "helpers.bzl"
            text = "# Upstream line-number drift\n" * 30 + PYODIDE_ACTION
            path.write_text(text, encoding="utf-8")
            use_pyodide_patcher_runfiles(path)
            patched = path.read_text(encoding="utf-8")
            before = ast.parse(text).body[0].body[0].value
            after = ast.parse(patched).body[0].body[0].value
            extra = after.keywords.pop()
            self.assertEqual(extra.arg, "use_execroot_entry_point")
            self.assertIs(ast.literal_eval(extra.value), False)
            self.assertEqual(ast.dump(before), ast.dump(after))
            use_pyodide_patcher_runfiles(path)
            self.assertEqual(path.read_text(encoding="utf-8"), patched)

    def test_unknown_or_ambiguous_upstream_drift_fails_without_writing(self):
        variants = [
            PYODIDE_ACTION.replace("patch_pyodide_asm", "different_tool"),
            PYODIDE_ACTION + PYODIDE_ACTION,
            PYODIDE_ACTION.replace("    )\n", "        use_execroot_entry_point = True,\n    )\n"),
        ]
        for text in variants:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "helpers.bzl"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    use_pyodide_patcher_runfiles(path)
                self.assertEqual(path.read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
