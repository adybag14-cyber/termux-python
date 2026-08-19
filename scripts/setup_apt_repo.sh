#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

REPO_URL="${ADYBAG_TERMUX_REPO_URL:-http://144.21.61.111/termux}"
EXPECTED_FINGERPRINT="EAD24A2124EFA7393A78B7B14699F966313F7A6B"
KEY_URL="https://raw.githubusercontent.com/adybag14-cyber/termux-python/main/apt/repo-signing-key.asc"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
KEYRING_DIR="$PREFIX/etc/apt/keyrings"
KEYRING="$KEYRING_DIR/adybag-termux.gpg"
SOURCE="$PREFIX/etc/apt/sources.list.d/adybag-termux.list"

echo "Installing signed AdyBag native Termux repository..."
pkg install -y ca-certificates curl gnupg >/dev/null
mkdir -p "$KEYRING_DIR" "$(dirname "$SOURCE")"
tmp="$(mktemp "${TMPDIR:-$PREFIX/tmp}/adybag-repo-key.XXXXXX")"
trap 'rm -f "$tmp" "$tmp.gpg"' EXIT
curl -fL --retry 3 --retry-all-errors "$KEY_URL" -o "$tmp"
actual="$(gpg --batch --with-colons --show-keys "$tmp" | awk -F: '$1=="fpr" {print $10; exit}')"
if [ "$actual" != "$EXPECTED_FINGERPRINT" ]; then
  echo "Repository signing-key fingerprint mismatch: $actual" >&2
  exit 1
fi
gpg --batch --yes --dearmor --output "$tmp.gpg" "$tmp"
install -m 0644 "$tmp.gpg" "$KEYRING"
printf 'deb [signed-by=%s] %s stable main\n' "$KEYRING" "$REPO_URL" > "$SOURCE"
apt -o Acquire::Retries=5 -o Acquire::http::Timeout=30 update
cat <<EOF
Repository enabled and signature verified.
Signing fingerprint: $EXPECTED_FINGERPRINT

Examples:
  pkg install wrangler
  pkg install uv
  pkg install python3.11
  pkg install python3.12
  pkg install python3.13
EOF