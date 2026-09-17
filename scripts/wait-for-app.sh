#!/usr/bin/env bash
# Poll a deployed app until it answers, so a green `terraform apply` that produced
# a container which cannot start is reported as the failure it is.
#
#   scripts/wait-for-app.sh https://example.azurecontainerapps.io [attempts]
#
# The app pulls a PUBLIC image with no credentials, so a private or misconfigured
# package would otherwise be a green-but-broken apply.
set -euo pipefail

url="${1:?usage: wait-for-app.sh <url> [attempts]}"
attempts="${2:-30}"

echo "Waiting for the app at $url to come up…"
for i in $(seq 1 "$attempts"); do
  # On a failed/timed-out request curl exits non-zero; overwrite (not append) so
  # code is a clean "000", never a false-positive like "000000". Only a real app
  # response (2xx/3xx/4xx) counts as up — a 000 (no reply) or 5xx (no healthy
  # backend) keeps waiting.
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$url") || code=000
  echo "  [$i] HTTP $code"
  case "$code" in
    2??|3??|4??) echo "App is up (HTTP $code)."; exit 0 ;;
  esac
  sleep 10
done
echo "::error::App never responded (~$((attempts * 10))s) — check the container logs."
exit 1
