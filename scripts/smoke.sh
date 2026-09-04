#!/usr/bin/env bash
# End-to-end smoke test against a running API service.
#
#   API_BASE=http://127.0.0.1:8000 bash scripts/smoke.sh
#
# Walks the happy path from PRD section 1.2: sign in, create a plan session,
# answer the follow-up round, read the three plans, activate one, list its
# tasks, mark one done, export Markdown. Exits non-zero on the first surprise.
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8000}"
V1="${API_BASE}/v1"
EMAIL="${SMOKE_EMAIL:-smoke-$(date +%s)@example.com}"

say() { printf '\n=== %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
jqr() { jq -er "$1" 2>/dev/null || fail "unexpected response shape: expected $1"; }

command -v jq >/dev/null || fail "jq is required"

say "health"
curl -sf "${API_BASE}/health" | jqr '.status'

say "sign in as ${EMAIL}"
TOKEN=$(curl -sf -X POST "${V1}/auth/google" \
  -H 'content-type: application/json' \
  -d "{\"code\": \"fake:${EMAIL}\", \"redirect_uri\": \"http://localhost/cb\"}" \
  | jqr '.access_token')
AUTH=(-H "authorization: Bearer ${TOKEN}")

say "create plan session"
SESSION=$(curl -sf -X POST "${V1}/plan-sessions" "${AUTH[@]}" \
  -H 'content-type: application/json' \
  -d '{"goal": "12 週 5K 跑進 30 分"}' | jqr '.session_id')

poll_session() {
  local want="$1" tries=0 body status
  while [ $tries -lt 60 ]; do
    body=$(curl -sf "${V1}/plan-sessions/${SESSION}" "${AUTH[@]}")
    status=$(echo "$body" | jq -r '.status')
    case "$status" in
      "$want") echo "$body"; return 0 ;;
      failed)  fail "session failed: $(echo "$body" | jq -r '.error')" ;;
    esac
    tries=$((tries + 1)); sleep 1
  done
  fail "session never reached ${want} (last status: ${status})"
}

say "wait for follow-up questions"
BODY=$(poll_session questioning)
ANSWERS=$(echo "$BODY" | jq -c '{answers: [.questions[] | {question_id: .id, choice: .options[0]}]}')

say "submit answers"
curl -sf -X POST "${V1}/plan-sessions/${SESSION}/answers" "${AUTH[@]}" \
  -H 'content-type: application/json' -d "$ANSWERS" >/dev/null

say "wait for the three plans"
BODY=$(poll_session done)
echo "$BODY" | jq -r '.plans[] | "  \(.difficulty)\t\(.duration_weeks)w\t\(.title)"'
[ "$(echo "$BODY" | jq '.plans | length')" -eq 3 ] || fail "expected three plans"
PLAN=$(echo "$BODY" | jq -r '.plans[] | select(.difficulty == "hard") | .id')

say "activate the hard plan"
curl -sf -X PATCH "${V1}/plans/${PLAN}" "${AUTH[@]}" \
  -H 'content-type: application/json' -d '{"status": "active"}' >/dev/null

say "list tasks"
TASKS=$(curl -sf "${V1}/plans/${PLAN}/tasks" "${AUTH[@]}")
COUNT=$(echo "$TASKS" | jq '.items | length')
[ "$COUNT" -gt 0 ] || fail "plan has no tasks"
echo "  ${COUNT} tasks"
TASK=$(echo "$TASKS" | jqr '.items[0].id')

say "mark one task done"
curl -sf -X PATCH "${V1}/plans/${PLAN}/tasks/${TASK}" "${AUTH[@]}" \
  -H 'content-type: application/json' -d '{"status": "done"}' \
  | jqr '.status' >/dev/null

say "export markdown"
curl -sf -X POST "${V1}/plans/${PLAN}/export" "${AUTH[@]}" \
  -H 'content-type: application/json' -d '{"target": "markdown"}' \
  | jqr '.markdown.content' | head -20

printf '\nsmoke OK  session=%s plan=%s\n' "$SESSION" "$PLAN"
