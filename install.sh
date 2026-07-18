#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

REPOSITORY="adybag14-cyber/termux-python"
INDEX_URL="https://github.com/${REPOSITORY}/releases/latest/download/release-index.tsv"

usage() {
  cat <<'EOF'
Install CPython, uv, and psutil builds made for native Termux aarch64.

Usage:
  install.sh 3.14 [--with-uv] [--with-psutil]
  install.sh uv

Examples:
  install.sh 3.13
  install.sh 3.14 --with-uv --with-psutil
  install.sh uv
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

target=$1
shift
with_uv=false
with_psutil=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-uv) with_uv=true ;;
    --with-psutil) with_psutil=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ "${PREFIX:-}" != "/data/data/com.termux/files/usr" ]]; then
  echo "This installer only supports the standard native Termux prefix:" >&2
  echo "  /data/data/com.termux/files/usr" >&2
  exit 1
fi

arch=$(dpkg --print-architecture 2>/dev/null || true)
if [[ "$arch" != "aarch64" ]]; then
  echo "Only Termux aarch64 is currently supported; detected: ${arch:-unknown}" >&2
  exit 1
fi

workdir=$(mktemp -d "${TMPDIR:-$PREFIX/tmp}/termux-python.XXXXXX")
trap 'rm -rf "$workdir"' EXIT
index="$workdir/release-index.tsv"
curl -fL --retry 4 --retry-all-errors -o "$index" "$INDEX_URL"

lookup() {
  local kind=$1
  local minor=$2
  awk -F '\t' -v wanted_kind="$kind" -v wanted_minor="$minor" '
    NR > 1 && $1 == wanted_kind && $2 == wanted_minor { print; exit }
  ' "$index"
}

download_row() {
  local row=$1
  local row_kind row_minor version architecture filename checksum url
  IFS=$'\t' read -r row_kind row_minor version architecture filename checksum url <<< "$row"
  local destination="$workdir/$filename"
  curl -fL --retry 4 --retry-all-errors -o "$destination" "$url"
  printf '%s  %s\n' "$checksum" "$destination" | sha256sum -c - >&2
  printf '%s\n' "$destination"
}

install_deb_kind() {
  local kind=$1
  local minor=$2
  local row
  row=$(lookup "$kind" "$minor")
  if [[ -z "$row" ]]; then
    echo "No $kind build for ${minor/-/latest} exists in the latest release." >&2
    exit 1
  fi

  local row_kind row_minor version architecture filename checksum url
  IFS=$'\t' read -r row_kind row_minor version architecture filename checksum url <<< "$row"
  local file
  file=$(download_row "$row")

  apt-get update
  apt-get install -y --allow-downgrades --no-install-recommends "$file"
  echo "Installed $row_kind $version for $architecture"
}

install_python() {
  local minor=$1
  local python_row ensurepip_row
  python_row=$(lookup "python" "$minor")
  if [[ -z "$python_row" ]]; then
    echo "No Python $minor build exists in the latest release." >&2
    exit 1
  fi
  ensurepip_row=$(lookup "ensurepip" "$minor" || true)

  local python_file ensurepip_file=""
  python_file=$(download_row "$python_row")
  if [[ -n "$ensurepip_row" ]]; then
    ensurepip_file=$(download_row "$ensurepip_row")
  fi

  apt-get update
  # python-pip owns ABI-specific files and must not survive a Python switch.
  apt-get remove -y python-pip || true
  if [[ -n "$ensurepip_file" ]]; then
    apt-get install -y --allow-downgrades --no-install-recommends "$ensurepip_file" "$python_file"
  else
    apt-get install -y --allow-downgrades --no-install-recommends "$python_file"
  fi

  if ! python -m pip --version >/dev/null 2>&1; then
    python -m ensurepip --upgrade --default-pip
  fi
  python -m pip --version
}

install_psutil() {
  local minor=$1
  local row
  row=$(lookup "psutil" "$minor")
  if [[ -z "$row" ]]; then
    echo "No psutil wheel for Python $minor exists in the latest release." >&2
    exit 1
  fi

  local wheel
  wheel=$(download_row "$row")
  python -m pip install --force-reinstall "$wheel"
  python -c 'import psutil; print("psutil", psutil.__version__)'
}

if [[ "$target" == "uv" ]]; then
  install_deb_kind "uv" "-"
  uv --version
  exit 0
fi

if [[ "$target" =~ ^3\.([0-9]+)$ ]]; then
  target_minor=${BASH_REMATCH[1]}
else
  target_minor=0
fi
if ((10#$target_minor < 9)); then
  echo "Expected a Python minor version such as 3.10 or 3.14, or 'uv'." >&2
  exit 2
fi

cat <<EOF
Installing Python $target will switch the active Termux 'python' package.
Existing pip packages compiled for another Python ABI may need reinstalling.
EOF

install_python "$target"
python - <<PY
import sys
expected = tuple(map(int, "$target".split(".")))
actual = sys.version_info[:2]
if actual != expected:
    raise SystemExit(f"Installed Python mismatch: expected {expected}, got {actual}")
print(sys.version)
PY

if $with_uv; then
  install_deb_kind "uv" "-"
  uv --version
fi

if $with_psutil; then
  install_psutil "$target"
fi
