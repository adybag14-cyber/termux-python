#!/usr/bin/env python3
"""Patch a workerd source checkout for a native Android/aarch64 Bazel target."""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected patch anchor not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tree", type=Path)
    args = parser.parse_args()
    tree = args.tree.resolve()

    module = tree / "MODULE.bazel"
    module_text = module.read_text(encoding="utf-8")
    if "rules_android_ndk" not in module_text:
        anchor = 'module(name = "workerd")\n'
        block = '''module(name = "workerd")

# Community Android/aarch64 target used by termux-python.  The NDK itself is
# supplied by CI through ANDROID_NDK_HOME; Bazel host tools remain native Linux.
bazel_dep(name = "rules_android_ndk", version = "0.1.5")
android_ndk_repository_extension = use_extension(
    "@rules_android_ndk//:extension.bzl",
    "android_ndk_repository_extension",
)
android_ndk_repository_extension.configure(api_level = 24)
use_repo(android_ndk_repository_extension, "androidndk")
register_toolchains("@androidndk//:all")
'''
        replace_once(module, anchor, block)

    build = tree / "BUILD.bazel"
    build_text = build.read_text(encoding="utf-8")
    if 'name = "android_arm64"' not in build_text:
        marker = '# Detect whether we use Linux/macOS/either, used to configure whether tcmalloc/perfetto should be\n# used.\n'
        platform = '''# Native Android/Termux aarch64 target.  This deliberately uses the Android OS
# constraint instead of pretending Bionic is glibc Linux.
platform(
    name = "android_arm64",
    constraint_values = [
        "@platforms//os:android",
        "@platforms//cpu:aarch64",
    ],
)

'''
        replace_once(build, marker, platform + marker)

    build_text = build.read_text(encoding="utf-8")
    if 'name = "is_android"' not in build_text:
        anchor = '''config_setting(
    name = "is_macos",
    constraint_values = ["@platforms//os:macos"],
    visibility = ["//visibility:public"],
)
'''
        replacement = anchor + '''
config_setting(
    name = "is_android",
    constraint_values = ["@platforms//os:android"],
    visibility = ["//visibility:public"],
)
'''
        replace_once(build, anchor, replacement)

    build_text = build.read_text(encoding="utf-8")
    if '        ":is_android",\n' not in build_text:
        replace_once(
            build,
            '''    match_any = [
        ":is_linux",
        ":is_macos",
    ],
''',
            '''    match_any = [
        ":is_linux",
        ":is_macos",
        ":is_android",
    ],
''',
        )

    zlib = tree / "build" / "BUILD.zlib"
    zlib_text = zlib.read_text(encoding="utf-8")
    if 'name = "arm64_android"' not in zlib_text:
        anchor = '''selects.config_setting_group(
    name = "arm64_linux",
    match_all = [
        "@platforms//cpu:aarch64",
        "@platforms//os:linux",
    ],
)
'''
        replacement = anchor + '''
selects.config_setting_group(
    name = "arm64_android",
    match_all = [
        "@platforms//cpu:aarch64",
        "@platforms//os:android",
    ],
)
'''
        replace_once(zlib, anchor, replacement)

    zlib_text = zlib.read_text(encoding="utf-8")
    os_select = '''        "@platforms//os:linux": ["ARMV8_OS_LINUX"],
        "@platforms//os:macos": ["ARMV8_OS_MACOS"],
        "@platforms//os:windows": ["ARMV8_OS_WINDOWS"],
'''
    if '        "@platforms//os:android": ["ARMV8_OS_LINUX"],\n' not in zlib_text:
        replace_once(
            zlib,
            os_select,
            '''        "@platforms//os:linux": ["ARMV8_OS_LINUX"],
        "@platforms//os:android": ["ARMV8_OS_LINUX"],
        "@platforms//os:macos": ["ARMV8_OS_MACOS"],
        "@platforms//os:windows": ["ARMV8_OS_WINDOWS"],
''',
        )

    zlib_text = zlib.read_text(encoding="utf-8")
    if '        ":arm64_android": ["ARMV8_OS_LINUX"],\n' not in zlib_text:
        replace_once(
            zlib,
            '        ":arm64_linux": ["ARMV8_OS_LINUX"],\n',
            '        ":arm64_linux": ["ARMV8_OS_LINUX"],\n        ":arm64_android": ["ARMV8_OS_LINUX"],\n',
        )

    # Android defines __linux__, but Bionic has no separate libpthread and
    # does not expose KJ's Linux memfd implementation through the same API.
    capnp_patch_dir = tree / "patches" / "capnp"
    capnp_patch_dir.mkdir(parents=True, exist_ok=True)
    capnp_patch = capnp_patch_dir / "0001-android-bionic-port.patch"
    capnp_patch.write_text(
        "\n".join([
            "diff --git a/src/kj/filesystem.c++ b/src/kj/filesystem.c++",
            "--- a/src/kj/filesystem.c++",
            "+++ b/src/kj/filesystem.c++",
            "@@ -31 +31 @@",
            "-#if __linux__",
            "+#if __linux__ && !defined(__ANDROID__)",
            "@@ -1839 +1839 @@",
            "-#if __linux__",
            "+#if __linux__ && !defined(__ANDROID__)",
            "diff --git a/src/kj/filesystem.h b/src/kj/filesystem.h",
            "--- a/src/kj/filesystem.h",
            "+++ b/src/kj/filesystem.h",
            "@@ -939 +939 @@",
            "-#if __linux__",
            "+#if __linux__ && !defined(__ANDROID__)",
            "diff --git a/src/kj/BUILD.bazel b/src/kj/BUILD.bazel",
            "--- a/src/kj/BUILD.bazel",
            "+++ b/src/kj/BUILD.bazel",
            "@@ -84,0 +85 @@",
            "+        \"@platforms//os:android\": [],",
        ]) + "\n",
        encoding="utf-8",
    )

    deps_module = tree / "build" / "deps" / "gen" / "deps.MODULE.bazel"
    deps_text = deps_module.read_text(encoding="utf-8")
    if "patches/capnp/0001-android-bionic-port.patch" not in deps_text:
        replace_once(
            deps_module,
            'http.archive(\n    name = "capnp-cpp",\n',
            'http.archive(\n    name = "capnp-cpp",\n'
            '    patch_args = ["-p1"],\n'
            '    patches = ["//:patches/capnp/0001-android-bionic-port.patch"],\n',
        )

    # V8's Android stack trace source uses an angle-bracket include for a V8
    # project header. In the Bazel Android target that header is available as a
    # project-relative include, not as a system include.
    v8_patch_name = "0040-Fix-Android-stack-trace-project-include.patch"
    v8_patch = tree / "patches" / "v8" / v8_patch_name
    v8_patch.write_text(
        "\n".join([
            "diff --git a/src/base/debug/stack_trace_android.cc b/src/base/debug/stack_trace_android.cc",
            "--- a/src/base/debug/stack_trace_android.cc",
            "+++ b/src/base/debug/stack_trace_android.cc",
            "@@ -15 +15 @@",
            "-#include <src/base/platform/platform.h>",
            "+#include \"src/base/platform/platform.h\"",
        ]) + "\n",
        encoding="utf-8",
    )

    v8_module = tree / "build" / "deps" / "v8.MODULE.bazel"
    v8_text = v8_module.read_text(encoding="utf-8")
    if v8_patch_name not in v8_text:
        replace_once(
            v8_module,
            '    "0039-Properly-depend-on-llvm-libc.patch",\n]',
            '    "0039-Properly-depend-on-llvm-libc.patch",\n'
            f'    "{v8_patch_name}",\n]',
        )

    v8_atomic_patch_name = "0041-Provide-atomic-ref-on-Android.patch"
    v8_atomic_patch = tree / "patches" / "v8" / v8_atomic_patch_name
    v8_atomic_patch.write_text(
        'diff --git a/include/v8config.h b/include/v8config.h\n--- a/include/v8config.h\n+++ b/include/v8config.h\n@@ -21,7 +21,104 @@\n #include "v8-gn.h"  // NOLINT(build/include_directory)\n #endif\n \n+#include <atomic>\n #include <memory>\n+\n+// Android NDK libc++ does not currently provide C++20 std::atomic_ref. V8\n+// relies on atomic_ref for atomically accessing existing storage, so provide\n+// the subset of the interface V8 uses via Clang\'s __atomic builtins.\n+#if defined(__ANDROID__) && !defined(__cpp_lib_atomic_ref)\n+namespace std {\n+namespace __v8_android_atomic_ref_compat {\n+constexpr int ToBuiltinOrder(memory_order order) noexcept {\n+  switch (order) {\n+    case memory_order_relaxed: return __ATOMIC_RELAXED;\n+    case memory_order_consume: return __ATOMIC_CONSUME;\n+    case memory_order_acquire: return __ATOMIC_ACQUIRE;\n+    case memory_order_release: return __ATOMIC_RELEASE;\n+    case memory_order_acq_rel: return __ATOMIC_ACQ_REL;\n+    case memory_order_seq_cst: return __ATOMIC_SEQ_CST;\n+  }\n+  __builtin_unreachable();\n+}\n+constexpr memory_order FailureOrder(memory_order order) noexcept {\n+  if (order == memory_order_release) return memory_order_relaxed;\n+  if (order == memory_order_acq_rel) return memory_order_acquire;\n+  return order;\n+}\n+}  // namespace __v8_android_atomic_ref_compat\n+\n+template <typename T>\n+class atomic_ref {\n+ public:\n+  using value_type = T;\n+  static constexpr size_t required_alignment = alignof(T);\n+  static constexpr bool is_always_lock_free =\n+      __atomic_always_lock_free(sizeof(T), nullptr);\n+\n+  explicit atomic_ref(T& object) noexcept : ptr_(&object) {}\n+  atomic_ref(const atomic_ref&) noexcept = default;\n+\n+  T load(memory_order order = memory_order_seq_cst) const noexcept {\n+    T value;\n+    __atomic_load(ptr_, &value,\n+                  __v8_android_atomic_ref_compat::ToBuiltinOrder(order));\n+    return value;\n+  }\n+\n+  void store(T desired,\n+             memory_order order = memory_order_seq_cst) const noexcept {\n+    __atomic_store(ptr_, &desired,\n+                   __v8_android_atomic_ref_compat::ToBuiltinOrder(order));\n+  }\n+\n+  T exchange(T desired,\n+             memory_order order = memory_order_seq_cst) const noexcept {\n+    T old;\n+    __atomic_exchange(ptr_, &desired, &old,\n+                      __v8_android_atomic_ref_compat::ToBuiltinOrder(order));\n+    return old;\n+  }\n+\n+  bool compare_exchange_strong(T& expected, T desired, memory_order success,\n+                               memory_order failure) const noexcept {\n+    return __atomic_compare_exchange(\n+        ptr_, &expected, &desired, false,\n+        __v8_android_atomic_ref_compat::ToBuiltinOrder(success),\n+        __v8_android_atomic_ref_compat::ToBuiltinOrder(failure));\n+  }\n+\n+  bool compare_exchange_strong(\n+      T& expected, T desired,\n+      memory_order order = memory_order_seq_cst) const noexcept {\n+    return compare_exchange_strong(\n+        expected, desired, order,\n+        __v8_android_atomic_ref_compat::FailureOrder(order));\n+  }\n+\n+  template <typename U = T>\n+  enable_if_t<is_integral_v<U>, U> fetch_or(\n+      U arg, memory_order order = memory_order_seq_cst) const noexcept {\n+    return __atomic_fetch_or(\n+        ptr_, arg, __v8_android_atomic_ref_compat::ToBuiltinOrder(order));\n+  }\n+\n+  template <typename U = T>\n+  enable_if_t<is_integral_v<U>, U> fetch_add(\n+      U arg, memory_order order = memory_order_seq_cst) const noexcept {\n+    return __atomic_fetch_add(\n+        ptr_, arg, __v8_android_atomic_ref_compat::ToBuiltinOrder(order));\n+  }\n+\n+  bool is_lock_free() const noexcept {\n+    return __atomic_is_lock_free(sizeof(T), ptr_);\n+  }\n+\n+ private:\n+  T* ptr_;\n+};\n+}  // namespace std\n+#endif  // defined(__ANDROID__) && !defined(__cpp_lib_atomic_ref)\n // clang-format off\n \n // Platform headers for feature detection below.\n',
        encoding="utf-8",
    )

    v8_text = v8_module.read_text(encoding="utf-8")
    if v8_atomic_patch_name not in v8_text:
        replace_once(
            v8_module,
            f'    "{v8_patch_name}",\n]',
            f'    "{v8_patch_name}",\n    "{v8_atomic_patch_name}",\n]',
        )

    # V8's Bazel helpers default generator tools to the target configuration.
    # Its own comment notes cross-compilation must use exec so generators,
    # Torque, and mksnapshot execute on the Linux build host rather than Android.
    v8_exec_patch_name = "0042-Build-V8-generators-in-exec-configuration.patch"
    v8_exec_patch = tree / "patches" / "v8" / v8_exec_patch_name
    v8_exec_patch.write_text(
        "\n".join([
            "diff --git a/bazel/defs.bzl b/bazel/defs.bzl",
            "--- a/bazel/defs.bzl",
            "+++ b/bazel/defs.bzl",
            "@@ -353 +353 @@ def get_cfg():",
            "-    return \"target\"",
            "+    return \"exec\"",
        ]) + "\n",
        encoding="utf-8",
    )

    v8_text = v8_module.read_text(encoding="utf-8")
    if v8_exec_patch_name not in v8_text:
        replace_once(
            v8_module,
            f'    "{v8_atomic_patch_name}",\n]',
            f'    "{v8_atomic_patch_name}",\n    "{v8_exec_patch_name}",\n]',
        )

    # workerd builds V8 under C++23, but V8's Bazel defaults append C++20
    # after the repository-wide flags. Once generator dependencies move to the
    # exec configuration that trailing flag breaks V8 15's immediate-function
    # regexp code on the Linux host. Keep Clang V8 builds on C++23 as intended.
    v8_cxx23_patch_name = "0043-Use-CXX23-for-Clang-Bazel-builds.patch"
    v8_cxx23_patch = tree / "patches" / "v8" / v8_cxx23_patch_name
    v8_cxx23_patch.write_text(
        "\n".join([
            "diff --git a/bazel/defs.bzl b/bazel/defs.bzl",
            "--- a/bazel/defs.bzl",
            "+++ b/bazel/defs.bzl",
            "@@ -152 +152 @@",
            "-                \"-std=c++20\",",
            "+                \"-std=c++23\",",
        ]) + "\n",
        encoding="utf-8",
    )

    v8_text = v8_module.read_text(encoding="utf-8")
    if v8_cxx23_patch_name not in v8_text:
        replace_once(
            v8_module,
            f'    "{v8_exec_patch_name}",\n]',
            f'    "{v8_exec_patch_name}",\n    "{v8_cxx23_patch_name}",\n]',
        )
    # mksnapshot runs on the Linux host in a cross-build, so V8 cannot infer
    # Android from the execution platform. Passing an empty target OS selects
    # the generic embedded writer (including 64 KiB ARM64 alignment), while
    # Android requires V8's Android writer behavior and 16 KiB alignment.
    v8_android_snapshot_patch_name = "0044-Set-Android-mksnapshot-target-OS.patch"
    v8_android_snapshot_patch = tree / "patches" / "v8" / v8_android_snapshot_patch_name
    v8_android_snapshot_patch.write_text(
        "\n".join([
            "diff --git a/bazel/defs.bzl b/bazel/defs.bzl",
            "--- a/bazel/defs.bzl",
            "+++ b/bazel/defs.bzl",
            "@@ -548,5 +548 @@ def v8_mksnapshot(name, args, suffix = \"\"):",
            "-        target_os = select({",
            "-            \"@v8//bazel/config:is_macos\": \"mac\",",
            "-            \"@v8//bazel/config:is_windows\": \"win\",",
            "-            \"//conditions:default\": \"\",",
            "-        }),",
            "+        target_os = \"android\",",
            "@@ -557,5 +553 @@ def v8_mksnapshot(name, args, suffix = \"\"):",
            "-        target_os = select({",
            "-            \"@v8//bazel/config:is_macos\": \"mac\",",
            "-            \"@v8//bazel/config:is_windows\": \"win\",",
            "-            \"//conditions:default\": \"\",",
            "-        }),",
            "+        target_os = \"android\",",
        ]) + "\n",
        encoding="utf-8",
    )

    v8_text = v8_module.read_text(encoding="utf-8")
    if v8_android_snapshot_patch_name not in v8_text:
        replace_once(
            v8_module,
            f'    "{v8_cxx23_patch_name}",\n]',
            f'    "{v8_cxx23_patch_name}",\n    "{v8_android_snapshot_patch_name}",\n]',
        )

    # V8's full-width WASM shuffle reducer relies on a default template
    # argument through an alias template. Clang rejects deduction for alias
    # templates here, so spell out the already-intended 128-bit shuffle width.
    v8_shuffle_patch_name = "0045-Explicit-SIMD-shuffle-array-size.patch"
    v8_shuffle_patch = tree / "patches" / "v8" / v8_shuffle_patch_name
    v8_shuffle_patch.write_text(
        "\n".join([
            "diff --git a/src/compiler/turboshaft/wasm-shuffle-reducer.cc b/src/compiler/turboshaft/wasm-shuffle-reducer.cc",
            "--- a/src/compiler/turboshaft/wasm-shuffle-reducer.cc",
            "+++ b/src/compiler/turboshaft/wasm-shuffle-reducer.cc",
            "@@ -522 +522 @@",
            "-    SimdShuffle::ShuffleArray shuffle_bytes;",
            "+    SimdShuffle::ShuffleArray<kSimd128Size> shuffle_bytes;",
        ]) + "\n",
        encoding="utf-8",
    )

    v8_text = v8_module.read_text(encoding="utf-8")
    if v8_shuffle_patch_name not in v8_text:
        replace_once(
            v8_module,
            f'    "{v8_android_snapshot_patch_name}",\n]',
            f'    "{v8_android_snapshot_patch_name}",\n    "{v8_shuffle_patch_name}",\n]',
        )

    # V8 declares native_context in CreateObjectLiteral but never consumes it.
    # The cross-built host V8 library treats warnings as errors, so remove the
    # dead declaration rather than suppressing unused-variable diagnostics.
    v8_dead_context_patch_name = "0046-Remove-unused-object-literal-native-context.patch"
    v8_dead_context_patch = tree / "patches" / "v8" / v8_dead_context_patch_name
    v8_dead_context_patch.write_text(
        "\n".join([
            "diff --git a/src/runtime/runtime-literals.cc b/src/runtime/runtime-literals.cc",
            "--- a/src/runtime/runtime-literals.cc",
            "+++ b/src/runtime/runtime-literals.cc",
            "@@ -519 +518,0 @@ Handle<JSObject> CreateObjectLiteral(",
            "-  DirectHandle<NativeContext> native_context = isolate->native_context();",
        ]) + "\n",
        encoding="utf-8",
    )

    v8_text = v8_module.read_text(encoding="utf-8")
    if v8_dead_context_patch_name not in v8_text:
        replace_once(
            v8_module,
            f'    "{v8_shuffle_patch_name}",\n]',
            f'    "{v8_shuffle_patch_name}",\n    "{v8_dead_context_patch_name}",\n]',
        )

    # Older iterations of this port moved gen-compile-cache to exec
    # configuration. Restore upstream's target configuration: workerd exposes
    # target_run_under specifically so cross-built tools can execute without
    # pulling their Android/V8 dependencies into the Linux host toolchain.
    js_bundle = tree / "build" / "wd_js_bundle.bzl"
    js_bundle_text = js_bundle.read_text(encoding="utf-8")
    compile_cache_exec = (
        '        "_tool": attr.label(\n'
        '            executable = True,\n'
        '            allow_single_file = True,\n'
        '            cfg = "exec",\n'
        '            default = "//src/rust/gen-compile-cache",\n'
        '        ),\n'
    )
    compile_cache_target = compile_cache_exec.replace('cfg = "exec"', 'cfg = "target"')
    if compile_cache_exec in js_bundle_text:
        replace_once(js_bundle, compile_cache_exec, compile_cache_target)
    elif compile_cache_target not in js_bundle_text:
        raise RuntimeError("Could not find gen-compile-cache tool configuration")

    # Bionic's <endian.h> exposes htobe*/be*toh as macros/inlines rather than
    # linkable global functions. workerd's wrapper header deliberately declares
    # global functions, so provide Android definitions using compiler builtins.
    endianness = tree / "src" / "workerd" / "api" / "crypto" / "endianness.c++"
    endianness_text = endianness.read_text(encoding="utf-8")
    android_endianness = r'''#if defined(__ANDROID__)

#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
uint16_t htobe16(uint16_t x) { return __builtin_bswap16(x); }
uint16_t htole16(uint16_t x) { return x; }
uint16_t be16toh(uint16_t x) { return __builtin_bswap16(x); }
uint16_t le16toh(uint16_t x) { return x; }
uint32_t htobe32(uint32_t x) { return __builtin_bswap32(x); }
uint32_t htole32(uint32_t x) { return x; }
uint32_t be32toh(uint32_t x) { return __builtin_bswap32(x); }
uint32_t le32toh(uint32_t x) { return x; }
uint64_t htobe64(uint64_t x) { return __builtin_bswap64(x); }
uint64_t htole64(uint64_t x) { return x; }
uint64_t be64toh(uint64_t x) { return __builtin_bswap64(x); }
uint64_t le64toh(uint64_t x) { return x; }
#elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
uint16_t htobe16(uint16_t x) { return x; }
uint16_t htole16(uint16_t x) { return __builtin_bswap16(x); }
uint16_t be16toh(uint16_t x) { return x; }
uint16_t le16toh(uint16_t x) { return __builtin_bswap16(x); }
uint32_t htobe32(uint32_t x) { return x; }
uint32_t htole32(uint32_t x) { return __builtin_bswap32(x); }
uint32_t be32toh(uint32_t x) { return x; }
uint32_t le32toh(uint32_t x) { return __builtin_bswap32(x); }
uint64_t htobe64(uint64_t x) { return x; }
uint64_t htole64(uint64_t x) { return __builtin_bswap64(x); }
uint64_t be64toh(uint64_t x) { return x; }
uint64_t le64toh(uint64_t x) { return __builtin_bswap64(x); }
#else
#error byte order not supported
#endif

#elif defined(__linux__) || defined(__CYGWIN__)

#include <endian.h>
'''
    if "#if defined(__ANDROID__)" not in endianness_text:
        replace_once(
            endianness,
            "#if defined(__linux__) || defined(__CYGWIN__)\n\n#include <endian.h>\n",
            android_endianness,
        )

    # rules_rust normally invokes the NDK clang driver with -nodefaultlibs for
    # Rust binaries that carry C++ link_deps. That suppresses Clang's compiler-rt
    # builtins archive, but V8's AArch64 CpuFeatures::FlushICache references
    # __clear_cache from compiler-rt. Workerd already supports linking Rust
    # binaries through cc_common.link; enable that path only for Android so the
    # NDK C++ toolchain owns the final link and supplies its normal compiler
    # runtime while standalone Linux behavior remains unchanged.
    rust_config = tree / "build" / "config" / "BUILD.bazel"
    rust_config_text = rust_config.read_text(encoding="utf-8")
    rust_cc_common_old = (
        'config_setting(\n'
        '    name = "rust_cc_common_link",\n'
        '    values = {"define": "never_match=true"},  # This will never match\n'
        '    visibility = ["//visibility:public"],\n'
        ')\n'
    )
    rust_cc_common_android = (
        'config_setting(\n'
        '    name = "rust_cc_common_link",\n'
        '    constraint_values = ["@platforms//os:android"],\n'
        '    visibility = ["//visibility:public"],\n'
        ')\n'
    )
    if rust_cc_common_old in rust_config_text:
        replace_once(rust_config, rust_cc_common_old, rust_cc_common_android)
    elif rust_cc_common_android not in rust_config_text:
        raise RuntimeError("Could not configure Android Rust cc_common linking")

    rust_module = tree / "build" / "deps" / "rust.MODULE.bazel"
    rust_text = rust_module.read_text(encoding="utf-8")
    if '    "aarch64-linux-android",\n' not in rust_text:
        replace_once(
            rust_module,
            '    "aarch64-unknown-linux-gnu",\n',
            '    "aarch64-unknown-linux-gnu",\n    "aarch64-linux-android",\n',
        )

    rust_text = rust_module.read_text(encoding="utf-8")
    if '        "aarch64-linux-android": ["-Ctarget-feature=+crc"],\n' not in rust_text:
        replace_once(
            rust_module,
            '        "aarch64-unknown-linux-gnu": ["-Ctarget-feature=+crc"],\n',
            '        "aarch64-unknown-linux-gnu": ["-Ctarget-feature=+crc"],\n'
            '        "aarch64-linux-android": ["-Ctarget-feature=+crc"],\n',
        )

    bazelrc = tree / ".bazelrc"
    bazelrc_text = bazelrc.read_text(encoding="utf-8")
    if "build:android --config=unix" not in bazelrc_text:
        bazelrc.write_text(
            bazelrc_text
            + '''
# Community native Android configuration used by termux-python.
# Keep host tools native to the Linux CI runner while target C/C++ uses the NDK.
build:android --config=unix
build:android --@capnp-cpp//src/kj:libdl=False
# Build-time target executables (notably gen-compile-cache) stay in Android
# target configuration and are executed through the CI-provided Termux runner.
build:android --//build/config:target_run_under=/usr/local/bin/workerd-android-run-under
# Host-side V8 generators must emit ARM64 code/snapshots for the Android target.
build:android --@v8//bazel/config:v8_target_cpu=arm64
build:release_android --config=android
build:release_android --config=release_unix
build:release_android --@workerd//src/workerd/server:use_tcmalloc=False
build:release_android --@workerd//src/workerd/util:use_perfetto=False
''',
            encoding="utf-8",
        )

    # Match workerd's supported Linux host-toolchain baseline. These settings only
    # configure Bazel's host/exec C++ toolchain; the Android target platform is
    # still compiled and linked by rules_android_ndk.
    # LLVM 19 can emit out-of-line __atomic_* helpers in V8 exec binaries such as mksnapshot.
    # Keep libatomic host-only so Android target C/C++ remains entirely under the NDK toolchain.
    host_toolchain_settings = (
        "build:android --repo_env=CC=/usr/lib/llvm-19/bin/clang\n",
        "build:android --repo_env=AR=/usr/lib/llvm-19/bin/llvm-ar\n",
        "build:android --host_linkopt=--ld-path=/usr/lib/llvm-19/bin/ld.lld\n",
        "build:android --host_linkopt=-latomic\n",
    )
    bazelrc_text = bazelrc.read_text(encoding="utf-8")
    missing_host_settings = [
        setting for setting in host_toolchain_settings if setting not in bazelrc_text
    ]
    if missing_host_settings:
        replace_once(
            bazelrc,
            "build:android --@capnp-cpp//src/kj:libdl=False\n",
            "build:android --@capnp-cpp//src/kj:libdl=False\n" + "".join(missing_host_settings),
        )
        bazelrc_text = bazelrc.read_text(encoding="utf-8")

    runner_setting = "build:android --//build/config:target_run_under=/usr/local/bin/workerd-android-run-under\n"
    if runner_setting not in bazelrc_text:
        replace_once(
            bazelrc,
            "build:android --@capnp-cpp//src/kj:libdl=False\n",
            "build:android --@capnp-cpp//src/kj:libdl=False\n" + runner_setting,
        )

    print(f"Patched workerd Android target in {tree}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
