---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Issue: Update default HTTP port to 7370 across the entire project

## Description
The ORIGIN.md specification states that the default HTTP port should be 7370, but the codebase was using 8080 in multiple places. This issue tracks updating all occurrences of the default HTTP port to 7370.

## Files Modified

1. **internal/config/config.go** (line 81)
   - Changed: `v.SetDefault("server.port", 8080)` → `v.SetDefault("server.port", 7370)`
   - This is the primary server default port configuration.

2. **cmd/cli/main.go** (line 14)
   - Changed: `defaultAPIBase = "http://localhost:8080"` → `defaultAPIBase = "http://localhost:7370"`
   - CLI default API base URL.

3. **cmd/cli/api_test.go** (lines 12, 16, 17)
   - Changed all occurrences of `http://localhost:8080` to `http://localhost:7370`
   - Unit test expectations updated to match new default.

4. **docs/Environment_Variables.md** (lines 16, 93, 103)
   - Changed `8080` → `7370` in ACS_HTTP_PORT default value
   - Changed `http://localhost:8080` → `http://localhost:7370` in ACS_SERVER_API_BASE default value
   - Updated example environment file.

5. **docs/API.md** (line 10)
   - Changed: `Default: http://localhost:8080` → `Default: http://localhost:7370`

6. **Makefile** (line 107)
   - Changed: `docker run --rm -p 8080:8080` → `docker run --rm -p 7370:7370`

7. **features/90ai-added.md** (line 192)
   - Changed: `http://localhost:8080` → `http://localhost:7370` in ACS_SERVER_API_BASE default value.

8. **tests/integration/conftest.py** (line 17)
   - Changed: `f"http://{TEST_SERVER_HOST}:8080"` → `f"http://{TEST_SERVER_HOST}:7370"`

9. **.task/Test_Execution_Checklist.md** (lines 41, 110)
   - Changed `http://test:8080` → `http://test:7370`
   - Changed `http://env:8080` → `http://env:7370`

## Verification

- `go build ./...` — PASS (no compilation errors)
- Re-checked for remaining `8080` references — only test-specific ports remain (e.g., mock agent server port 18080, test server port 18080, agent.local:8080 in interface_test.go which is a test fixture URL, not the default ACS port)

## Status

Fixed.
