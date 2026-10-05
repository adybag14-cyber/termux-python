"""Exercise compile-cache argument forwarding without Docker, QEMU, or Android."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "run_workerd_android_target_tool.sh"
FAKE_DOCKER = r'''
import json
import os
from pathlib import Path
import subprocess
import sys

args = sys.argv[1:]
assert args[:4] == ["run", "--rm", "--platform", "linux/arm64"], args
assert args[4] == "-v" and args[6] == "-w", args
assert args[5] == os.getcwd() + ":" + os.getcwd(), args
assert args[7] == os.getcwd(), args
assert args[8] == "termux/termux-docker:aarch64", args
Path(os.environ["DOCKER_LOG"]).write_text(json.dumps(args))
if os.environ.get("DOCKER_EXIT"):
    sys.exit(int(os.environ["DOCKER_EXIT"]))
sys.exit(subprocess.run(args[9:]).returncode)
'''
FAKE_TOOL = r'''
import argparse
import json
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("file_list")
parser.add_argument("--kind", choices=["module", "function"], default="module")
parser.add_argument("--v8-flag", action="append", default=[])
parser.add_argument("--eager", action="store_true")
args = parser.parse_args()
manifest = Path(args.file_list)
rows = [line.split(" ") for line in manifest.read_text().splitlines() if line]
inputs = []
for index, (source, target) in enumerate(rows):
    source, target = Path(source), Path(target)
    assert source.parent == manifest.parent == target.parent
    assert source.is_file() and not source.is_symlink()
    assert target.is_file() and not target.is_symlink()
    inputs.append(source.read_text())
    if str(index) != os.environ.get("OMIT_OUTPUT"):
        target.write_text("cache:" + source.read_text())
Path(os.environ["TOOL_LOG"]).write_text(json.dumps({
    "argv": sys.argv[1:], "manifest": args.file_list,
    "kind": args.kind, "v8_flags": args.v8_flag, "eager": args.eager,
    "rows": rows, "inputs": inputs,
}))
sys.exit(int(os.environ.get("TOOL_EXIT", "0")))
'''


class WorkerdAndroidRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # Docker argv must preserve spaces, but the Rust manifest format cannot
        # contain them. Staged file-list entries should stay relative to cwd.
        self.cwd = self.root / "sandbox with spaces"
        self.cwd.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.write_executable(self.bin / "docker", FAKE_DOCKER)
        self.tool = self.root / "real-tool"
        self.write_executable(self.tool, FAKE_TOOL)
        (self.cwd / "tool").symlink_to(self.tool)
        (self.root / "source.js").write_text("export const answer = 42;\n")
        (self.cwd / "source.js").symlink_to(self.root / "source.js")
        (self.cwd / "other.js").write_text("export default 'other';\n")
        # The declared Bazel output can point outside the mounted sandbox.
        self.external_output = self.root / "cache"
        self.external_output.write_text("previous cache")
        (self.cwd / "cache").symlink_to(self.external_output)
        self.manifest = self.cwd / "manifest"
        self.manifest.write_text("source.js cache\nother.js nested/other-cache\n")
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "DOCKER_LOG": str(self.root / "docker.json"),
            "TOOL_LOG": str(self.root / "tool.json"),
        }
        for name in ("DOCKER_EXIT", "TOOL_EXIT", "OMIT_OUTPUT"):
            self.env.pop(name, None)

    def write_executable(self, path, source):
        path.write_text("#!" + sys.executable + "\n" + textwrap.dedent(source))
        path.chmod(0o755)

    def run_runner(self, *args, env=None, tool="./tool"):
        result = subprocess.run(
            ["bash", str(RUNNER), tool, *args], cwd=self.cwd,
            env={**self.env, **(env or {})}, capture_output=True, text=True,
        )
        self.assertEqual(list(self.cwd.glob(".android-runner*")), [],
                         "staging files must be removed on success and failure")
        return result

    def assert_success(self, args, manifest_index):
        result = self.run_runner(*args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = json.loads((self.root / "tool.json").read_text())
        expected = list(args)
        expected[manifest_index] = log["manifest"]
        self.assertEqual(log["argv"], expected, "only the manifest argv may change")
        self.assertNotEqual(log["manifest"], args[manifest_index])
        self.assertEqual(self.external_output.read_text(),
                         "cache:" + (self.root / "source.js").read_text())
        self.assertTrue((self.cwd / "cache").is_symlink())
        self.assertEqual((self.cwd / "nested/other-cache").read_text(),
                         "cache:" + (self.cwd / "other.js").read_text())
        self.assertEqual(log["inputs"], [(self.root / "source.js").read_text(),
                                         (self.cwd / "other.js").read_text()])
        self.assertEqual(len(log["rows"]), 2)
        return log

    def assert_outputs_unchanged(self):
        self.assertEqual(self.external_output.read_text(), "previous cache")
        self.assertFalse((self.cwd / "nested/other-cache").exists())

    def test_modern_flags_precede_manifest_and_are_quote_safe(self):
        flags = ["--v8-flag=--no-lazy",
                 "--v8-flag=--label='two words' \"$HOME\" `touch injected` "
                 "$(touch injected) * [abc]; echo nope"]
        log = self.assert_success(["--kind", "function", *flags, "manifest"], 4)
        self.assertEqual(log["kind"], "function")
        self.assertEqual(log["v8_flags"], [flag.split("=", 1)[1] for flag in flags])
        self.assertFalse((self.cwd / "injected").exists())

    def test_legacy_manifest_first(self):
        log = self.assert_success(["manifest"], 0)
        self.assertEqual(log["kind"], "module")
        self.assertEqual(log["v8_flags"], [])

    def test_options_after_manifest_and_equals_kind_are_preserved(self):
        log = self.assert_success(
            ["manifest", "--kind=module", "--v8-flag", "trace-gc", "--eager"], 0)
        self.assertEqual(log["kind"], "module")
        self.assertEqual(log["v8_flags"], ["trace-gc"])
        self.assertTrue(log["eager"])

    def test_end_of_options_supports_dash_prefixed_manifest(self):
        self.manifest.rename(self.cwd / "-manifest")
        self.assert_success(["--kind", "module", "--", "-manifest"], 3)

    def test_last_manifest_line_does_not_require_newline(self):
        self.manifest.write_text("\nsource.js cache\nother.js nested/other-cache")
        self.assert_success(["--kind", "module", "manifest"], 2)

    def test_malformed_arguments_fail_before_docker(self):
        cases = [
            [], ["--kind"], ["--kind", "function"],
            ["--kind", "unknown", "manifest"], ["--kind=", "manifest"],
            ["--kind=module", "--kind=function", "manifest"],
            ["--v8-flag"], ["--v8-flag", "--no-lazy", "manifest"],
            ["--v8-flag=", "manifest"], ["--v8-flag", "", "manifest"],
            ["--eager", "--eager", "manifest"], ["--eager=false", "manifest"],
            ["--unknown", "manifest"], ["manifest", "other.js"],
            ["manifest", "--", "other.js"], ["--"], ["missing-manifest"], [""],
        ]
        for args in cases:
            with self.subTest(args=args):
                result = self.run_runner(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "docker.json").exists())
                self.assert_outputs_unchanged()

    def test_malformed_manifests_fail_closed_and_clean_partial_staging(self):
        for line in ("missing-output", "source.js cache unexpected", "source.js  cache",
                     "source.js\tcache", " ", " source.js cache"):
            with self.subTest(line=line):
                self.manifest.write_text("other.js other-cache\n" + line + "\n")
                result = self.run_runner("manifest")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Malformed compile-cache manifest line 2", result.stderr)
                self.assertFalse((self.root / "docker.json").exists())
                self.assert_outputs_unchanged()
                self.assertFalse((self.cwd / "other-cache").exists())

    def test_empty_manifest_fails_without_running_docker(self):
        self.manifest.write_text("\n\n")
        result = self.run_runner("manifest")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contained no outputs", result.stderr)
        self.assertFalse((self.root / "docker.json").exists())
        self.assert_outputs_unchanged()

    def test_missing_input_cleans_already_staged_files(self):
        self.manifest.write_text("source.js cache\nmissing.js nested/other-cache\n")
        result = self.run_runner("manifest")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "docker.json").exists())
        self.assert_outputs_unchanged()

    def test_docker_failure_returns_status_and_never_copies_outputs(self):
        result = self.run_runner("manifest", env={"DOCKER_EXIT": "73"})
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertTrue((self.root / "docker.json").exists())
        self.assertFalse((self.root / "tool.json").exists())
        self.assert_outputs_unchanged()

    def test_tool_failure_returns_status_and_never_copies_outputs(self):
        result = self.run_runner("--kind", "function", "manifest", env={"TOOL_EXIT": "9"})
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertTrue((self.root / "tool.json").exists())
        self.assert_outputs_unchanged()

    def test_missing_output_fails_before_copying_any_outputs(self):
        result = self.run_runner("manifest", env={"OMIT_OUTPUT": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not produce nested/other-cache", result.stderr)
        self.assert_outputs_unchanged()

    def test_copyback_failure_returns_nonzero_and_cleans_staging(self):
        (self.cwd / "nested").write_text("not a directory")
        result = self.run_runner("manifest")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / "tool.json").exists())
        self.assertEqual((self.cwd / "nested").read_text(), "not a directory")

    def test_nonexecutable_tool_is_rejected(self):
        result = self.run_runner("manifest", tool="source.js")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not executable", result.stderr)
        self.assertFalse((self.root / "docker.json").exists())
        self.assert_outputs_unchanged()


if __name__ == "__main__":
    unittest.main()
