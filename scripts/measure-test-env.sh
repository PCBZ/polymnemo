#!/usr/bin/env bash
# Measure the read payload against the DEPLOYED test env (#89 / #96):
#   1. target the test env (its /mcp endpoint + Log Analytics workspace)
#   2. seed memories, then exercise the real reads (recall / list / get / session)
#   3. fetch the #96 observe log lines from Log Analytics
#   4. save them to a local file
#
# The test env runs at POLYMNEMO_LOG_LEVEL=DEBUG, so its reads emit the observe
# lines (`read <op>: N rows, embedding fetched|deferred (~M bytes)`). Run this
# once on the no-defer image and once on the +defer image, then diff the two
# saved files to see what deferring the embedding (#89) saves.
#
# Requires: az (logged in; `az extension add -n log-analytics` if needed), curl,
# jq. Configure via the env vars below.
#
#   TEST_MCP_ENDPOINT=https://polymnemo-test.<...>.azurecontainerapps.io/mcp \
#   TEST_API_KEY=testkey:tester \
#   ./scripts/measure-test-env.sh
set -euo pipefail

ENDPOINT="${TEST_MCP_ENDPOINT:?set TEST_MCP_ENDPOINT (the test /mcp URL)}"
KEY="${TEST_API_KEY:?set TEST_API_KEY (a bearer key for the test env)}"
APP="${TEST_APP:-polymnemo-test}"
RG="${TEST_RG:-polymnemo-test-rg}"
WS_NAME="${TEST_WORKSPACE:-${APP}-logs}"
ROWS="${ROWS:-25}"                       # >= list_limit so `list` returns a full page
INGEST_WAIT="${INGEST_WAIT:-180}"        # Log Analytics ingestion lag (seconds)
OUT="${OUT:-read-payload-$(date +%Y%m%d-%H%M%S).json}"
NS="measure-$(date +%s)"
SESS="measure-sess-$(date +%s)"

# Call an MCP tool over Streamable HTTP; prints the JSON-RPC result object.
mcp() {
  curl -sS --max-time 30 "$ENDPOINT" \
    -H "Authorization: Bearer $KEY" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}" \
    | sed -n 's/^data: //p'
}

echo "== 1) test env: $APP  ($ENDPOINT)"

echo "== 2) seed $ROWS memories in namespace '$NS', then exercise the reads"
first_id=""
for i in $(seq 1 "$ROWS"); do
  res=$(mcp remember "{\"content\":\"measure row $i - remembered text for the read payload test\",\"namespace\":\"$NS\"}")
  if [ -z "$first_id" ]; then
    first_id=$(printf '%s' "$res" | jq -r '.result.structuredContent.ids[0] // empty' 2>/dev/null || true)
  fi
done
mcp save_session "{\"session_id\":\"$SESS\",\"content\":\"line one\nline two\nline three\"}" >/dev/null

# The four read paths that emit the #96 observe log:
mcp recall "{\"query\":\"remembered text\",\"namespace\":\"$NS\"}" >/dev/null           # -> search
mcp list_memories "{\"namespace\":\"$NS\"}" >/dev/null                                  # -> list
[ -n "$first_id" ] && mcp get_memory "{\"id\":\"$first_id\"}" >/dev/null                # -> get
mcp load_session "{\"session_id\":\"$SESS\"}" >/dev/null                                # -> get_session

echo "== 3) wait ${INGEST_WAIT}s for Log Analytics ingestion"
sleep "$INGEST_WAIT"

echo "== 4) fetch the observe logs -> $OUT"
WSID="$(az monitor log-analytics workspace show -g "$RG" -n "$WS_NAME" --query customerId -o tsv)"
az monitor log-analytics query --workspace "$WSID" --analytics-query "
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == '$APP'
| where Log_s startswith 'read '
| project TimeGenerated, Log_s
| order by TimeGenerated desc
| take 500" -o json >"$OUT"

n="$(jq 'length' "$OUT" 2>/dev/null || echo '?')"
echo "saved $n observe log rows to $OUT"
echo "(if 0 rows, ingestion is still lagging — re-run step 4's az query in a minute)"
