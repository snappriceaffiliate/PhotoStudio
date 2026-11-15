#!/usr/bin/env bash
# Create the server's /opt layout and the two wrapper scripts. Run once, as your normal user:
#   sudo -v && ./deploy/setup-layout.sh          (from inside the cloned repository)
#
#   /opt/picksnap/     the code (this repository); the compose file and settings live in deploy/
#   /opt/deployment/   deploy.sh and backup.sh, thin wrappers so you never need to cd anywhere
#   /opt/backup/       nightly database dumps (readable by you only)
#
# OPT_ROOT=/some/other/path changes /opt, which is only useful for trying this out.
set -euo pipefail
root="${OPT_ROOT:-/opt}"
repo="$(cd "$(dirname "$0")/.." && pwd)"
me="$(id -un)"
# Use sudo only when the folder is not already writable by this user.
as_root() { if [[ -w "$root" ]]; then "$@"; else sudo "$@"; fi; }

as_root mkdir -p "$root/picksnap" "$root/deployment" "$root/backup"
as_root chown -R "$me:" "$root/picksnap" "$root/deployment" "$root/backup"
as_root chmod 700 "$root/backup"

if [[ "$repo" != "$root/picksnap" ]]; then
  echo "Note: the repository is at $repo, not $root/picksnap." >&2
  echo "The wrappers will point at $repo. To follow the standard layout, clone it into $root/picksnap." >&2
fi

cat > "$root/deployment/deploy.sh" <<WRAP
#!/usr/bin/env bash
# Wrapper: update the app to the latest version. Logic lives in $repo/deploy/deploy.sh.
export BACKUP_DIR="\${BACKUP_DIR:-$root/backup}"
exec "$repo/deploy/deploy.sh" "\$@"
WRAP
cat > "$root/deployment/backup.sh" <<WRAP
#!/usr/bin/env bash
# Wrapper: back up the database into $root/backup. Logic lives in $repo/deploy/backup.sh.
export BACKUP_DIR="\${BACKUP_DIR:-$root/backup}"
exec "$repo/deploy/backup.sh" "\$@"
WRAP
chmod 755 "$root/deployment/deploy.sh" "$root/deployment/backup.sh"
echo "Ready:"
echo "  $root/deployment/deploy.sh   deploy or update"
echo "  $root/deployment/backup.sh   back up the database to $root/backup"
