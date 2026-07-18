#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: build_psutil_wheel.sh /absolute/path/python.deb /absolute/output/dir 3.x" >&2
  exit 2
fi

python_deb=$1
output_dir=$2
python_minor=$3
psutil_version=7.2.2
psutil_sha256=38f406bf21acc67e45f414b7980463b2e6e6270ba3616ffd41995d997078cbe6
psutil_url="https://github.com/giampaolo/psutil/archive/refs/tags/release-${psutil_version}.tar.gz"

if [[ ! "$python_minor" =~ ^3\.[0-9]+$ ]]; then
  echo "invalid Python minor: $python_minor" >&2
  exit 2
fi

mkdir -p "$output_dir"

for attempt in 1 2 3 4; do
  if pkg update -y && pkg install -y clang make pkg-config; then
    break
  fi
  if [[ $attempt -eq 4 ]]; then
    echo "Termux package installation failed after $attempt attempts" >&2
    exit 1
  fi
  sleep $((attempt * 5))
done

install_debs=("$python_deb")
ensurepip_deb=$(find "$(dirname "$python_deb")" -maxdepth 1 -type f \
  -name 'python-ensurepip-wheels_*_all.deb' -print -quit || true)
if [[ -n "$ensurepip_deb" ]]; then
  install_debs=("$ensurepip_deb" "$python_deb")
fi

# Avoid installing the repository's current python-pip recommendation. The
# matching ensurepip wheels, when split by the recipe, are installed locally.
apt-get install -y --allow-downgrades --no-install-recommends "${install_debs[@]}"

if ! python -m pip --version >/dev/null 2>&1; then
  python -m ensurepip --upgrade --default-pip
fi
python -m pip install --upgrade pip setuptools wheel packaging

workdir=$(mktemp -d "$HOME/termux-psutil.XXXXXX")
test_venv="$HOME/termux-python-psutil-test"
trap 'rm -rf "$workdir" "$test_venv"' EXIT
archive="$workdir/psutil.tar.gz"
source_dir="$workdir/psutil-release-${psutil_version}"
wheelhouse="$workdir/wheelhouse"
mkdir -p "$wheelhouse"

curl -fL --retry 4 --retry-all-errors -o "$archive" "$psutil_url"
printf '%s  %s\n' "$psutil_sha256" "$archive" | sha256sum -c -
tar -xzf "$archive" -C "$workdir"

# CPython 3.14 identifies Android explicitly through sys.platform == "android".
# psutil 7.2.2 otherwise rejects that value even though Termux uses its Linux
# /proc backend. Treat Android as Linux in the shared platform detector so both
# setup.py and psutil's runtime import select the Linux implementation.
common_py="$source_dir/psutil/_common.py"
grep -q 'LINUX = sys.platform.startswith("linux")' "$common_py"
sed -i 's/LINUX = sys.platform.startswith("linux")/LINUX = sys.platform.startswith(("linux", "android"))/' "$common_py"
grep -q 'LINUX = sys.platform.startswith(("linux", "android"))' "$common_py"

python -m pip wheel \
  --no-build-isolation \
  --no-deps \
  --wheel-dir "$wheelhouse" \
  "$source_dir"

wheel=$(find "$wheelhouse" -maxdepth 1 -type f -name 'psutil-*.whl' -print -quit)
if [[ -z "$wheel" ]]; then
  echo "psutil wheel was not produced" >&2
  exit 1
fi

# psutil uses CPython's stable ABI, so every build naturally has the same
# cp36-abi3 filename. Add a valid numeric wheel build tag (39, 310, ...) to
# preserve a separately tested asset and release-index row for each Python ABI.
base=$(basename "$wheel")
rest=${base#psutil-${psutil_version}-}
build_tag=${python_minor//./}
published="$output_dir/psutil-${psutil_version}-${build_tag}-${rest}"
cp "$wheel" "$published"
chmod 0644 "$published"

rm -rf "$test_venv"
python -m venv "$test_venv"
"$test_venv/bin/python" -m pip install --no-index "$published"
"$test_venv/bin/python" - "$python_minor" <<'PY'
import json
import platform
import psutil
import sys

expected = sys.argv[1]
actual = f"{sys.version_info.major}.{sys.version_info.minor}"
if actual != expected:
    raise SystemExit(f"Python mismatch: expected {expected}, got {actual}")

print(json.dumps({
    "python": sys.version,
    "implementation": platform.python_implementation(),
    "machine": platform.machine(),
    "platform": sys.platform,
    "psutil": psutil.__version__,
    "cpu_count": psutil.cpu_count(),
}, indent=2))
PY

build_info="$output_dir/build-info-${python_minor}.json"
"$test_venv/bin/python" - "$build_info" <<'PY'
import json
import platform
import psutil
import sys
from pathlib import Path

output = Path(sys.argv[1])
output.write_text(json.dumps({
    "python": sys.version,
    "python_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
    "python_platform": sys.platform,
    "psutil": psutil.__version__,
    "machine": platform.machine(),
}, indent=2) + "\n")
PY

test -s "$build_info"
chmod 0644 "$build_info"
ls -la "$output_dir"
