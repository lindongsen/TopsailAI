#!/usr/bin/env bash
# =============================================================================
# ACS Manual API Test Script (Bash/curl)
# =============================================================================
# Executes manual API tests against a running ACS server using curl.
# Usage: ./manual_api_test.sh [API_BASE_URL]
# Default API_BASE_URL: http://127.0.0.1:7370
# =============================================================================

set -euo pipefail

API_BASE="${1:-${ACS_API_BASE:-http://127.0.0.1:7370}}"
TOTAL=0
PASSED=0
FAILED=0
SKIPPED=0

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_pass() { PASSED=$((PASSED + 1)); echo -e "${GREEN}[PASS]${NC} $1"; }
log_fail() { FAILED=$((FAILED + 1)); echo -e "${RED}[FAIL]${NC} $1"; if [ -n "${2:-}" ]; then echo -e "       Detail: $2"; fi; }
log_skip() { SKIPPED=$((SKIPPED + 1)); echo -e "${YELLOW}[SKIP]${NC} $1"; }

# Global state
GROUP_ID=""
MESSAGE_ID=""

# ---------------------------------------------------------------------------
# Helper: run_test <test_id> <test_name> <expected_status> <method> <path> [body]
# ---------------------------------------------------------------------------
run_test() {
    local test_id="$1" test_name="$2" expected_status="$3" method="$4" path="$5"
    local body="${6:-}"
    local url="${API_BASE}${path}"
    local http_code body_text

    TOTAL=$((TOTAL + 1))
    echo ""
    echo "=== $test_id: $test_name ==="

    if [ -n "$body" ]; then
        http_code=$(curl -s -o /tmp/acs_manual_resp.json -w "%{http_code}" \
            -X "$method" \
            -H "Content-Type: application/json" \
            -d "$body" \
            "$url" 2>/dev/null || echo "000")
    else
        http_code=$(curl -s -o /tmp/acs_manual_resp.json -w "%{http_code}" \
            -X "$method" \
            -H "Content-Type: application/json" \
            "$url" 2>/dev/null || echo "000")
    fi

    body_text=$(cat /tmp/acs_manual_resp.json 2>/dev/null || echo "")

    if [ "$http_code" = "$expected_status" ]; then
        log_pass "$test_id: $test_name (HTTP $http_code)"
        return 0
    else
        log_fail "$test_id: $test_name" "HTTP $http_code (expected $expected_status), body: ${body_text:0:300}"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Helper: run_test_body_check <test_id> <test_name> <expected_status> <body_check> <method> <path> [body]
# ---------------------------------------------------------------------------
run_test_body_check() {
    local test_id="$1" test_name="$2" expected_status="$3" body_check="$4" method="$5" path="$6"
    local body="${7:-}"
    local url="${API_BASE}${path}"
    local http_code body_text

    TOTAL=$((TOTAL + 1))
    echo ""
    echo "=== $test_id: $test_name ==="

    if [ -n "$body" ]; then
        http_code=$(curl -s -o /tmp/acs_manual_resp.json -w "%{http_code}" \
            -X "$method" \
            -H "Content-Type: application/json" \
            -d "$body" \
            "$url" 2>/dev/null || echo "000")
    else
        http_code=$(curl -s -o /tmp/acs_manual_resp.json -w "%{http_code}" \
            -X "$method" \
            -H "Content-Type: application/json" \
            "$url" 2>/dev/null || echo "000")
    fi

    body_text=$(cat /tmp/acs_manual_resp.json 2>/dev/null || echo "")

    if [ "$http_code" != "$expected_status" ]; then
        log_fail "$test_id: $test_name" "HTTP $http_code (expected $expected_status), body: ${body_text:0:300}"
        return 1
    fi

    if echo "$body_text" | grep -q "$body_check"; then
        log_pass "$test_id: $test_name (HTTP $http_code, contains '$body_check')"
        return 0
    else
        log_fail "$test_id: $test_name" "HTTP $http_code, but body missing '$body_check': ${body_text:0:300}"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo "============================================================================="
echo "  ACS Manual API Test Script (Bash/curl)"
echo "  Target: $API_BASE"
echo "  Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "============================================================================="

# =====================================================================
# Phase A: Health & Readiness
# =====================================================================
echo ""
echo "============================================================================="
echo "  PHASE A: Health & Readiness"
echo "============================================================================="

run_test "MANUAL-API-001" "Liveness Probe" 200 "GET" "/healthz"
run_test_body_check "MANUAL-API-002" "Readiness Probe" 200 "ready" "GET" "/readyz"
run_test_body_check "MANUAL-API-003" "Comprehensive Health" 200 "healthy" "GET" "/health"

# =====================================================================
# Phase B: Group CRUD
# =====================================================================
echo ""
echo "============================================================================="
echo "  PHASE B: Group CRUD"
echo "============================================================================="

# B-004: Create Group
run_test "MANUAL-API-004" "Create Group" 201 "POST" "/api/v1/groups" \
    '{"group_name":"Manual Test Group (Bash)","group_context":"Created via manual API test bash script"}'

if [ -f /tmp/acs_manual_resp.json ]; then
    GROUP_ID=$(cat /tmp/acs_manual_resp.json | grep -o '"group_id":"[^"]*"' | cut -d'"' -f4 || true)
    if [ -n "$GROUP_ID" ]; then
        log_info "Created group: $GROUP_ID"
    fi
fi

if [ -z "$GROUP_ID" ]; then
    log_fail "MANUAL-API-004" "Cannot proceed without group_id"
    echo ""
    echo "============================================================================="
    echo "  TEST EXECUTION SUMMARY (ABORTED)"
    echo "============================================================================="
    echo "  Total Tests:  $TOTAL"
    echo -e "  ${GREEN}Passed:${NC}       $PASSED"
    echo -e "  ${RED}Failed:${NC}       $FAILED"
    echo -e "  ${YELLOW}Skipped:${NC}      $SKIPPED"
    exit 1
fi

# B-005: Create Group with Secret Key
run_test "MANUAL-API-005" "Create Group with Secret Key" 201 "POST" "/api/v1/groups" \
    '{"group_name":"Secret Group","group_context":"Private","group_key":"my-secret-key"}'

# B-006: Invalid Input - Empty Name
run_test "MANUAL-API-006" "Create Group - Empty Name (Invalid)" 400 "POST" "/api/v1/groups" \
    '{"group_name":"","group_context":"test"}'

# B-007: Invalid Input - Missing Required Field
run_test "MANUAL-API-007" "Create Group - Missing Name (Invalid)" 400 "POST" "/api/v1/groups" \
    '{"group_context":"test"}'

# B-008: Get Group
run_test_body_check "MANUAL-API-008" "Get Group" 200 "$GROUP_ID" "GET" "/api/v1/groups/$GROUP_ID"

# B-009: Get Group - Not Found
run_test "MANUAL-API-009" "Get Group - Not Found" 404 "GET" "/api/v1/groups/non-existent-id"

# B-010: List Groups
run_test_body_check "MANUAL-API-010" "List Groups" 200 "items" "GET" "/api/v1/groups"

# B-011: List Groups with Pagination
run_test_body_check "MANUAL-API-011" "List Groups with Pagination" 200 "items" "GET" "/api/v1/groups?offset=0&limit=2"

# B-012: List Groups with Sorting
run_test_body_check "MANUAL-API-012" "List Groups with Sorting" 200 "items" "GET" "/api/v1/groups?sort_key=create_at_ms&order_by=asc"

# B-013: Update Group
run_test_body_check "MANUAL-API-013" "Update Group" 200 "Updated Manual Group" "PUT" "/api/v1/groups/$GROUP_ID" \
    '{"group_name":"Updated Manual Group","group_context":"Updated context"}'

# B-014: Partial Update
run_test_body_check "MANUAL-API-014" "Partial Update Group" 200 "Partially Updated" "PUT" "/api/v1/groups/$GROUP_ID" \
    '{"group_name":"Partially Updated"}'

# =====================================================================
# Phase C: Member Management
# =====================================================================
echo ""
echo "============================================================================="
echo "  PHASE C: Member Management"
echo "============================================================================="

# C-017: Join as User
run_test "MANUAL-API-017" "Join Group as User" 201 "POST" "/api/v1/groups/$GROUP_ID/members" \
    '{"member_id":"manual-user-001","member_name":"Manual Tester","member_description":"A human tester","member_type":"user"}'

# C-018: Join as Worker-Agent
run_test "MANUAL-API-018" "Join Group as Worker-Agent" 201 "POST" "/api/v1/groups/$GROUP_ID/members" \
    '{"member_id":"manual-agent-001","member_name":"Test Worker Agent","member_description":"A test worker agent","member_type":"worker-agent","member_interface":"{\"adaptor\":\"topsailai_agent\",\"environments\":{\"ACS_AGENT_API_BASE\":\"http://127.0.0.1:7373\",\"ACS_AGENT_API_KEY\":\"test-key\"},\"timeout_chat\":30}"}'

# C-019: Join as Manager-Agent
run_test "MANUAL-API-019" "Join Group as Manager-Agent" 201 "POST" "/api/v1/groups/$GROUP_ID/members" \
    '{"member_id":"manual-manager-001","member_name":"Test Manager","member_description":"Group coordinator","member_type":"manager-agent","member_interface":"{\"adaptor\":\"topsailai_agent\",\"environments\":{\"ACS_AGENT_API_BASE\":\"http://127.0.0.1:7373\",\"ACS_AGENT_API_KEY\":\"test-key\"},\"timeout_chat\":30}"}'

# C-020: Duplicate Member
run_test "MANUAL-API-020" "Join Group - Duplicate Member" 409 "POST" "/api/v1/groups/$GROUP_ID/members" \
    '{"member_id":"manual-user-001","member_name":"Duplicate","member_type":"user"}'

# C-021: Invalid Member Type
run_test "MANUAL-API-021" "Join Group - Invalid Member Type" 400 "POST" "/api/v1/groups/$GROUP_ID/members" \
    '{"member_id":"bad-type-user","member_name":"Bad","member_type":"invalid-type"}'

# C-022: List Members
run_test_body_check "MANUAL-API-022" "List Group Members" 200 "manual-user-001" "GET" "/api/v1/groups/$GROUP_ID/members"

# C-023: Update Member
run_test_body_check "MANUAL-API-023" "Update Member Status" 200 "Updated Tester" "PUT" "/api/v1/groups/$GROUP_ID/members/manual-user-001" \
    '{"member_name":"Updated Tester","member_status":"idle"}'

# =====================================================================
# Phase D: Message Operations
# =====================================================================
echo ""
echo "============================================================================="
echo "  PHASE D: Message Operations"
echo "============================================================================="

# D-026: Create Message
run_test "MANUAL-API-026" "Create Message (Plain Text)" 201 "POST" "/api/v1/groups/$GROUP_ID/messages" \
    '{"message_text":"Hello from manual API test!","sender_id":"manual-user-001","sender_type":"user"}'

if [ -f /tmp/acs_manual_resp.json ]; then
    MESSAGE_ID=$(cat /tmp/acs_manual_resp.json | grep -o '"message_id":"[^"]*"' | cut -d'"' -f4 || true)
    if [ -n "$MESSAGE_ID" ]; then
        log_info "Created message: $MESSAGE_ID"
    fi
fi

# D-027: Create Message with Attachments
run_test "MANUAL-API-027" "Create Message with Attachments" 201 "POST" "/api/v1/groups/$GROUP_ID/messages" \
    '{"message_text":"See this image","message_attachments":"[{\"data\":\"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==\",\"size\":67,\"format\":\"image/png\"}]","sender_id":"manual-user-001","sender_type":"user"}'

# D-028: Create Message with Mention
run_test_body_check "MANUAL-API-028" "Create Message with Mention" 201 "mentions" "POST" "/api/v1/groups/$GROUP_ID/messages" \
    '{"message_text":"Hello @manual-agent-001, can you help?","sender_id":"manual-user-001","sender_type":"user"}'

# D-029: Create Message with @all
run_test_body_check "MANUAL-API-029" "Create Message with @all" 201 "mentions" "POST" "/api/v1/groups/$GROUP_ID/messages" \
    '{"message_text":"@all Please review this document","sender_id":"manual-user-001","sender_type":"user"}'

# D-030: Invalid Sender
run_test "MANUAL-API-030" "Create Message - Invalid Sender" 400 "POST" "/api/v1/groups/$GROUP_ID/messages" \
    '{"message_text":"Unauthorized","sender_id":"not-a-member","sender_type":"user"}'

# D-031: Missing Required Fields
run_test "MANUAL-API-031" "Create Message - Missing Required Fields" 400 "POST" "/api/v1/groups/$GROUP_ID/messages" \
    '{"sender_id":"manual-user-001","sender_type":"user"}'

# D-032: List Messages
run_test_body_check "MANUAL-API-032" "List Messages" 200 "items" "GET" "/api/v1/groups/$GROUP_ID/messages"

# D-033: List Messages with Pagination
run_test_body_check "MANUAL-API-033" "List Messages with Pagination" 200 "items" "GET" "/api/v1/groups/$GROUP_ID/messages?offset=0&limit=2"

# D-034: List Messages with Time Range
NOW_MS=$(date +%s%3N)
START_MS=$((NOW_MS - 600000))
END_MS=$((NOW_MS + 600000))
run_test_body_check "MANUAL-API-034" "List Messages with Time Range" 200 "items" "GET" "/api/v1/groups/$GROUP_ID/messages?create_at_ms=$START_MS-$END_MS"

# D-035: List Messages with Sorting
run_test_body_check "MANUAL-API-035" "List Messages with Sorting" 200 "items" "GET" "/api/v1/groups/$GROUP_ID/messages?sort_key=create_at_ms&order_by=asc"

# D-036: Update Message
if [ -n "$MESSAGE_ID" ]; then
    run_test_body_check "MANUAL-API-036" "Update Message" 200 "edited" "PUT" "/api/v1/groups/$GROUP_ID/messages/$MESSAGE_ID" \
        '{"message_text":"This message has been edited"}'
else
    log_skip "MANUAL-API-036: Update Message - no message ID available"
fi

# D-037: Delete Message
if [ -n "$MESSAGE_ID" ]; then
    run_test "MANUAL-API-037" "Delete Message" 204 "DELETE" "/api/v1/groups/$GROUP_ID/messages/$MESSAGE_ID"
else
    log_skip "MANUAL-API-037: Delete Message - no message ID available"
fi

# D-038: Delete Message - Not Found
run_test "MANUAL-API-038" "Delete Message - Not Found" 404 "DELETE" "/api/v1/groups/$GROUP_ID/messages/non-existent-msg"

# =====================================================================
# Phase E: Edge Cases & Error Handling
# =====================================================================
echo ""
echo "============================================================================="
echo "  PHASE E: Edge Cases & Error Handling"
echo "============================================================================="

# E-043: Invalid JSON
run_test "MANUAL-API-043" "Invalid JSON Body" 400 "POST" "/api/v1/groups" "{invalid json"

# E-044: Method Not Allowed (PATCH)
run_test "MANUAL-API-044" "Method Not Allowed (PATCH)" 404 "PATCH" "/api/v1/groups/$GROUP_ID" '{"group_name":"test"}'

# E-045: Not Found Route
run_test "MANUAL-API-045" "Not Found Route" 404 "GET" "/api/v1/non-existent-endpoint"

# E-046: Trace ID Auto-Generated
TOTAL=$((TOTAL + 1))
echo ""
echo "=== MANUAL-API-046: Trace ID - Auto-Generated ==="
TRACE_ID=$(curl -s -I -X GET "${API_BASE}/api/v1/groups/$GROUP_ID" 2>/dev/null | grep -i "X-Trace-ID" | awk '{print $2}' | tr -d '\r')
if [ -n "$TRACE_ID" ] && [ ${#TRACE_ID} -gt 10 ]; then
    log_pass "MANUAL-API-046: Trace ID auto-generated in header: ${TRACE_ID:0:20}..."
else
    log_fail "MANUAL-API-046: Trace ID not found in response header" "header=$TRACE_ID"
fi

# E-047: Trace ID Preserved
TOTAL=$((TOTAL + 1))
echo ""
echo "=== MANUAL-API-047: Trace ID - Preserved from Request ==="
CUSTOM_TRACE="manual-test-trace-$(openssl rand -hex 4)"
RETURNED_TRACE=$(curl -s -I -X GET -H "X-Trace-ID: $CUSTOM_TRACE" "${API_BASE}/api/v1/groups/$GROUP_ID" 2>/dev/null | grep -i "X-Trace-ID" | awk '{print $2}' | tr -d '\r')
if [ "$RETURNED_TRACE" = "$CUSTOM_TRACE" ]; then
    log_pass "MANUAL-API-047: Custom trace ID preserved: $CUSTOM_TRACE"
else
    log_fail "MANUAL-API-047: Custom trace ID not preserved" "sent=$CUSTOM_TRACE, returned=$RETURNED_TRACE"
fi

# E-048: Very Long Message
TOTAL=$((TOTAL + 1))
echo ""
echo "=== MANUAL-API-048: Very Long Message Text ==="
LONG_TEXT=$(python3 -c "print('A'*5000)")
HTTP_CODE=$(curl -s -o /tmp/acs_manual_resp.json -w "%{http_code}" \
    -X POST -H "Content-Type: application/json" \
    -d "{\"message_text\":\"$LONG_TEXT\",\"sender_id\":\"manual-user-001\",\"sender_type\":\"user\"}" \
    "${API_BASE}/api/v1/groups/$GROUP_ID/messages" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "201" ] && grep -q "message_id" /tmp/acs_manual_resp.json 2>/dev/null; then
    log_pass "MANUAL-API-048: Long message stored successfully"
else
    log_fail "MANUAL-API-048: Long message failed" "HTTP $HTTP_CODE"
fi

# E-049: Unicode Characters
TOTAL=$((TOTAL + 1))
echo ""
echo "=== MANUAL-API-049: Unicode and Multi-byte Characters ==="
HTTP_CODE=$(curl -s -o /tmp/acs_manual_resp.json -w "%{http_code}" \
    -X POST -H "Content-Type: application/json" \
    -d '{"message_text":"你好世界 🎉 ñoño émojis: 🔥🚀💡","sender_id":"manual-user-001","sender_type":"user"}' \
    "${API_BASE}/api/v1/groups/$GROUP_ID/messages" 2>/dev/null || echo "000")
BODY=$(cat /tmp/acs_manual_resp.json 2>/dev/null || echo "")
if [ "$HTTP_CODE" = "201" ] && echo "$BODY" | grep -q "你好世界"; then
    log_pass "MANUAL-API-049: Unicode characters preserved"
else
    log_fail "MANUAL-API-049: Unicode characters not preserved" "HTTP $HTTP_CODE"
fi

# E-050: Empty Message Text
run_test "MANUAL-API-050" "Empty Message Text" 400 "POST" "/api/v1/groups/$GROUP_ID/messages" \
    '{"message_text":"","sender_id":"manual-user-001","sender_type":"user"}'

# =====================================================================
# Phase F: Concurrent Scenarios
# =====================================================================
echo ""
echo "============================================================================="
echo "  PHASE F: Concurrent Scenarios"
echo "============================================================================="

# F-051: Rapid Message Creation
TOTAL=$((TOTAL + 1))
echo ""
echo "=== MANUAL-API-051: Rapid Message Creation ==="
BEFORE=$(curl -s "${API_BASE}/api/v1/groups/$GROUP_ID/messages" 2>/dev/null | grep -o '"total":[0-9]*' | head -1 | cut -d':' -f2 || echo "0")
for i in $(seq 1 10); do
    curl -s -o /dev/null -X POST -H "Content-Type: application/json" \
        -d "{\"message_text\":\"Rapid message $i\",\"sender_id\":\"manual-user-001\",\"sender_type\":\"user\"}" \
        "${API_BASE}/api/v1/groups/$GROUP_ID/messages" 2>/dev/null &
done
wait
sleep 1
AFTER=$(curl -s "${API_BASE}/api/v1/groups/$GROUP_ID/messages" 2>/dev/null | grep -o '"total":[0-9]*' | head -1 | cut -d':' -f2 || echo "0")
if [ "$AFTER" -ge "$((BEFORE + 10))" ]; then
    log_pass "MANUAL-API-051: All rapid messages stored (before: $BEFORE, after: $AFTER)"
else
    log_fail "MANUAL-API-051: Missing rapid messages" "before=$BEFORE, after=$AFTER, expected=$((BEFORE + 10))"
fi

# F-052: Concurrent Member Joins
TOTAL=$((TOTAL + 1))
echo ""
echo "=== MANUAL-API-052: Concurrent Member Joins ==="
BEFORE_M=$(curl -s "${API_BASE}/api/v1/groups/$GROUP_ID/members" 2>/dev/null | grep -o '"total":[0-9]*' | head -1 | cut -d':' -f2 || echo "0")
for i in $(seq 1 5); do
    curl -s -o /dev/null -X POST -H "Content-Type: application/json" \
        -d "{\"member_id\":\"concurrent-user-$i\",\"member_name\":\"User $i\",\"member_type\":\"user\"}" \
        "${API_BASE}/api/v1/groups/$GROUP_ID/members" 2>/dev/null &
done
wait
sleep 1
AFTER_M=$(curl -s "${API_BASE}/api/v1/groups/$GROUP_ID/members" 2>/dev/null | grep -o '"total":[0-9]*' | head -1 | cut -d':' -f2 || echo "0")
if [ "$AFTER_M" -ge "$((BEFORE_M + 5))" ]; then
    log_pass "MANUAL-API-052: All concurrent members joined (before: $BEFORE_M, after: $AFTER_M)"
else
    log_fail "MANUAL-API-052: Missing concurrent members" "before=$BEFORE_M, after=$AFTER_M, expected=$((BEFORE_M + 5))"
fi

# =====================================================================
# Phase G: Cleanup
# =====================================================================
echo ""
echo "============================================================================="
echo "  PHASE G: Cleanup"
echo "============================================================================="

# G-053: Delete Group
TOTAL=$((TOTAL + 1))
echo ""
echo "=== MANUAL-API-053: Delete Group with Members and Messages ==="
DEL_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "${API_BASE}/api/v1/groups/$GROUP_ID" 2>/dev/null || echo "000")
VERIFY_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X GET "${API_BASE}/api/v1/groups/$GROUP_ID" 2>/dev/null || echo "000")
if [ "$DEL_CODE" = "204" ] && [ "$VERIFY_CODE" = "404" ]; then
    log_pass "MANUAL-API-053: Group deleted and verified gone (HTTP $DEL_CODE -> $VERIFY_CODE)"
else
    log_fail "MANUAL-API-053: Group delete failed" "DELETE=$DEL_CODE, GET=$VERIFY_CODE"
fi

# G-025: Leave Group - Not Found
run_test "MANUAL-API-025" "Leave Group - Not Found" 404 "DELETE" "/api/v1/groups/$GROUP_ID/members/non-existent-member"

# G-016: Delete Group - Not Found
run_test "MANUAL-API-016" "Delete Group - Not Found" 404 "DELETE" "/api/v1/groups/non-existent-id"

# =====================================================================
# Summary
# =====================================================================
echo ""
echo "============================================================================="
echo "  TEST EXECUTION SUMMARY"
echo "============================================================================="
echo "  Total Tests:  $TOTAL"
echo -e "  ${GREEN}Passed:${NC}       $PASSED"
echo -e "  ${RED}Failed:${NC}       $FAILED"
echo -e "  ${YELLOW}Skipped:${NC}      $SKIPPED"
echo ""
if [ $FAILED -eq 0 ]; then
    echo -e "  ${GREEN}ALL TESTS PASSED ✅${NC}"
    exit 0
else
    echo -e "  ${RED}SOME TESTS FAILED ❌${NC}"
    exit 1
fi
