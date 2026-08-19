# Signed Termux APT repository server

This directory records the non-secret infrastructure currently used by the public native Termux package repository.

The production endpoint is `http://144.21.61.111/termux`. Port `8000` remains available as a compatibility fallback, but new clients use standard HTTP port 80 to avoid carrier/VPN proxy failures on nonstandard ports. The repository signing fingerprint is:

```text
EAD24A2124EFA7393A78B7B14699F966313F7A6B
```

The private OpenPGP signing key is intentionally **not** stored in Git, GitHub Actions, or the unprivileged release downloader. It exists only in the production server's root-owned signing home.

## Trust split

1. GitHub Actions builds and tests release artifacts.
2. `sync_release_packages.py` runs as the unprivileged `termuxrepo` user every 15 minutes. It accepts only the explicit package allowlist, requires GitHub's `sha256:` asset digest, validates Debian package identity/architecture, and stages completed downloads under `/srv/termux-repo/incoming`.
3. A root-owned systemd path unit notices completed `.deb` files and invokes `publish_termux_repo.sh`. There is no sudo capability in the downloader service.
4. The publisher validates the allowlist again, refuses any package named plain `python`, keeps only the newest version of each package/architecture in the active pool, builds APT indices, signs `Release`/`InRelease`, verifies the signature before publication, then atomically swaps `/srv/termux-repo/current`.
5. Five signed filesystem snapshots are retained for rollback. Published `.deb` files are mode `0644`; the incoming staging directory is not publicly served.

## Production file placement

```text
/usr/local/bin/sync-termux-repo                 <- server/sync_release_packages.py
/usr/local/sbin/publish-termux-repo             <- server/publish_termux_repo.sh
/etc/systemd/system/termux-repo-sync.service
/etc/systemd/system/termux-repo-sync.timer
/etc/systemd/system/termux-repo-publish.service
/etc/systemd/system/termux-repo-publish.path
/etc/nginx/sites-available/adybag-termux-repo
/srv/termux-repo/incoming
/srv/termux-repo/releases
/srv/termux-repo/current -> releases/<timestamp>
/var/lib/termux-repo/gnupg                     <- server-only private signing home
```

## Required host packages

Ubuntu/Debian host packages: `nginx`, `dpkg-dev`, `apt-utils`, `gnupg`, `ca-certificates`, `curl`, `xz-utils`, `rsync`.

The server requires a dedicated unprivileged `termuxrepo` account with write access only to `/srv/termux-repo/incoming`. It does not need SSH access or sudo. The production account has a `nologin` shell and no authorized SSH keys.

After installing the units:

```bash
systemctl daemon-reload
systemctl enable --now termux-repo-sync.timer termux-repo-publish.path nginx
```

The OpenPGP key must be provisioned separately into `/var/lib/termux-repo/gnupg`; never automate a private signing key into repository source.
