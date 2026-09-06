#!/usr/bin/env bash
# End-to-end smoke test against a running stack.
#
#   API_BASE=http://127.0.0.1:8000 bash scripts/smoke.sh
#
# Walks the whole loop: sign in, upload a calendar, let the Analyzer read it, score
# the shapes, answer the three questions, settle on a hypothesis, wait for the plan,
# tick a task off, and open the quarterly review. Exits non-zero on the first surprise.
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8000}"
V1="${API_BASE}/v1"
EMAIL="${SMOKE_EMAIL:-smoke-$(date +%s)@example.com}"
# Seconds to wait for any one queued step. A real provider scoring six shapes with five
# cited evidence items each is a large generation; the fixtures answer instantly.
POLL_SECONDS="${SMOKE_POLL_SECONDS:-300}"

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

say "upload a calendar"
ICS=$(mktemp); trap 'rm -f "$ICS"' EXIT
cat > "$ICS" <<'ICSBODY'
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//guru//smoke//EN
BEGIN:VEVENT
UID:smoke-1
DTSTART:20260105T090000Z
DTEND:20260105T100000Z
SUMMARY:Design review
END:VEVENT
BEGIN:VEVENT
UID:smoke-2
DTSTART:20260112T190000Z
DTEND:20260112T210000Z
SUMMARY:Reading group
END:VEVENT
END:VCALENDAR
ICSBODY
SIZE=$(wc -c < "$ICS" | tr -d ' ')
PRESIGN=$(curl -sf -X POST "${V1}/imports/presign" "${AUTH[@]}" \
  -H 'content-type: application/json' \
  -d "{\"filename\": \"smoke.ics\", \"content_type\": \"text/calendar\", \"size_bytes\": ${SIZE}}")
IMPORT=$(echo "$PRESIGN" | jqr '.import_id')
curl -sf -X PUT "$(echo "$PRESIGN" | jqr '.upload_url')" \
  -H 'content-type: text/calendar' --data-binary "@${ICS}" >/dev/null
curl -sf -X POST "${V1}/imports/${IMPORT}/complete" "${AUTH[@]}" >/dev/null

poll() {  # poll <url> <jq path> <wanted> <failed>
  local tries=0 body value
  while [ $tries -lt "$POLL_SECONDS" ]; do
    body=$(curl -sf "$1" "${AUTH[@]}" || true)
    value=$(echo "$body" | jq -r "$2" 2>/dev/null || echo "")
    [ "$value" = "$3" ] && { echo "$body"; return 0; }
    [ "$value" = "$4" ] && fail "$1 reported ${4}: $(echo "$body" | jq -r '.error')"
    tries=$((tries + 1)); sleep 1
  done
  fail "$1 never reached ${3} after ${POLL_SECONDS}s (last: ${value})"
}

say "wait for the parse and the profile"
poll "${V1}/imports" '.[0].status' parsed failed >/dev/null
poll "${V1}/profile" '.coverage.events' 2 '' >/dev/null

say "read the data and score every shape"
RUN=$(curl -sf -X POST "${V1}/direction/runs" "${AUTH[@]}" | jqr '.id')
BODY=$(poll "${V1}/direction/runs/${RUN}" '.status' ready failed)
echo "$BODY" | jq -r '.reports[] | "  report \(.dimension)"'
echo "$BODY" | jq -r '.verdicts[] | "  \(.role_model_code)\t\(.fit)\t\(.verdict)"'
[ "$(echo "$BODY" | jq '.verdicts | length')" -ge 6 ] || fail "expected every shape to be scored"
[ "$(echo "$BODY" | jq -c '[.verdicts[].evidence | length] | unique')" = "[5]" ] \
  || fail "every verdict must carry exactly five evidence items"

say "answer the three questions"
for pair in 'q1:No more managing a team.' 'q2:I stopped running after six weeks.' 'q3:career'; do
  curl -sf -X PUT "${V1}/questions/${pair%%:*}" "${AUTH[@]}" \
    -H 'content-type: application/json' \
    -d "$(jq -nc --arg a "${pair#*:}" '{answer: $a}')" >/dev/null
done
curl -sf "${V1}/quota" "${AUTH[@]}" | jqr '.drop_first'

say "settle on a hypothesis"
VERDICT=$(echo "$BODY" | jqr '.verdicts[0].id')
HYPOTHESIS=$(curl -sf -X POST "${V1}/hypotheses" "${AUTH[@]}" \
  -H 'content-type: application/json' -d "{\"fit_verdict_id\": \"${VERDICT}\"}")
PLAN=$(echo "$HYPOTHESIS" | jqr '.plan_id')
echo "  v$(echo "$HYPOTHESIS" | jq -r '.version') reviewed on $(echo "$HYPOTHESIS" | jq -r '.review_date')"

say "wait for the plan"
BODY=$(poll "${V1}/plans/${PLAN}" '.status' draft failed)
echo "$BODY" | jq -r '.milestones[] | "  milestone \(.key): \(.title)"'
echo "$BODY" | jq -r '.structure.assumptions[]? | "  assumes: \(.)"'

say "activate it and tick one task off"
curl -sf -X PUT "${V1}/plans/${PLAN}/status" "${AUTH[@]}" \
  -H 'content-type: application/json' -d '{"status": "active"}' >/dev/null
TASKS=$(curl -sf "${V1}/plans/${PLAN}/tasks" "${AUTH[@]}")
COUNT=$(echo "$TASKS" | jq 'length')
[ "$COUNT" -gt 0 ] || fail "plan has no tasks"
echo "  ${COUNT} tasks"
TASK=$(echo "$TASKS" | jqr '.[0].id')
curl -sf -X PUT "${V1}/plans/${PLAN}/tasks/${TASK}/status" "${AUTH[@]}" \
  -H 'content-type: application/json' -d '{"status": "done"}' | jqr '.status' >/dev/null

say "open the quarterly review"
REVIEW=$(curl -sf -X POST "${V1}/reconciliations" "${AUTH[@]}" \
  -H 'content-type: application/json' \
  -d "{\"hypothesis_id\": \"$(echo "$HYPOTHESIS" | jqr '.id')\"}" | jqr '.id')
BODY=$(poll "${V1}/reconciliations/${REVIEW}" '.status' done failed)
echo "$BODY" | jq -r '.narrative'
[ "$(echo "$BODY" | jq -r '.outcome')" = "null" ] || fail "the review must not decide for the user"

printf '\nsmoke OK  plan=%s review=%s\n' "$PLAN" "$REVIEW"
