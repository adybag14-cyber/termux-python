# Native Python and developer-tool builds for Termux aarch64

[![Daily Termux aarch64 builds](https://github.com/adybag14-cyber/termux-python/actions/workflows/daily-build.yml/badge.svg)](https://github.com/adybag14-cyber/termux-python/actions/workflows/daily-build.yml)
[![Validate repository](https://github.com/adybag14-cyber/termux-python/actions/workflows/validate.yml/badge.svg)](https://github.com/adybag14-cyber/termux-python/actions/workflows/validate.yml)

This repository builds native Android/Termux packages for **64-bit ARM (`aarch64`)** every day and publishes them in uniquely tagged GitHub Releases.

It produces:

- CPython 3.9, 3.10, 3.11, 3.12, 3.13, and 3.14 Termux `.deb` packages.
- New stable Python series automatically after the upstream Termux recipe supports them.
- A native `uv` and `uvx` Termux `.deb` package.
- A native Cloudflare `wrangler` Termux `.deb`, with Wrangler built from its matching `workers-sdk` tag plus matching Android/Bionic `workerd` and `esbuild` binaries compiled from source.
- A native `psutil` wheel built and import-tested separately against every successful Python build.
- `SHA256SUMS`, JSON, and TSV release indexes containing immutable asset URLs.

CPython is not itself a Python wheel. The interpreter is distributed as a Termux `.deb`; compiled extension packages such as `psutil` are distributed as wheels.

## Signed APT repository (`pkg install`)

The project also publishes the tested `.deb` outputs through a signed third-party Termux APT repository. The repository is served from the same Oracle VM that runs the native Hermes gateway, while the repository signing key is kept only on that server. The server polls immutable public GitHub Releases, verifies GitHub-published SHA-256 digests and package metadata, and then signs/publishes locally; no server deployment private key is stored in GitHub Actions.

Enable it once from native Termux:

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/scripts/setup_apt_repo.sh | bash
```

The bootstrap verifies the repository key fingerprint before adding the source:

```text
EAD24A2124EFA7393A78B7B14699F966313F7A6B
```

After that the packages behave like normal Termux packages:

```bash
pkg install wrangler
pkg install uv
pkg install python3.11
pkg install python3.12
pkg install python3.13
pkg install python3.14
```

The APT variants of historical CPython are deliberately repackaged as `python3.X`. They remove only generic aliases such as `python`, `python3`, generic `pydoc`, `libpython3.so`, and generic pkg-config/manpage links, so multiple interpreter minors can coexist without replacing Termux's official rolling `python` package. Pip is bootstrapped only under its version-qualified command such as `pip3.13`.

The raw immutable GitHub-release `python_*.deb` assets are retained for the legacy checksum-pinned switch-style installer below; those continue to identify as package `python`. The signed APT repository **never accepts a package named plain `python`**.

Repository endpoint:

```text
http://144.21.61.111:8000/termux
```

## Copy-paste installation

These commands support the standard native Termux prefix on Android aarch64:

### Python 3.9

> Python 3.9 is end-of-life. Use it only for compatibility with old applications.

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/install.sh | bash -s -- 3.9
```

### Python 3.10

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/install.sh | bash -s -- 3.10
```

### Python 3.11

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/install.sh | bash -s -- 3.11
```

### Python 3.12

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/install.sh | bash -s -- 3.12
```

### Python 3.13

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/install.sh | bash -s -- 3.13
```

### Python 3.14

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/install.sh | bash -s -- 3.14
```

### Python, uv, and psutil together

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/install.sh | bash -s -- 3.14 --with-uv --with-psutil
```

### uv only

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/install.sh | bash -s -- uv
```

### Wrangler only

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/install.sh | bash -s -- wrangler
```

The Wrangler package includes the exact `workerd` and `esbuild` versions selected by that Wrangler release, compiled from source for native Android `aarch64`. It preserves Wrangler's upstream command layout: `wrangler`, the `wrangler2` compatibility alias, and the distinct `cf-wrangler` delegate entrypoint. The package deliberately does not ship platform-native npm binaries or Sharp's precompiled WASM fallback; Miniflare's local Images transforms therefore remain unavailable until that backend is built from source for this target, while core Wrangler, esbuild, and workerd functionality are unaffected.

After a future stable series is published by this project, the same form works, for example:

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/install.sh | bash -s -- 3.15 --with-uv --with-psutil
```

## Important package behaviour

There are now two intentionally different distribution modes:

- The signed APT repository exposes side-by-side `python3.X` packages and is the preferred public `pkg install` interface.
- The historical GitHub-release installer consumes the original package named `python` and therefore switches the active Termux Python when changing versions. This path is retained for compatibility and immutable-release testing.

Do not install the raw `python_*.deb` release asset manually if you want multiple Python minors to coexist; enable the APT repository and install `python3.X` instead.

The installer:

1. verifies that it is running in the standard native Termux prefix;
2. verifies the architecture is `aarch64`;
3. downloads the latest release index;
4. selects the requested package (and Python series when applicable);
5. follows the exact immutable release URL recorded in that index;
6. verifies SHA-256 before installing anything;
7. installs the selected asset and verifies the requested interpreter or tool version.

## Immutable releases

Every publishing run creates a new release tag similar to:

```text
termux-aarch64-20260718.42.1
```

Existing release tags and assets are never replaced by the workflow. `release-index.json` and `release-index.tsv` record the exact URL and SHA-256 of every downloadable asset. The `/releases/latest/download/release-index.tsv` pointer is only used to discover the newest immutable release.

## How the build works

1. `scripts/resolve_versions.py` reads the stable Python releases published on Python.org.
2. Each Python minor series uses a historical `termux/termux-packages` recipe from when Termux supported that ABI.
3. `scripts/prepare_python_recipe.py` updates that recipe to the newest patch release in the series and verifies the Python.org source hash.
4. The current Termux package build system cross-compiles the package for Android API 24 and `aarch64`.
5. The resulting package runs inside an emulated native aarch64 Termux container.
6. That interpreter builds pinned `psutil` source, applies the small Android-to-Linux `/proc` backend compatibility patch, and imports the wheel in a clean virtual environment.
7. The current upstream Termux `uv` recipe builds and tests `uv` and `uvx` separately.
8. The Wrangler job resolves the newest stable `wrangler` release and checks out its exact `workers-sdk` tag.
9. The matching `esbuild` version is compiled from source for Android `aarch64` (to ship in the package). For the Linux-side Wrangler source build, CI discovers every esbuild API version in Wrangler's filtered dependency graph and compiles each exact version from its upstream source tag before running the workspace build, avoiding prebuilt host esbuild binaries and cross-version protocol mismatches.
10. The matching `workerd` source is cross-compiled with the Android NDK and Bazel for `aarch64-linux-android`, including small Bionic compatibility patches for upstream assumptions that currently treat Android as ordinary glibc Linux. Linux host/exec C++ actions use the same LLVM 19 baseline as workerd upstream CI and explicitly link `libatomic` for V8 generator executables when LLVM emits out-of-line atomic helpers, while Android target C/C++ remains on the NDK API-24 toolchain. Workerd's Rust `gen-compile-cache` helper is linked through that Android C++ toolchain so the NDK compiler-rt builtins (including the AArch64 instruction-cache helper used by V8) are present even though rules_rust's ordinary final-link path suppresses default runtime libraries. Build-time Android target executables that must run during the cross-build are executed under an aarch64 Termux/QEMU container instead of being silently rebuilt against glibc.
11. CI installs the finished Wrangler `.deb` into an emulated aarch64 Termux environment, runs a Wrangler dry-run plus the distinct `cf-wrangler build` delegate to exercise the Android packaging paths, launches `wrangler dev`, and fetches a real local Worker response through Android workerd.
12. Successful outputs are indexed with SHA-256 hashes and published in the same immutable release. Legacy Python matrix failures remain isolated from newer Python series.

## Daily and manual builds

The scheduled workflow runs every day at 04:23 UTC. A manual run can build all configured versions or selected series such as:

```text
3.13,3.14
```

Open **Actions → Daily Termux aarch64 builds → Run workflow** and enter the desired series. The manual `wrangler_only` option skips Python and uv, performs the full Wrangler source build and Termux runtime smoke test, and never publishes a release.

## Repository layout

```text
.github/workflows/daily-build.yml   Daily matrix build and release
.github/workflows/validate.yml      Syntax, resolver, and index validation
config/series.json                  Historical recipe refs for known ABIs
install.sh                          Checksum-verifying Termux installer
scripts/resolve_versions.py         Stable release and future-series resolver
scripts/prepare_python_recipe.py    Recipe extraction and source update
scripts/build_psutil_wheel.sh       Native aarch64 wheel build and import test
scripts/patch_workerd_android.py     Android/Bionic workerd dependency/toolchain patcher
scripts/run_workerd_android_target_tool.sh  Execute Android build-time tools under Termux/QEMU
scripts/package_wrangler_android.py  Assemble the self-contained Wrangler Termux .deb
scripts/test_wrangler_termux.sh      Real Wrangler/esbuild/workerd Termux smoke test
scripts/generate_release_index.py   Immutable URLs and SHA-256 indexes
```

## Limitations

- Only Android/Termux `aarch64` is currently built.
- Packages target the standard `com.termux` prefix, `/data/data/com.termux/files/usr`.
- This is an independent project, not an official Python, Termux, Astral, uv, psutil, Cloudflare, Wrangler, workerd, or esbuild distribution.
- Legacy CPython series may stop compiling against modern Android toolchains. Matrix failures are isolated and visible in GitHub Actions.
- A successful build does not make every package on PyPI Android-compatible. Native extensions may still require Termux-specific patches.

## Sources and licensing

Build scripts reuse and transform recipes and patches from [`termux/termux-packages`](https://github.com/termux/termux-packages), and build Wrangler/workerd/esbuild from their upstream source repositories. CPython, uv, psutil, Termux, Wrangler, workerd, esbuild, and their dependencies retain their respective upstream licences. This repository's original automation code is available under the MIT License.
