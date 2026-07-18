#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: build_psutil_wheel.sh /absolute/path/python.deb /absolute/output/dir" >&2
  exit 2
fi

python_deb=$1
output_dir=$2
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
python -m pip install --upgrade pip setuptools wheel
python -m pip wheel --no-deps --wheel-dir "$output_dir" psutil

wheel=$(find "$output_dir" -maxdepth 1 -type f -name 'psutil-*.whl' -print -quit)
if [[ -z "$wheel" ]]; then
  echo "psutil wheel was not produced" >&2
  exit 1
fi

rm -rf /tmp/termux-python-psutil-test
python -m venv /tmp/termux-python-psutil-test
/tmp/termux-python-psutil-test/bin/python -m pip install --no-index "$wheel"
/tmp/termux-python-psutil-test/bin/python - <<'PY'
import json
import platform
import psutil
import sys

print(json.dumps({
    "python": sys.version,
    "implementation": platform.python_implementation(),
    "machine": platform.machine(),
    "psutil": psutil.__version__,
    "cpu_count": psutil.cpu_count(),
}, indent=2))
PY

/tmp/termux-python-psutil-test/bin/python - "$output_dir" <<'PY'
import json
import platform
import psutil
import sys
from pathlib import Path

output = Path(sys.argv[1]) / f"build-info-{sys.version_info.major}.{sys.version_info.minor}.json"
output.write_text(json.dumps({
    "python": sys.version,
    "python_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
    "psutil": psutil.__version__,
    "machine": platform.machine(),
}, indent=2) + "\n")
PY
