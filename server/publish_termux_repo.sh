#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
exec 9>/run/lock/adybag-termux-repo.lock
flock 9

BASE=/srv/termux-repo
INCOMING="$BASE/incoming"
RELEASES="$BASE/releases"
NOW="$(date -u +%Y%m%dT%H%M%SZ)"
STAGE="$RELEASES/.staging-$NOW-$$"
FINAL="$RELEASES/$NOW"
GNUPGHOME=/var/lib/termux-repo/gnupg
export GNUPGHOME
FPR="$(cat /var/lib/termux-repo/signing-fingerprint)"

cleanup(){ rm -rf "$STAGE"; }
trap cleanup EXIT
mkdir -p "$STAGE/termux/pool/main" "$STAGE/termux/dists/stable/main/binary-aarch64"

if [ -L "$BASE/current" ] && [ -d "$BASE/current/termux/pool/main" ]; then
  cp -a "$BASE/current/termux/pool/main/." "$STAGE/termux/pool/main/"
fi

shopt -s nullglob
files=("$INCOMING"/*.deb)
for deb in "${files[@]}"; do
  pkg="$(dpkg-deb -f "$deb" Package)"
  ver="$(dpkg-deb -f "$deb" Version)"
  arch="$(dpkg-deb -f "$deb" Architecture)"
  case "$pkg" in
    python)
      echo "Refusing package named 'python': $deb would shadow official Termux Python" >&2
      exit 1
      ;;
    python3.[0-9]|python3.[0-9][0-9]|python3.[0-9]-ensurepip-wheels|python3.[0-9][0-9]-ensurepip-wheels|wrangler|uv|hermes-agent)
      ;;
    *)
      echo "Refusing unapproved package name: $pkg" >&2
      exit 1
      ;;
  esac
  case "$arch" in aarch64|all) ;; *) echo "Refusing architecture $arch for $pkg" >&2; exit 1;; esac
  test -n "$ver"
  cp -f "$deb" "$STAGE/termux/pool/main/$(basename "$deb")"
done

# Keep only the newest Debian version of each package/architecture in the live
# tree. Older immutable snapshots remain available under $RELEASES for rollback,
# while the active pool stays bounded as CI publishes new Wrangler/uv/Hermes builds.
declare -A newest_ver=() newest_file=()
for deb in "$STAGE/termux/pool/main"/*.deb; do
  pkg="$(dpkg-deb -f "$deb" Package)"
  ver="$(dpkg-deb -f "$deb" Version)"
  arch="$(dpkg-deb -f "$deb" Architecture)"
  key="$pkg:$arch"
  if [[ -z "${newest_ver[$key]:-}" ]] || dpkg --compare-versions "$ver" gt "${newest_ver[$key]}"; then
    newest_ver[$key]="$ver"
    newest_file[$key]="$deb"
  fi
done
for deb in "$STAGE/termux/pool/main"/*.deb; do
  pkg="$(dpkg-deb -f "$deb" Package)"
  arch="$(dpkg-deb -f "$deb" Architecture)"
  key="$pkg:$arch"
  [[ "$deb" == "${newest_file[$key]}" ]] || rm -f "$deb"
done

# Downloads are intentionally staged with mkstemp(0600). Only after package
# metadata validation/pruning do they become public repository artifacts.
chmod 0644 "$STAGE/termux/pool/main"/*.deb

cd "$STAGE/termux"
dpkg-scanpackages --multiversion pool/main /dev/null > dists/stable/main/binary-aarch64/Packages
gzip -9nc dists/stable/main/binary-aarch64/Packages > dists/stable/main/binary-aarch64/Packages.gz
xz -9e -c dists/stable/main/binary-aarch64/Packages > dists/stable/main/binary-aarch64/Packages.xz

apt-ftparchive \
  -o APT::FTPArchive::Release::Origin='adybag14-cyber' \
  -o APT::FTPArchive::Release::Label='AdyBag Termux Native' \
  -o APT::FTPArchive::Release::Suite='stable' \
  -o APT::FTPArchive::Release::Codename='stable' \
  -o APT::FTPArchive::Release::Architectures='aarch64' \
  -o APT::FTPArchive::Release::Components='main' \
  -o APT::FTPArchive::Release::Description='Native Android/Termux packages built and tested by adybag14-cyber CI' \
  release dists/stable > dists/stable/Release

gpg --batch --yes --local-user "$FPR" --clearsign \
  --output dists/stable/InRelease dists/stable/Release
gpg --batch --yes --local-user "$FPR" --detach-sign --armor \
  --output dists/stable/Release.gpg dists/stable/Release
cp /var/lib/termux-repo/repo-signing-key.asc repo-signing-key.asc
cp /var/lib/termux-repo/repo-signing-key.gpg repo-signing-key.gpg
printf '%s  repo-signing-key.gpg\n' "$(sha256sum repo-signing-key.gpg | awk '{print $1}')" > repo-signing-key.sha256
printf '%s\n' "$FPR" > repo-signing-key.fingerprint

# Sanity checks before exposing a new tree.
gpgv --keyring /var/lib/termux-repo/repo-signing-key.gpg dists/stable/InRelease >/dev/null
find . -type f -print0 | sort -z | xargs -0 sha256sum > REPOSITORY-SHA256SUMS

cd "$RELEASES"
mv "$STAGE" "$FINAL"
trap - EXIT
ln -sfn "releases/$NOW" "$BASE/current.new"
mv -Tf "$BASE/current.new" "$BASE/current"

rm -f "$INCOMING"/*.deb
# Keep the five most recent immutable snapshots.
mapfile -t old < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -name '20*' -printf '%f\n' | sort -r | tail -n +6)
for name in "${old[@]}"; do rm -rf "$RELEASES/$name"; done

echo "Published $NOW"
