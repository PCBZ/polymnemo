#!/usr/bin/env bash
# Post the Gemini review as inline PR comments, then an overall summary.
#
# The model can't run shell tools in CI (gemini-cli denies run_shell_command by
# policy in non-interactive mode), so it only writes JSON and the workflow writes
# that to review.json; this script posts it with jq + gh.
#
#   usage: post_gemini_review.sh <pr-number> <head-sha>
#
# Reads the findings from review.json:
#   {"summary": "<markdown>", "comments": [{path, line, severity, body}, ...]}
# Each finding becomes an inline comment on its diff line, prefixed by a severity
# dot — 🔴 high · 🟠 medium · 🟡 low. A line GitHub rejects (not on the diff) is
# skipped individually so one bad line can't sink the rest. Repo comes from
# $GITHUB_REPOSITORY, auth from $GH_TOKEN; the model's text is only ever read
# from the file, never interpolated into the shell.
set -uo pipefail

pr="${1:?usage: post_gemini_review.sh <pr-number> <head-sha>}"
sha="${2:?usage: post_gemini_review.sh <pr-number> <head-sha>}"
repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
file="${REVIEW_FILE:-review.json}"

# Tolerate ```json ... ``` fences the model may wrap the JSON in.
grep -v '^```' "$file" > "$file.clean" && mv "$file.clean" "$file"

jq -c '.comments[]?' "$file" | while read -r c; do
  case "$(jq -r '.severity // "low"' <<<"$c")" in
    high) dot='🔴' ;;
    medium) dot='🟠' ;;
    *) dot='🟡' ;;
  esac
  gh api --method POST "repos/$repo/pulls/$pr/comments" \
    -f commit_id="$sha" \
    -f path="$(jq -r '.path' <<<"$c")" \
    -F line="$(jq -r '.line' <<<"$c")" \
    -f side='RIGHT' \
    -f body="$dot $(jq -r '.body' <<<"$c")" \
    || echo "::warning::skipped inline comment ($(jq -r '.path' <<<"$c"):$(jq -r '.line' <<<"$c")) — not on the diff"
done

jq -r '.summary // "## 🤖 Gemini review"' "$file" | gh pr comment "$pr" --repo "$repo" --body-file -
