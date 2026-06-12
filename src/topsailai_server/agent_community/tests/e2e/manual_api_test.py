#!/usr/bin/env python3
# =============================================================================
# ACS Manual API Test Script (Python/requests)
# =============================================================================
# Executes manual API tests against a running ACS server.
# Usage: python3 manual_api_test.py [API_BASE_URL]
# Default API_BASE_URL: http://127.0.0.1:7370
# =============================================================================

import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

# Configuration
API_BASE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ACS_API_BASE", "http://127.0.0.1:7370")
REQUEST_TIMEOUT = 30

# Test counters
TOTAL = 0
PASSED = 0
FAILED = 0
SKIPPED = 0

# Test state
group_id = None
message_id = None

# Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def log_info(msg: str):
    print(f"{BLUE}[INFO]{RESET} {msg}")


def log_pass(test_id: str, msg: str):
    global PASSED
    PASSED += 1
    print(f"{GREEN}[PASS]{RESET} {test_id}: {msg}")


def log_fail(test_id: str, msg: str, detail: str = ""):
    global FAILED
    FAILED += 1
    print(f"{RED}[FAIL]{RESET} {test_id}: {msg}")
    if detail:
        print(f"       Detail: {detail[:400]}")


def log_skip(test_id: str, msg: str):
    global SKIPPED
    SKIPPED += 1
    print(f"{YELLOW}[SKIP]{RESET} {test_id}: {msg}")


def run_test(test_id: str, test_name: str, expected_status: int, method: str, path: str, **kwargs) -> requests.Response | None:
    global TOTAL
    TOTAL += 1
    print(f"\n=== {test_id}: {test_name} ===")

    url = f"{API_BASE}{path}"
    try:
        resp = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.RequestException as e:
        log_fail(test_id, test_name, f"Connection error: {e}")
        return None

    if resp.status_code == expected_status:
        log_pass(test_id, f"{test_name} (HTTP {resp.status_code})")
        return resp
    else:
        log_fail(test_id, f"{test_name}", f"HTTP {resp.status_code} (expected {expected_status}), body: {resp.text[:300]}")
        return None


def run_test_body_check(test_id: str, test_name: str, expected_status: int, body_check: str, method: str, path: str, **kwargs) -> requests.Response | None:
    global TOTAL
    TOTAL += 1
    print(f"\n=== {test_id}: {test_name} ===")

    url = f"{API_BASE}{path}"
    try:
        resp = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.RequestException as e:
        log_fail(test_id, test_name, f"Connection error: {e}")
        return None

    if resp.status_code != expected_status:
        log_fail(test_id, f"{test_name}", f"HTTP {resp.status_code} (expected {expected_status}), body: {resp.text[:300]}")
        return None

    body = resp.text
    if body_check in body:
        log_pass(test_id, f"{test_name} (HTTP {resp.status_code}, contains '{body_check}')")
        return resp
    else:
        log_fail(test_id, f"{test_name}", f"HTTP {resp.status_code}, but body missing '{body_check}': {body[:300]}")
        return None


