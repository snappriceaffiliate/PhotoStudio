#!/usr/bin/env bash
# Create deploy/.env.production from the template, with fresh random secrets.
#   ./deploy/make-env.sh app.example.com
# It never overwrites an existing file, and the result is readable by you only.
set -euo pipefail
domain="${1:-}"
if [[ -z "$domain" || "$domain" == *"/"* || "$domain" == *":"* || "$domain" == "app.example.com" ]]; then
  echo "Usage: $0 <your-domain>   (for example app.yourname.in, without https://)" >&2
  exit 1
fi
here="$(cd "$(dirname "$0")" && pwd)"
target="$here/.env.production"
if [[ -e "$target" ]]; then
  echo "$target already exists. Delete it first if you really want a new one (this changes every secret)." >&2
  exit 1
fi
secret() { openssl rand -hex "$1"; }  # hex only, so the values are safe inside URLs
umask 077
sed \
  -e "s|__DOMAIN__|$domain|g" \
  -e "s|__SECRET_KEY__|$(secret 32)|" \
  -e "s|__POSTGRES_ADMIN_PASSWORD__|$(secret 24)|" \
  "$here/.env.production.example" > "$target.tmp"
app_password="$(secret 24)"
sed -e "s|__APP_DB_PASSWORD__|$app_password|g" "$target.tmp" > "$target"
rm "$target.tmp"
echo "Created $target"
echo "Next: open it and fill in the storage, email and payment sections."
