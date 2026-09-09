#!/usr/bin/env bash
#
# Push the GitHub Actions secrets/variables for the Azure CI deploy, read from a
# fill-in file (default: scripts/github-secrets.env).
#
#   cp scripts/github-secrets.env.template scripts/github-secrets.env
#   # ...fill in the values...
#   bash scripts/setup-github-secrets.sh
#
# Values are piped straight to `gh` — never printed, never echoed. The fill-in
# file holds real secrets: it is gitignored, and this script offers to delete it
# when done. ACR_NAME is a GitHub *variable* (not a secret); everything else is a
# secret. Leave a value blank in the file to skip it.

set -euo pipefail

FILE="${1:-scripts/github-secrets.env}"
VARS=" ACR_NAME " # space-delimited set of keys that are variables, not secrets

command -v gh >/dev/null || { echo "error: gh (GitHub CLI) not installed." >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "error: run 'gh auth login' first." >&2; exit 1; }
if [[ ! -f "$FILE" ]]; then
  echo "error: $FILE not found." >&2
  echo "  cp scripts/github-secrets.env.template scripts/github-secrets.env  # then fill it in" >&2
  exit 1
fi

REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
echo "Target repository: $REPO"

set_n=0
skip_n=0
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"                       # strip a trailing CR (CRLF files)
  [[ -z "$line" || "$line" == \#* ]] && continue
  [[ "$line" != *=* ]] && continue
  key="${line%%=*}"
  val="${line#*=}"
  key="${key// /}"                           # trim spaces around the key
  val="${val#"${val%%[![:space:]]*}"}"       # trim leading whitespace
  val="${val%"${val##*[![:space:]]}"}"       # trim trailing whitespace
  if [[ -z "$val" ]]; then
    echo "  skip   $key (blank)"
    skip_n=$((skip_n + 1))
    continue
  fi
  if [[ "$VARS" == *" $key "* ]]; then
    gh variable set "$key" --body "$val" >/dev/null
    echo "  ✓ var    $key"
  else
    printf '%s' "$val" | gh secret set "$key" >/dev/null   # value via stdin, not argv
    echo "  ✓ secret $key"
  fi
  set_n=$((set_n + 1))
done <"$FILE"

echo
echo "Set $set_n, skipped $skip_n."
echo
echo "⚠  $FILE still holds your real secrets (it is gitignored, but not deleted)."
read -rp "Delete it now? [y/N] " yn </dev/tty 2>/dev/null || yn=""
if [[ "${yn:-}" =~ ^[Yy]$ ]]; then
  rm -f "$FILE"
  echo "Deleted $FILE."
else
  echo "Kept $FILE — delete it yourself when you're done."
fi

echo
echo "Secrets now on $REPO:"
gh secret list
echo
echo "Variables:"
gh variable list
