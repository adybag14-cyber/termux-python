# Native Python builds for Termux aarch64

[![Daily Termux aarch64 builds](https://github.com/adybag14-cyber/termux-python/actions/workflows/daily-build.yml/badge.svg)](https://github.com/adybag14-cyber/termux-python/actions/workflows/daily-build.yml)
[![Validate repository](https://github.com/adybag14-cyber/termux-python/actions/workflows/validate.yml/badge.svg)](https://github.com/adybag14-cyber/termux-python/actions/workflows/validate.yml)

This repository builds native Android/Termux packages for **64-bit ARM (`aarch64`)** every day and publishes them in uniquely tagged GitHub Releases.

It produces:

- CPython 3.9, 3.10, 3.11, 3.12, 3.13, and 3.14 Termux `.deb` packages.
- New stable Python series automatically after the upstream Termux recipe supports them.
- A native `uv` and `uvx` Termux `.deb` package.
- A native `psutil` wheel built and import-tested separately against every successful Python build.
- `SHA256SUMS`, JSON, and TSV release indexes containing immutable asset URLs.

CPython is not itself a Python wheel. The interpreter is distributed as a Termux `.deb`; compiled extension packages such as `psutil` are distributed as wheels.

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

After a future stable series is published by this project, the same form works, for example:

```bash
curl -fsSL https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/install.sh | bash -s -- 3.15 --with-uv --with-psutil
```

## Important package behaviour

The Python packages intentionally keep Termux's normal package name, `python`. Installing Python 3.10 after Python 3.14 therefore **switches the active Termux Python**; it does not install both interpreters side by side.

This avoids pretending that packages compiled for different Python ABIs can safely share one Termux prefix. After switching versions, reinstall pip packages containing native extensions.

The installer:

1. verifies that it is running in the standard native Termux prefix;
2. verifies the architecture is `aarch64`;
3. downloads the latest release index;
4. selects the requested Python series;
5. follows the exact immutable release URL recorded in that index;
6. verifies SHA-256 before installing anything;
7. checks that the installed interpreter has the requested major/minor version.

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
8. Successful outputs are published even when one legacy Python series fails, so an old ABI cannot block newer builds.

## Daily and manual builds

The scheduled workflow runs every day at 04:23 UTC. A manual run can build all configured versions or selected series such as:

```text
3.13,3.14
```

Open **Actions → Daily Termux aarch64 builds → Run workflow** and enter the desired series.

## Repository layout

```text
.github/workflows/daily-build.yml   Daily matrix build and release
.github/workflows/validate.yml      Syntax, resolver, and index validation
config/series.json                  Historical recipe refs for known ABIs
install.sh                          Checksum-verifying Termux installer
scripts/resolve_versions.py         Stable release and future-series resolver
scripts/prepare_python_recipe.py    Recipe extraction and source update
scripts/build_psutil_wheel.sh       Native aarch64 wheel build and import test
scripts/generate_release_index.py   Immutable URLs and SHA-256 indexes
```

## Limitations

- Only Android/Termux `aarch64` is currently built.
- Packages target the standard `com.termux` prefix, `/data/data/com.termux/files/usr`.
- This is an independent project, not an official Python, Termux, Astral, uv, or psutil distribution.
- Legacy CPython series may stop compiling against modern Android toolchains. Matrix failures are isolated and visible in GitHub Actions.
- A successful build does not make every package on PyPI Android-compatible. Native extensions may still require Termux-specific patches.

## Sources and licensing

Build scripts reuse and transform recipes and patches from [`termux/termux-packages`](https://github.com/termux/termux-packages). CPython, uv, psutil, and Termux retain their respective upstream licences. This repository's original automation code is available under the MIT License.
