"""Exercise the shipped Cap'n Proto patch against source and line-number drift."""
import ast
from pathlib import Path
import subprocess
import tempfile
import unittest


PATCH = Path(__file__).resolve().parents[1] / "patches" / "capnp-android.patch"
BUILD = '''cc_library(
    name = "kj",
    srcs = ["array.c++", "filesystem.c++"],
    linkopts = select({
        "@platforms//os:windows": [],
        ":use_libdl": [
            "-lpthread",
            "-ldl",
        ],
        "//conditions:default": ["-lpthread"],
    }),
)
'''
FILESYSTEM = '''#if __linux__
#include <sys/mman.h>    // for memfd_create()
#endif  // __linux__

#if __linux__

Own<File> newMemfdFile(uint flags) {
  return newDiskFile(KJ_SYSCALL_FD(memfd_create("kj-memfd", flags | MFD_CLOEXEC)));
}
#endif
'''
HEADER = '''#if __linux__

Own<File> newMemfdFile(uint flags = 0);
#endif
'''


class CapnpAndroidPatchTests(unittest.TestCase):
    def apply_patch(self, root, build, padding):
        kj = root / "src" / "kj"
        kj.mkdir(parents=True)
        for name, text in {
            "BUILD.bazel": build,
            "filesystem.c++": FILESYSTEM,
            "filesystem.h": HEADER,
        }.items():
            (kj / name).write_text("\n" * padding + text, encoding="utf-8")
        return subprocess.run(
            ["patch", "--batch", "--fuzz=0", "-p1", "-i", str(PATCH)],
            cwd=root, text=True, capture_output=True,
        )

    def test_android_is_a_select_branch_after_line_number_drift(self):
        # The failed CI revision moved the old line-84 insertion into the
        # use_libdl string list. Vary both line numbers and that list's length.
        for padding in (0, 75, 120):
            for build in (BUILD, BUILD.replace('            "-ldl",',
                                              '            "-ldl",\n            "-lm",')):
                with self.subTest(padding=padding, build=build):
                    with tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        result = self.apply_patch(root, build, padding)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        kj = root / "src" / "kj"
                        patched = (kj / "BUILD.bazel").read_text()
                        call = ast.parse(patched).body[0].value
                        attrs = {keyword.arg: keyword.value for keyword in call.keywords}
                        options = ast.literal_eval(attrs["linkopts"].args[0])
                        self.assertEqual(options.pop("@platforms//os:android"), [])
                        original = ast.parse(build).body[0].value
                        original_attrs = {keyword.arg: keyword.value for keyword in original.keywords}
                        self.assertEqual(options, ast.literal_eval(original_attrs["linkopts"].args[0]))
                        self.assertEqual(ast.literal_eval(attrs["srcs"]),
                                         ast.literal_eval(original_attrs["srcs"]))
                        for name, original in (("filesystem.c++", FILESYSTEM),
                                               ("filesystem.h", HEADER)):
                            self.assertEqual(
                                (kj / name).read_text(),
                                "\n" * padding + original.replace(
                                    "#if __linux__", "#if __linux__ && !defined(__ANDROID__)"),
                            )

    def test_unknown_link_options_fail_instead_of_inserting_by_line_number(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.apply_patch(Path(directory), BUILD.replace(":use_libdl", ":changed"), 75)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("FAILED", result.stdout)


if __name__ == "__main__":
    unittest.main()