def print_banner():
    print("=" * 77)
    print("  ACS Manual API Test Script (Python)")
    print(f"  Target: {API_BASE}")
    print(f"  Date: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 77)


def print_summary():
    print("\n" + "=" * 77)
    print("  TEST EXECUTION SUMMARY")
    print("=" * 77)
    print(f"  Total Tests:  {TOTAL}")
    print(f"  {GREEN}Passed:{RESET}       {PASSED}")
    print(f"  {RED}Failed:{RESET}       {FAILED}")
    print(f"  {YELLOW}Skipped:{RESET}      {SKIPPED}")
    print("")
    if FAILED == 0:
        print(f"  {GREEN}ALL TESTS PASSED ✅{RESET}")
    else:
        print(f"  {RED}SOME TESTS FAILED ❌{RESET}")


def main():
    global TOTAL, PASSED, FAILED, SKIPPED, group_id, message_id

    print_banner()
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})

    # =====================================================================
    # Phase A: Health & Readiness
    # =====================================================================
    print("\n" + "=" * 77)
    print("  PHASE A: Health & Readiness")
    print("=" * 77)

    run_test("MANUAL-API-001", "Liveness Probe", 200, "GET", "/healthz")
    run_test_body_check("MANUAL-API-002", "Readiness Probe", 200, "ready", "GET", "/readyz")
    run_test_body_check("MANUAL-API-003", "Comprehensive Health", 200, "healthy", "GET", "/health")

    # =====================================================================
    # Phase B: Group CRUD
    # =====================================================================
    print("\n" + "=" * 77)
    print("  PHASE B: Group CRUD")
    print("=" * 77)

    # B-004: Create Group
    resp = run_test(
        "MANUAL-API-004", "Create Group", 201, "POST", "/api/v1/groups",
        json={"group_name": "Manual Test Group (Python)", "group_context": "Created via manual API test Python script"}
    )
    if resp:
        data = resp.json()
        group_id = data.get("group_id")
        log_info(f"Created group: {group_id}")
    else:
        log_fail("MANUAL-API-004", "Cannot proceed without group_id")
        print_summary()
        sys.exit(1)

    # B-005: Create Group with Secret Key
    run_test(
        "MANUAL-API-005", "Create Group with Secret Key", 201, "POST", "/api/v1/groups",
        json={"group_name": "Secret Group", "group_context": "Private", "group_key": "my-secret-key"}
    )

    # B-006: Invalid Input - Empty Name
    run_test(
        "MANUAL-API-006", "Create Group - Empty Name (Invalid)", 400, "POST", "/api/v1/groups",
        json={"group_name": "", "group_context": "test"}
    )

    # B-007: Invalid Input - Missing Required Field
    run_test(
        "MANUAL-API-007", "Create Group - Missing Name (Invalid)", 400, "POST", "/api/v1/groups",
        json={"group_context": "test"}
    )

    # B-008: Get Group
    run_test_body_check("MANUAL-API-008", "Get Group", 200, group_id, "GET", f"/api/v1/groups/{group_id}")

    # B-009: Get Group - Not Found
    run_test("MANUAL-API-009", "Get Group - Not Found", 404, "GET", "/api/v1/groups/non-existent-id")

    # B-010: List Groups
    run_test_body_check("MANUAL-API-010", "List Groups", 200, "items", "GET", "/api/v1/groups")

    # B-011: List Groups with Pagination
    run_test_body_check("MANUAL-API-011", "List Groups with Pagination", 200, "items", "GET", "/api/v1/groups?offset=0&limit=2")

    # B-012: List Groups with Sorting
    run_test_body_check("MANUAL-API-012", "List Groups with Sorting", 200, "items", "GET", "/api/v1/groups?sort_key=create_at_ms&order_by=asc")

    # B-013: Update Group
    run_test_body_check(
        "MANUAL-API-013", "Update Group", 200, "Updated Manual Group", "PUT", f"/api/v1/groups/{group_id}",
        json={"group_name": "Updated Manual Group", "group_context": "Updated context"}
    )

    # B-014: Partial Update
    run_test_body_check(
        "MANUAL-API-014", "Partial Update Group", 200, "Partially Updated", "PUT", f"/api/v1/groups/{group_id}",
        json={"group_name": "Partially Updated"}
    )

    # =====================================================================
    # Phase C: Member Management
    # =====================================================================
    print("\n" + "=" * 77)
    print("  PHASE C: Member Management")
    print("=" * 77)

    # C-017: Join as User
    run_test(
        "MANUAL-API-017", "Join Group as User", 201, "POST", f"/api/v1/groups/{group_id}/members",
        json={"member_id": "manual-user-001", "member_name": "Manual Tester", "member_description": "A human tester", "member_type": "user"}
    )

    # C-018: Join as Worker-Agent
    run_test(
        "MANUAL-API-018", "Join Group as Worker-Agent", 201, "POST", f"/api/v1/groups/{group_id}/members",
        json={
            "member_id": "manual-agent-001",
            "member_name": "Test Worker Agent",
            "member_description": "A test worker agent",
            "member_type": "worker-agent",
            "member_interface": json.dumps({
                "adaptor": "topsailai_agent",
                "environments": {"ACS_AGENT_API_BASE": "http://127.0.0.1:7373", "ACS_AGENT_API_KEY": "test-key"},
                "timeout_chat": 30
            })
        }
    )

    # C-019: Join as Manager-Agent
    run_test(
        "MANUAL-API-019", "Join Group as Manager-Agent", 201, "POST", f"/api/v1/groups/{group_id}/members",
        json={
            "member_id": "manual-manager-001",
            "member_name": "Test Manager",
            "member_description": "Group coordinator",
            "member_type": "manager-agent",
            "member_interface": json.dumps({
                "adaptor": "topsailai_agent",
                "environments": {"ACS_AGENT_API_BASE": "http://127.0.0.1:7373", "ACS_AGENT_API_KEY": "test-key"},
                "timeout_chat": 30
            })
        }
    )

    # C-020: Duplicate Member
    run_test(
        "MANUAL-API-020", "Join Group - Duplicate Member", 409, "POST", f"/api/v1/groups/{group_id}/members",
        json={"member_id": "manual-user-001", "member_name": "Duplicate", "member_type": "user"}
    )

    # C-021: Invalid Member Type
    run_test(
        "MANUAL-API-021", "Join Group - Invalid Member Type", 400, "POST", f"/api/v1/groups/{group_id}/members",
        json={"member_id": "bad-type-user", "member_name": "Bad", "member_type": "invalid-type"}
    )

    # C-022: List Members
    run_test_body_check("MANUAL-API-022", "List Group Members", 200, "manual-user-001", "GET", f"/api/v1/groups/{group_id}/members")

    # C-023: Update Member
    run_test_body_check(
        "MANUAL-API-023", "Update Member Status", 200, "Updated Tester", "PUT",
        f"/api/v1/groups/{group_id}/members/manual-user-001",
        json={"member_name": "Updated Tester", "member_status": "idle"}
    )

    # =====================================================================
    # Phase D: Message Operations
    # =====================================================================
    print("\n" + "=" * 77)
    print("  PHASE D: Message Operations")
    print("=" * 77)

    # D-026: Create Message
    resp = run_test(
        "MANUAL-API-026", "Create Message (Plain Text)", 201, "POST", f"/api/v1/groups/{group_id}/messages",
        json={"message_text": "Hello from manual API test!", "sender_id": "manual-user-001", "sender_type": "user"}
    )
    if resp:
        data = resp.json()
        message_id = data.get("message_id")
        log_info(f"Created message: {message_id}")

    # D-027: Create Message with Attachments
    # Note: message_attachments is expected as a JSON string, not an array
    run_test(
        "MANUAL-API-027", "Create Message with Attachments", 201, "POST", f"/api/v1/groups/{group_id}/messages",
        json={
            "message_text": "See this image",
            "message_attachments": json.dumps([{"data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "size": 67, "format": "image/png"}]),
            "sender_id": "manual-user-001", "sender_type": "user"
        }
    )

    # D-028: Create Message with Mention
    run_test_body_check(
        "MANUAL-API-028", "Create Message with Mention", 201, "mentions", "POST",
        f"/api/v1/groups/{group_id}/messages",
        json={"message_text": "Hello @manual-agent-001, can you help?", "sender_id": "manual-user-001", "sender_type": "user"}
    )

    # D-029: Create Message with @all
    run_test_body_check(
        "MANUAL-API-029", "Create Message with @all", 201, "mentions", "POST",
        f"/api/v1/groups/{group_id}/messages",
        json={"message_text": "@all Please review this document", "sender_id": "manual-user-001", "sender_type": "user"}
    )

    # D-030: Invalid Sender
    run_test(
        "MANUAL-API-030", "Create Message - Invalid Sender", 400, "POST", f"/api/v1/groups/{group_id}/messages",
        json={"message_text": "Unauthorized", "sender_id": "not-a-member", "sender_type": "user"}
    )

    # D-031: Missing Required Fields
    run_test(
        "MANUAL-API-031", "Create Message - Missing Required Fields", 400, "POST", f"/api/v1/groups/{group_id}/messages",
        json={"sender_id": "manual-user-001", "sender_type": "user"}
    )

    # D-032: List Messages
    run_test_body_check("MANUAL-API-032", "List Messages", 200, "items", "GET", f"/api/v1/groups/{group_id}/messages")

    # D-033: List Messages with Pagination
    run_test_body_check("MANUAL-API-033", "List Messages with Pagination", 200, "items", "GET", f"/api/v1/groups/{group_id}/messages?offset=0&limit=2")

    # D-034: List Messages with Time Range
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - 600000
    end_ms = now_ms + 600000
    run_test_body_check(
        "MANUAL-API-034", "List Messages with Time Range", 200, "items", "GET",
        f"/api/v1/groups/{group_id}/messages?create_at_ms={start_ms}-{end_ms}"
    )

    # D-035: List Messages with Sorting
    run_test_body_check("MANUAL-API-035", "List Messages with Sorting", 200, "items", "GET", f"/api/v1/groups/{group_id}/messages?sort_key=create_at_ms&order_by=asc")

    # D-036: Update Message
    if message_id:
        run_test_body_check(
            "MANUAL-API-036", "Update Message", 200, "edited", "PUT",
            f"/api/v1/groups/{group_id}/messages/{message_id}",
            json={"message_text": "This message has been edited"}
        )
    else:
        log_skip("MANUAL-API-036", "Update Message - no message ID available")

    # D-037: Delete Message
    if message_id:
        run_test("MANUAL-API-037", "Delete Message", 204, "DELETE", f"/api/v1/groups/{group_id}/messages/{message_id}")
    else:
        log_skip("MANUAL-API-037", "Delete Message - no message ID available")

    # D-038: Delete Message - Not Found
    run_test("MANUAL-API-038", "Delete Message - Not Found", 404, "DELETE", f"/api/v1/groups/{group_id}/messages/non-existent-msg")

    # =====================================================================
    # Phase E: Edge Cases & Error Handling
    # =====================================================================
    print("\n" + "=" * 77)
    print("  PHASE E: Edge Cases & Error Handling")
    print("=" * 77)

    # E-043: Invalid JSON
    run_test("MANUAL-API-043", "Invalid JSON Body", 400, "POST", "/api/v1/groups", data="{invalid json")

    # E-044: Method Not Allowed — router returns 404 for unregistered methods
    run_test("MANUAL-API-044", "Method Not Allowed (PATCH)", 404, "PATCH", f"/api/v1/groups/{group_id}", json={"group_name": "test"})

    # E-045: Not Found Route
    run_test("MANUAL-API-045", "Not Found Route", 404, "GET", "/api/v1/non-existent-endpoint")

    # E-046: Trace ID Auto-Generated — check response header
    TOTAL += 1
    print("\n=== MANUAL-API-046: Trace ID - Auto-Generated ===")
    resp = session.get(f"{API_BASE}/api/v1/groups/{group_id}", timeout=REQUEST_TIMEOUT)
    trace_id = resp.headers.get("X-Trace-ID", "")
    if resp.status_code == 200 and trace_id and len(trace_id) > 10:
        log_pass("MANUAL-API-046", f"Trace ID auto-generated in header: {trace_id[:20]}...")
    else:
        log_fail("MANUAL-API-046", "Trace ID not found in response header", f"status={resp.status_code}, headers={dict(resp.headers)}")

    # E-047: Trace ID Preserved — check response header echoes custom value
    TOTAL += 1
    print("\n=== MANUAL-API-047: Trace ID - Preserved from Request ===")
    custom_trace = f"manual-test-trace-{uuid.uuid4().hex[:8]}"
    resp = session.get(f"{API_BASE}/api/v1/groups/{group_id}", headers={"X-Trace-ID": custom_trace}, timeout=REQUEST_TIMEOUT)
    returned_trace = resp.headers.get("X-Trace-ID", "")
    if resp.status_code == 200 and returned_trace == custom_trace:
        log_pass("MANUAL-API-047", f"Custom trace ID preserved: {custom_trace}")
    else:
        log_fail("MANUAL-API-047", "Custom trace ID not preserved", f"sent={custom_trace}, returned={returned_trace}, status={resp.status_code}")

    # E-048: Very Long Message
    TOTAL += 1
    print("\n=== MANUAL-API-048: Very Long Message Text ===")
    long_text = "A" * 5000
    resp = session.post(
        f"{API_BASE}/api/v1/groups/{group_id}/messages",
        json={"message_text": long_text, "sender_id": "manual-user-001", "sender_type": "user"},
        timeout=REQUEST_TIMEOUT
    )
    if resp.status_code == 201 and "message_id" in resp.text:
        log_pass("MANUAL-API-048", "Long message stored successfully")
    else:
        log_fail("MANUAL-API-048", "Long message failed", f"HTTP {resp.status_code}: {resp.text[:300]}")

    # E-049: Unicode Characters
    TOTAL += 1
    print("\n=== MANUAL-API-049: Unicode and Multi-byte Characters ===")
    resp = session.post(
        f"{API_BASE}/api/v1/groups/{group_id}/messages",
        json={"message_text": "你好世界 🎉 ñoño émojis: 🔥🚀💡", "sender_id": "manual-user-001", "sender_type": "user"},
        timeout=REQUEST_TIMEOUT
    )
    if resp.status_code == 201 and "你好世界" in resp.text:
        log_pass("MANUAL-API-049", "Unicode characters preserved")
    else:
        log_fail("MANUAL-API-049", "Unicode characters not preserved", f"HTTP {resp.status_code}: {resp.text[:300]}")

    # E-050: Empty Message Text
    run_test(
        "MANUAL-API-050", "Empty Message Text", 400, "POST", f"/api/v1/groups/{group_id}/messages",
        json={"message_text": "", "sender_id": "manual-user-001", "sender_type": "user"}
    )

    # =====================================================================
    # Phase F: Concurrent Scenarios
    # =====================================================================
    print("\n" + "=" * 77)
    print("  PHASE F: Concurrent Scenarios")
    print("=" * 77)

    # F-051: Rapid Message Creation
    TOTAL += 1
    print("\n=== MANUAL-API-051: Rapid Message Creation ===")
    before_resp = session.get(f"{API_BASE}/api/v1/groups/{group_id}/messages", timeout=REQUEST_TIMEOUT)
    before_count = before_resp.json().get("total", 0) if before_resp.status_code == 200 else 0

    def send_msg(i: int):
        return session.post(
            f"{API_BASE}/api/v1/groups/{group_id}/messages",
            json={"message_text": f"Rapid message {i}", "sender_id": "manual-user-001", "sender_type": "user"},
            timeout=10
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(send_msg, i) for i in range(1, 11)]
        for future in as_completed(futures):
            future.result()

    time.sleep(0.5)
    after_resp = session.get(f"{API_BASE}/api/v1/groups/{group_id}/messages", timeout=REQUEST_TIMEOUT)
    after_count = after_resp.json().get("total", 0) if after_resp.status_code == 200 else 0

    if after_count >= before_count + 10:
        log_pass("MANUAL-API-051", f"All rapid messages stored (before: {before_count}, after: {after_count})")
    else:
        log_fail("MANUAL-API-051", f"Missing rapid messages (before: {before_count}, after: {after_count}, expected: {before_count + 10})")

    # F-052: Concurrent Member Joins
    TOTAL += 1
    print("\n=== MANUAL-API-052: Concurrent Member Joins ===")
    before_resp = session.get(f"{API_BASE}/api/v1/groups/{group_id}/members", timeout=REQUEST_TIMEOUT)
    before_members = before_resp.json().get("total", 0) if before_resp.status_code == 200 else 0

    def join_member(i: int):
        return session.post(
            f"{API_BASE}/api/v1/groups/{group_id}/members",
            json={"member_id": f"concurrent-user-{i}", "member_name": f"User {i}", "member_type": "user"},
            timeout=10
        )

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(join_member, i) for i in range(1, 6)]
        for future in as_completed(futures):
            future.result()

    time.sleep(0.5)
    after_resp = session.get(f"{API_BASE}/api/v1/groups/{group_id}/members", timeout=REQUEST_TIMEOUT)
    after_members = after_resp.json().get("total", 0) if after_resp.status_code == 200 else 0

    if after_members >= before_members + 5:
        log_pass("MANUAL-API-052", f"All concurrent members joined (before: {before_members}, after: {after_members})")
    else:
        log_fail("MANUAL-API-052", f"Missing concurrent members (before: {before_members}, after: {after_members}, expected: {before_members + 5})")

    # =====================================================================
    # Phase G: Cleanup
    # =====================================================================
    print("\n" + "=" * 77)
    print("  PHASE G: Cleanup")
    print("=" * 77)

    # G-053: Delete Group
    TOTAL += 1
    print("\n=== MANUAL-API-053: Delete Group with Members and Messages ===")
    resp = session.delete(f"{API_BASE}/api/v1/groups/{group_id}", timeout=REQUEST_TIMEOUT)
    if resp.status_code in (200, 204):
        verify = session.get(f"{API_BASE}/api/v1/groups/{group_id}", timeout=REQUEST_TIMEOUT)
        if verify.status_code == 404:
            log_pass("MANUAL-API-053", f"Group deleted and verified gone (HTTP {resp.status_code} → 404)")
        else:
            log_fail("MANUAL-API-053", f"Group delete returned {resp.status_code} but GET returned {verify.status_code}")
    else:
        log_fail("MANUAL-API-053", f"Group delete failed with HTTP {resp.status_code}", resp.text[:300])

    # G-025: Leave Group - Not Found (after group delete)
    run_test("MANUAL-API-025", "Leave Group - Not Found", 404, "DELETE", f"/api/v1/groups/{group_id}/members/non-existent-member")

    # G-016: Delete Group - Not Found
    run_test("MANUAL-API-016", "Delete Group - Not Found", 404, "DELETE", "/api/v1/groups/non-existent-id")

    # =====================================================================
    # Summary
    # =====================================================================
    print_summary()
    sys.exit(0 if FAILED == 0 else 1)


if __name__ == "__main__":
    main()
