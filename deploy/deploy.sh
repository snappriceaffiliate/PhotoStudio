#!/usr/bin/env bash
# Deploy or update the app on the server. Safe to run again.
#   /opt/deployment/deploy.sh          (the wrapper) or ./deploy/deploy.sh
# What it does: takes the latest code from main, backs up the database if one is running,
# rebuilds, restarts, and waits until the web app reports healthy.
# BRANCH=<name> deploys another branch (for example to try a change); SERVICES="db web" starts
# only some services.
set -euo pipefail

# Everything is inside main(), which is called on the last line: git may replace this very
# file while it updates the code, and bash must already have read all of it by then.
main() {
  cd "$(dirname "$0")/.."

  if [[ ! -f deploy/.env.production ]]; then
    echo "Missing deploy/.env.production. Run ./deploy/make-env.sh <your-domain> first." >&2
    exit 1
  fi
  compose=(docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml)
  branch="${BRANCH:-main}"

  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "This folder has uncommitted changes; refusing to deploy over them. Run 'git status'." >&2
    exit 1
  fi
  before="$(git rev-parse --short HEAD)"
  git fetch --quiet origin
  git checkout --quiet "$branch"
  git pull --ff-only --quiet origin "$branch"
  after="$(git rev-parse --short HEAD)"

  if [[ -n "$("${compose[@]}" ps --status running --quiet db 2>/dev/null)" ]]; then
    ./deploy/backup.sh
  else
    echo "No running database yet (first deploy): nothing to back up."
  fi

  # shellcheck disable=SC2086 # SERVICES is meant to split into words
  "${compose[@]}" up -d --build ${SERVICES:-}

  echo "Waiting for the web app to become healthy..."
  for _ in $(seq 1 60); do
    if [[ "$("${compose[@]}" ps --format '{{.Service}}={{.Health}}' web 2>/dev/null)" == "web=healthy" ]]; then
      echo "Deployed $before -> $after (branch $branch)."
      "${compose[@]}" ps
      exit 0
    fi
    sleep 3
  done

  echo "The web app did not become healthy within 3 minutes. Recent log lines:" >&2
  "${compose[@]}" logs --tail 40 web >&2 || true
  echo >&2
  echo "To go back to the previous version:" >&2
  echo "  git checkout $before && docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml up -d --build" >&2
  exit 1
}

main "$@"
exit $?
