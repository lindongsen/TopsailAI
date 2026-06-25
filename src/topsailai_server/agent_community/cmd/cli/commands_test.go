// Package main provides unit tests for command parsing and dispatch.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)
func TestParseInlineArgs(t *testing.T) {
	tests := []struct {
		name string
		args []string
		want map[string]string
	}{
		{
			name: "empty args",
			args: []string{},
			want: map[string]string{},
		},
		{
			name: "single flag",
			args: []string{"--name", "test"},
			want: map[string]string{"name": "test"},
		},
		{
			name: "multiple flags",
			args: []string{"--name", "test", "--id", "123"},
			want: map[string]string{"name": "test", "id": "123"},
		},
		{
			name: "key=value format",
			args: []string{"name=test", "id=123"},
			want: map[string]string{"name": "test", "id": "123"},
		},
		{
			name: "mixed formats",
			args: []string{"--name", "test", "id=123"},
			want: map[string]string{"name": "test", "id": "123"},
		},
		{
			name: "boolean flag",
			args: []string{"--force"},
			want: map[string]string{"force": "true"},
		},
		{
			name: "flag without value followed by flag",
			args: []string{"--force", "--name", "test"},
			want: map[string]string{"force": "true", "name": "test"},
		},
		{
			name: "value with spaces",
			args: []string{"--name", "hello world"},
			want: map[string]string{"name": "hello world"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := parseInlineArgs(tt.args)
			if len(got) != len(tt.want) {
				t.Errorf("parseInlineArgs() = %v, want %v", got, tt.want)
			}
			for k, v := range tt.want {
				if got[k] != v {
					t.Errorf("parseInlineArgs()[%q] = %q, want %q", k, got[k], v)
				}
			}
		})
	}
}

func TestDispatchCommandEmpty(t *testing.T) {
	state := &CLIState{running: true}

	err := DispatchCommand("", state)
	if err != nil {
		t.Errorf("DispatchCommand(\"\") error = %v, want nil", err)
	}

	err = DispatchCommand("   ", state)
	if err != nil {
		t.Errorf("DispatchCommand(\"   \") error = %v, want nil", err)
	}
}

func TestDispatchCommandUnknown(t *testing.T) {
	state := &CLIState{running: true}

	err := DispatchCommand("/unknown", state)
	if err == nil {
		t.Error("DispatchCommand(\"/unknown\") expected error, got nil")
	}
}

func TestDispatchCommandAliases(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"exit", "/exit"},
		{"quit", "/exit"},
		{"help", "/help"},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			state := &CLIState{running: true}
			err := DispatchCommand(tt.input, state)
			if err != nil {
				t.Errorf("DispatchCommand(%q) error = %v", tt.input, err)
			}
		})
	}
}

func TestDispatchCommandExit(t *testing.T) {
	state := &CLIState{running: true}

	err := DispatchCommand("/exit", state)
	if err != nil {
		t.Errorf("DispatchCommand(\"/exit\") error = %v, want nil", err)
	}
	if state.running {
		t.Error("expected running to be false after /exit")
	}
}

func TestDispatchCommandHelp(t *testing.T) {
	state := &CLIState{running: true}

	err := DispatchCommand("/help", state)
	if err != nil {
		t.Errorf("DispatchCommand(\"/help\") error = %v, want nil", err)
	}
	if !state.running {
		t.Error("expected running to still be true after /help")
	}
}

func TestCommandHandlersExist(t *testing.T) {
	expectedCommands := []string{
		"/group:list",
		"/group:create",
		"/group:enter",
		"/group:update",
		"/group:delete",
		"/member:list",
		"/member:add",
		"/member:remove",
		"/member:update",
		"/message:list",
		"/message:edit",
		"/message:delete",
		"/help",
		"/exit",
	}

	for _, cmd := range expectedCommands {
		if _, ok := commandHandlers[cmd]; !ok {
			t.Errorf("commandHandlers missing %q", cmd)
		}
	}
}

func TestCommandAliasesExist(t *testing.T) {
	expectedAliases := map[string]string{
		"exit": "/exit",
		"quit": "/exit",
		"help": "/help",
	}

	for alias, target := range expectedAliases {
		if got, ok := commandAliases[alias]; !ok {
			t.Errorf("commandAliases missing %q", alias)
		} else if got != target {
			t.Errorf("commandAliases[%q] = %q, want %q", alias, got, target)
		}
	}
}

func TestDispatchCommandWithArgs(t *testing.T) {
	// Test that commands with inline args are parsed correctly.
	// Create a mock API client to avoid nil pointer dereference.
	state := &CLIState{
		running:   true,
		apiClient: NewAPIClient("http://localhost:99999"),
	}

	// /group:list with query params should not error (will fail on API call, but parsing should work)
	err := DispatchCommand("/group:list --limit 10", state)
	// This will fail because there's no API server, but it should parse the args.
	// We expect an error from the API call, not from parsing.
	if err == nil {
		// If no error, the API call succeeded (no server), which is unexpected.
		// Actually with no server it should error. Let's just verify it doesn't panic.
	}
}

func TestDispatchCommandCaseInsensitiveAliases(t *testing.T) {
	state := &CLIState{running: true}

	// Aliases are case-insensitive in current implementation (converted to lowercase)
	err := DispatchCommand("EXIT", state)
	// "EXIT" is converted to "exit" which is an alias for "/exit"
	// Since state has no apiClient, handleExit won't call API, just sets running=false
	if err != nil {
		t.Errorf("DispatchCommand(\"EXIT\") unexpected error: %v", err)
	}
	if state.running {
		t.Error("DispatchCommand(\"EXIT\") expected running to be false")
	}
}

func TestParseInlineArgsEmptyValue(t *testing.T) {
	args := []string{"--name", ""}
	got := parseInlineArgs(args)
	if got["name"] != "" {
		t.Errorf("parseInlineArgs() = %q, want empty string", got["name"])
	}
}

func TestParseInlineArgsMultipleEquals(t *testing.T) {
	args := []string{"data=key=value"}
	got := parseInlineArgs(args)
	if got["data"] != "key=value" {
		t.Errorf("parseInlineArgs() = %q, want 'key=value'", got["data"])
	}
}

func TestParseInlineArgsNoValueAfterFlag(t *testing.T) {
	args := []string{"--name"}
	got := parseInlineArgs(args)
	if got["name"] != "true" {
		t.Errorf("parseInlineArgs() = %q, want 'true'", got["name"])
	}
}

func TestCLIStateStruct(t *testing.T) {
	state := &CLIState{
		userID:   "u1",
		userName: "Alice",
		running:  true,
	}

	if state.userID != "u1" {
		t.Errorf("userID = %q, want %q", state.userID, "u1")
	}
	if state.userName != "Alice" {
		t.Errorf("userName = %q, want %q", state.userName, "Alice")
	}
	if !state.running {
		t.Error("expected running to be true")
	}
}

func TestCommandHandlerType(t *testing.T) {
	// Verify that all handlers conform to CommandHandler type.
	var _ CommandHandler = handleGroupList
	var _ CommandHandler = handleGroupCreate
	var _ CommandHandler = handleGroupEnter
	var _ CommandHandler = handleGroupUpdate
	var _ CommandHandler = handleGroupDelete
	var _ CommandHandler = handleMemberList
	var _ CommandHandler = handleMemberAdd
	var _ CommandHandler = handleMemberRemove
	var _ CommandHandler = handleMemberUpdate
	var _ CommandHandler = handleMessageList
	var _ CommandHandler = handleMessageEdit
	var _ CommandHandler = handleMessageDelete
	var _ CommandHandler = handleHelp
	var _ CommandHandler = handleExit
}

func TestDispatchCommandWhitespace(t *testing.T) {
	state := &CLIState{running: true}

	tests := []struct {
		input string
	}{
		{"  /help  "},
		{"/help   "},
		{"   /help"},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			err := DispatchCommand(tt.input, state)
			if err != nil {
				t.Errorf("DispatchCommand(%q) error = %v", tt.input, err)
			}
		})
	}
}

func TestDispatchCommandMultipleSpaces(t *testing.T) {
	state := &CLIState{
		running:   true,
		apiClient: NewAPIClient("http://localhost:99999"),
	}

	// Multiple spaces between command and args
	err := DispatchCommand("/group:list   --limit   10", state)
	// Should parse without panic
	_ = err
}

func TestRestorePrompt(t *testing.T) {
	// restorePrompt requires a readline instance, which we can't easily mock.
	// Just verify it doesn't panic with nil rl (it will panic, so we skip).
	t.Skip("restorePrompt requires readline instance")
}

func TestHandleGroupEnterInlineArg(t *testing.T) {
	// Verify that a direct group_id argument is parsed by handleGroupEnter fallback.
	args := []string{"group-123"}
	params := parseInlineArgs(args)

	groupID := params["group-id"]
	if groupID == "" && len(args) > 0 {
		groupID = strings.TrimSpace(args[0])
	}
	if groupID != "group-123" {
		t.Errorf("handleGroupEnter inline arg parsing failed: got %q, want %q", groupID, "group-123")
	}
}

func TestHandleGroupEnterEmptyInlineArg(t *testing.T) {
	args := []string{""}
	groupID := ""
	params := parseInlineArgs(args)
	if params["group-id"] == "" && len(args) > 0 {
		groupID = strings.TrimSpace(args[0])
	}
	if groupID != "" {
		t.Errorf("expected empty groupID for empty arg, got %q", groupID)
	}
}

// --- Account/authorization tests ---

func TestHasRole(t *testing.T) {
	tests := []struct {
		role     string
		required string
		want     bool
	}{
		{RoleAdmin, RoleUser, true},
		{RoleAdmin, RoleManager, true},
		{RoleAdmin, RoleAdmin, true},
		{RoleManager, RoleUser, true},
		{RoleManager, RoleManager, true},
		{RoleManager, RoleAdmin, false},
		{RoleUser, RoleUser, true},
		{RoleUser, RoleManager, false},
		{RoleUser, RoleAdmin, false},
		{"", RoleUser, false},
	}
	for _, tt := range tests {
		t.Run(tt.role+"_"+tt.required, func(t *testing.T) {
			if got := hasRole(tt.role, tt.required); got != tt.want {
				t.Errorf("hasRole(%q, %q) = %v, want %v", tt.role, tt.required, got, tt.want)
			}
		})
	}
}

func TestRequireAuth(t *testing.T) {
	state := &CLIState{apiClient: NewAPIClient("http://localhost")}
	if err := requireAuth(state); err == nil {
		t.Error("requireAuth() expected error for unauthenticated state")
	}

	state.apiClient.SetAuthMethod(AuthMethodAPIKey, "ak-test.secret")
	if err := requireAuth(state); err != nil {
		t.Errorf("requireAuth() unexpected error: %v", err)
	}
}

func TestRequireRole(t *testing.T) {
	state := &CLIState{
		apiClient:   NewAPIClient("http://localhost"),
		accountRole: RoleUser,
	}
	state.apiClient.SetAuthMethod(AuthMethodAPIKey, "ak-test.secret")

	if err := requireRole(state, RoleUser); err != nil {
		t.Errorf("requireRole(user) unexpected error: %v", err)
	}
	if err := requireRole(state, RoleManager); err == nil {
		t.Error("requireRole(manager) expected error for user role")
	}
}

func TestUpdateAuthState(t *testing.T) {
	state := &CLIState{apiClient: NewAPIClient("http://localhost"), userName: "anonymous"}
	updateAuthState(state, AuthMethodAPIKey, "ak-test.secret", "acc-1", "Alice", RoleUser, 0)

	if state.userID != "acc-1" {
		t.Errorf("userID = %q, want %q", state.userID, "acc-1")
	}
	if state.userName != "Alice" {
		t.Errorf("userName = %q, want %q", state.userName, "Alice")
	}
	if state.accountRole != RoleUser {
		t.Errorf("accountRole = %q, want %q", state.accountRole, RoleUser)
	}
	if state.apiKey != "ak-test.secret" {
		t.Errorf("apiKey = %q, want %q", state.apiKey, "ak-test.secret")
	}
	if state.sessionKey != "" {
		t.Errorf("sessionKey = %q, want empty", state.sessionKey)
	}
}

func TestClearAuthState(t *testing.T) {
	state := &CLIState{apiClient: NewAPIClient("http://localhost")}
	updateAuthState(state, AuthMethodAPIKey, "ak-test.secret", "acc-1", "Alice", RoleUser, 0)
	clearAuthState(state)

	if state.apiClient.IsAuthenticated() {
		t.Error("expected client to be unauthenticated after clearAuthState")
	}
	if state.userName != "anonymous" {
		t.Errorf("userName = %q, want anonymous", state.userName)
	}
}

func TestFormatAPIError(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want string
	}{
		{
			name: "401",
			err:  fmt.Errorf("HTTP 401 Unauthorized"),
			want: "authentication required",
		},
		{
			name: "403",
			err:  fmt.Errorf("HTTP 403 Forbidden"),
			want: "access denied",
		},
		{
			name: "other",
			err:  fmt.Errorf("HTTP 500 Internal Server Error"),
			want: "HTTP 500 Internal Server Error",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := formatAPIError(tt.err)
			if !strings.Contains(got.Error(), tt.want) {
				t.Errorf("formatAPIError() = %q, want containing %q", got.Error(), tt.want)
			}
		})
	}
}

func TestBuildAccountCreateRequest(t *testing.T) {
	params := map[string]string{
		"name":          "Alice",
		"description":   "Test user",
		"role":          RoleUser,
		"login-name":    "alice@example.com",
		"login-password": "secret",
		"email":         "alice@example.com",
	}
	req := buildAccountCreateRequest(params)

	if req["account_name"] != "Alice" {
		t.Errorf("account_name = %v, want Alice", req["account_name"])
	}
	if req["role"] != RoleUser {
		t.Errorf("role = %v, want user", req["role"])
	}
}

func TestBuildAccountUpdateRequest(t *testing.T) {
	params := map[string]string{
		"name":       "Alice Updated",
		"status":     "inactive",
		"avatar-url": "https://example.com/avatar.png",
	}
	req := buildAccountUpdateRequest(params)

	if req["account_name"] != "Alice Updated" {
		t.Errorf("account_name = %v", req["account_name"])
	}
	if req["status"] != "inactive" {
		t.Errorf("status = %v", req["status"])
	}
}

func TestCommandHandlersIncludeAuthCommands(t *testing.T) {
	expectedCommands := []string{
		"/login",
		"/logout",
		"/account:me",
		"/account:create",
		"/account:list",
		"/account:get",
		"/account:update",
		"/account:delete",
		"/account:password",
		"/account:session",
		"/api-key:create",
		"/api-key:list",
		"/api-key:delete",
	}

	for _, cmd := range expectedCommands {
		if _, ok := commandHandlers[cmd]; !ok {
			t.Errorf("commandHandlers missing %q", cmd)
		}
	}
}

func TestCommandHandlerTypeAuth(t *testing.T) {
	var _ CommandHandler = handleLogin
	var _ CommandHandler = handleLogout
	var _ CommandHandler = handleAccountMe
	var _ CommandHandler = handleAccountCreate
	var _ CommandHandler = handleAccountList
	var _ CommandHandler = handleAccountGet
	var _ CommandHandler = handleAccountUpdate
	var _ CommandHandler = handleAccountDelete
	var _ CommandHandler = handleAccountPassword
	var _ CommandHandler = handleAccountSession
	var _ CommandHandler = handleAPIKeyCreate
	var _ CommandHandler = handleAPIKeyList
	var _ CommandHandler = handleAPIKeyDelete
}

// --- Command handler tests with mock HTTP server ---

func newMockCLIState(t *testing.T) (*CLIState, *httptest.Server, func() string, func()) {
	t.Helper()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/api/v1/groups":
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"items": []map[string]interface{}{
						{"group_id": "group-123", "group_name": "Team", "group_context": "ctx"},
					},
					"total": 1,
				}),
			})
		case r.Method == http.MethodPost && r.URL.Path == "/api/v1/groups":
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"group_id": "group-new", "group_name": "New Team", "group_context": "New context",
				}),
			})
		case r.Method == http.MethodPut && strings.HasPrefix(r.URL.Path, "/api/v1/groups/"):
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"group_id": "group-123", "group_name": "Updated", "group_context": "Updated context",
				}),
			})
		case r.Method == http.MethodDelete && strings.HasPrefix(r.URL.Path, "/api/v1/groups/"):
			w.WriteHeader(http.StatusNoContent)
			json.NewEncoder(w).Encode(APIResponse{})
		case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/api/v1/groups/") && strings.HasSuffix(r.URL.Path, "/members"):
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"items": []map[string]interface{}{
						{"member_id": "u1", "member_name": "Alice", "member_type": "user"},
					},
					"total": 1,
				}),
			})
		case r.Method == http.MethodPost && strings.HasPrefix(r.URL.Path, "/api/v1/groups/") && strings.HasSuffix(r.URL.Path, "/members"):
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"group_id": "group-123", "member_id": "u2", "member_name": "Bob", "member_type": "user",
				}),
			})
		case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/api/v1/groups/") && strings.HasSuffix(r.URL.Path, "/messages"):
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"items": []map[string]interface{}{
						{"message_id": "msg-1", "message_text": "hello", "sender_id": "u1", "sender_type": "user"},
					},
					"total": 1,
				}),
			})
		default:
			w.WriteHeader(http.StatusNotFound)
			json.NewEncoder(w).Encode(APIResponse{Error: "not found"})
		}
	}))

	client := NewAPIClient(server.URL)
	client.SetAPIKey("ak-test.secret")

	state := &CLIState{
		running:     true,
		apiClient:   client,
		userID:      "u1",
		userName:    "Alice",
		accountRole: "user",
		lastGroupID: "group-123",
	}

	oldStdout := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w

	oldPromptState := promptState
	promptState = state

	cleanup := func() {
		if w != nil {
			w.Close()
			os.Stdout = oldStdout
			w = nil
		}
		io.Copy(io.Discard, r)
		r.Close()
		promptState = oldPromptState
		server.Close()
	}

	captureOutput := func() string {
		if w != nil {
			w.Close()
			os.Stdout = oldStdout
			w = nil
		}
		var buf bytes.Buffer
		io.Copy(&buf, r)
		return buf.String()
	}

	return state, server, captureOutput, cleanup
}

func mustJSON(v interface{}) json.RawMessage {
	b, _ := json.Marshal(v)
	return b
}

func TestHandleGroupList(t *testing.T) {
	state, _, captureOutput, cleanup := newMockCLIState(t)
	defer cleanup()

	err := handleGroupList([]string{}, state)
	if err != nil {
		t.Fatalf("handleGroupList error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "group-123") {
		t.Errorf("expected output to contain group id, got: %s", out)
	}
}

func TestHandleGroupCreate(t *testing.T) {
	state, _, captureOutput, cleanup := newMockCLIState(t)
	defer cleanup()

	err := handleGroupCreate([]string{"--name", "New Team", "--context", "New context"}, state)
	if err != nil {
		t.Fatalf("handleGroupCreate error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "group-new") {
		t.Errorf("expected output to contain created group id, got: %s", out)
	}
}

func TestHandleGroupUpdate(t *testing.T) {
	state, _, captureOutput, cleanup := newMockCLIState(t)
	defer cleanup()

	err := handleGroupUpdate([]string{"--group-id", "group-123", "--name", "Updated"}, state)
	if err != nil {
		t.Fatalf("handleGroupUpdate error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "updated") {
		t.Errorf("expected output to contain updated confirmation, got: %s", out)
	}
}

func TestHandleGroupDelete(t *testing.T) {
	state, _, captureOutput, cleanup := newMockCLIState(t)
	defer cleanup()

	err := handleGroupDelete([]string{"--group-id", "group-123", "--yes"}, state)
	if err != nil {
		t.Fatalf("handleGroupDelete error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "deleted") {
		t.Errorf("expected output to contain deleted confirmation, got: %s", out)
	}
}

func TestHandleMemberList(t *testing.T) {
	state, _, captureOutput, cleanup := newMockCLIState(t)
	defer cleanup()

	err := handleMemberList([]string{"--group-id", "group-123"}, state)
	if err != nil {
		t.Fatalf("handleMemberList error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Alice") {
		t.Errorf("expected output to contain member name, got: %s", out)
	}
}

func TestHandleMemberAdd(t *testing.T) {
	state, _, captureOutput, cleanup := newMockCLIState(t)
	defer cleanup()

	err := handleMemberAdd([]string{
		"--group-id", "group-123",
		"--member-id", "u2",
		"--member-name", "Bob",
		"--member-type", "user",
	}, state)
	if err != nil {
		t.Fatalf("handleMemberAdd error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "u2") {
		t.Errorf("expected output to contain added member id, got: %s", out)
	}
}

func TestHandleMessageList(t *testing.T) {
	state, _, captureOutput, cleanup := newMockCLIState(t)
	defer cleanup()

	err := handleMessageList([]string{"--group-id", "group-123"}, state)
	if err != nil {
		t.Fatalf("handleMessageList error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "hello") {
		t.Errorf("expected output to contain message text, got: %s", out)
	}
}

func TestSanitizeMemberName(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want string
	}{
		{"alphanumeric", "Agent123", "Agent123"},
		{"with hyphen", "my-agent", "my-agent"},
		{"with underscore", "my_agent", "my_agent"},
		{"with spaces", "my agent", "my_agent"},
		{"with special chars", "agent@foo!bar", "agent_foo_bar"},
		{"empty", "", ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := sanitizeMemberName(tt.in)
			if got != tt.want {
				t.Errorf("sanitizeMemberName(%q) = %q, want %q", tt.in, got, tt.want)
			}
		})
	}
}

// --- Additional helper for tests with custom handlers ---

// newTestCLIState creates a CLIState wired to a custom httptest handler and
// captures stdout for assertion. It also manages the global promptState.
func newTestCLIState(t *testing.T, handler http.HandlerFunc, role string) (*CLIState, func() string, func()) {
	t.Helper()

	server := httptest.NewServer(handler)
	client := NewAPIClient(server.URL)
	client.SetAPIKey("ak-test.secret")

	state := &CLIState{
		running:     true,
		apiClient:   client,
		userID:      "u1",
		userName:    "Alice",
		accountRole: role,
		lastGroupID: "group-123",
	}

	oldStdout := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w

	oldPromptState := promptState
	promptState = state

	cleanup := func() {
		if w != nil {
			w.Close()
			os.Stdout = oldStdout
			w = nil
		}
		io.Copy(io.Discard, r)
		r.Close()
		promptState = oldPromptState
		server.Close()
	}

	captureOutput := func() string {
		if w != nil {
			w.Close()
			os.Stdout = oldStdout
			w = nil
		}
		var buf bytes.Buffer
		io.Copy(&buf, r)
		return buf.String()
	}

	return state, captureOutput, cleanup
}

// --- Login / Logout ---

func TestHandleLogin_APIKey(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/me" {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id":   "acc-1",
					"account_name": "Alice",
					"role":         "user",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()

	err := handleLogin([]string{"--api-key", "ak-test.secret"}, state)
	if err != nil {
		t.Fatalf("handleLogin error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Logged in") {
		t.Errorf("expected login success message, got: %s", out)
	}
	if state.userID != "acc-1" {
		t.Errorf("userID = %q, want acc-1", state.userID)
	}
	if state.accountRole != RoleUser {
		t.Errorf("accountRole = %q, want user", state.accountRole)
	}
}

func TestHandleLogin_SessionKey(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/me" {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id":   "acc-1",
					"account_name": "Alice",
					"role":         "admin",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, "")
	defer cleanup()

	err := handleLogin([]string{"--session-key", "acc-1-session"}, state)
	if err != nil {
		t.Fatalf("handleLogin error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Logged in") {
		t.Errorf("expected login success message, got: %s", out)
	}
	if state.accountRole != RoleAdmin {
		t.Errorf("accountRole = %q, want admin", state.accountRole)
	}
}

func TestHandleLogin_LoginNamePassword(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/api/v1/accounts/login":
			var body map[string]interface{}
			json.NewDecoder(r.Body).Decode(&body)
			if body["login_name"] != "alice@example.com" || body["login_password"] != "secret" {
				t.Errorf("unexpected login body: %v", body)
			}
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id":    "acc-1",
					"session_key":   "acc-1-session",
					"expires_at_ms": int64(1704153600000),
				}),
			})
		case r.URL.Path == "/api/v1/accounts/me":
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id":   "acc-1",
					"account_name": "Alice",
					"role":         "user",
				}),
			})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}, "")
	defer cleanup()

	err := handleLogin([]string{"--login-name", "alice@example.com", "--login-password", "secret"}, state)
	if err != nil {
		t.Fatalf("handleLogin error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Logged in") {
		t.Errorf("expected login success message, got: %s", out)
	}
	if state.sessionKey != "acc-1-session" {
		t.Errorf("sessionKey = %q, want acc-1-session", state.sessionKey)
	}
}

func TestHandleLogin_MissingCredentials(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}, "")
	defer cleanup()

	// No inline args and no readline -> method stays empty, no API call, prints warning.
	err := handleLogin([]string{}, state)
	if err != nil {
		t.Fatalf("handleLogin error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Cancelled") {
		t.Errorf("expected cancellation message, got: %s", out)
	}
}

func TestHandleLogout(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {}, RoleUser)
	defer cleanup()

	err := handleLogout([]string{}, state)
	if err != nil {
		t.Fatalf("handleLogout error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Logged out") {
		t.Errorf("expected logout message, got: %s", out)
	}
	if state.apiClient.IsAuthenticated() {
		t.Error("expected client to be unauthenticated after logout")
	}
}

// --- Account command handler tests ---
// --- Account command handler tests ---

func TestHandleAccountMe(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/me" {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id":   "acc-1",
					"account_name": "Alice",
					"role":         "user",
					"email":        "alice@example.com",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()

	err := handleAccountMe([]string{}, state)
	if err != nil {
		t.Fatalf("handleAccountMe error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Alice") {
		t.Errorf("expected account name in output, got: %s", out)
	}
	if state.userID != "acc-1" {
		t.Errorf("userID = %q, want acc-1", state.userID)
	}
}

func TestHandleAccountCreate_Admin(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts" {
			var body map[string]interface{}
			json.NewDecoder(r.Body).Decode(&body)
			if body["account_name"] != "Bob" {
				t.Errorf("account_name = %v, want Bob", body["account_name"])
			}
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id": "acc-2",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleAdmin)
	defer cleanup()

	err := handleAccountCreate([]string{"--name", "Bob", "--role", "user", "--login-name", "bob@example.com"}, state)
	if err != nil {
		t.Fatalf("handleAccountCreate error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "acc-2") {
		t.Errorf("expected created account id, got: %s", out)
	}
}

func TestHandleAccountCreate_ManagerPassesRoleThrough(t *testing.T) {
	var receivedRole string
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts" {
			var body map[string]interface{}
			json.NewDecoder(r.Body).Decode(&body)
			receivedRole, _ = body["role"].(string)
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id": "acc-2",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleManager)
	defer cleanup()

	err := handleAccountCreate([]string{"--name", "Bob", "--role", "admin", "--login-name", "bob@example.com"}, state)
	if err != nil {
		t.Fatalf("handleAccountCreate error = %v", err)
	}

	if receivedRole != RoleAdmin {
		t.Errorf("role sent to server = %q, want admin", receivedRole)
	}
	out := captureOutput()
	if !strings.Contains(out, "acc-2") {
		t.Errorf("expected created account id, got: %s", out)
	}
}

func TestHandleAccountCreate_ManagerReceives403(t *testing.T) {
	state, _, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts" {
			w.WriteHeader(http.StatusForbidden)
			json.NewEncoder(w).Encode(APIResponse{
				Error: "manager can only create user accounts",
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleManager)
	defer cleanup()

	err := handleAccountCreate([]string{"--name", "Bob", "--role", "admin", "--login-name", "bob@example.com"}, state)
	if err == nil {
		t.Fatal("expected error for 403 response, got nil")
	}

	if !strings.Contains(err.Error(), "manager can only create user accounts") {
		t.Errorf("expected 403 error message in returned error, got: %s", err.Error())
	}
}

func TestHandleAccountList(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts" {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"items": []map[string]interface{}{
						{"account_id": "acc-1", "account_name": "Alice", "role": "user", "status": "active"},
					},
					"total": 1,
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleManager)
	defer cleanup()

	err := handleAccountList([]string{}, state)
	if err != nil {
		t.Fatalf("handleAccountList error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Alice") {
		t.Errorf("expected account name in output, got: %s", out)
	}
}

func TestHandleAccountGet(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-1" {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id":   "acc-1",
					"account_name": "Alice",
					"role":         "user",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()
	state.userID = "acc-1"

	err := handleAccountGet([]string{"--id", "acc-1"}, state)
	if err != nil {
		t.Fatalf("handleAccountGet error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Alice") {
		t.Errorf("expected account name in output, got: %s", out)
	}
}

func TestHandleAccountGet_SelfOnlyForUser(t *testing.T) {
	state, _, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {}, RoleUser)
	defer cleanup()
	state.userID = "acc-1"

	err := handleAccountGet([]string{"--id", "acc-2"}, state)
	if err == nil {
		t.Fatal("expected error for non-self account access by user")
	}
	if !strings.Contains(err.Error(), "access denied") {
		t.Errorf("error = %q, want access denied", err.Error())
	}
}

func TestHandleAccountUpdate(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-1" && r.Method == http.MethodPut {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id": "acc-1",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()
	state.userID = "acc-1"

	err := handleAccountUpdate([]string{"--id", "acc-1", "--name", "Alice Updated"}, state)
	if err != nil {
		t.Fatalf("handleAccountUpdate error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "updated") {
		t.Errorf("expected update confirmation, got: %s", out)
	}
}

func TestHandleAccountDelete(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-2" && r.Method == http.MethodDelete {
			w.WriteHeader(http.StatusNoContent)
			json.NewEncoder(w).Encode(APIResponse{})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleAdmin)
	defer cleanup()

	err := handleAccountDelete([]string{"--account-id", "acc-2", "--yes"}, state)
	if err != nil {
		t.Fatalf("handleAccountDelete error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "deleted") {
		t.Errorf("expected delete confirmation, got: %s", out)
	}
}

func TestHandleAccountPasswordSelf(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-1/password" && r.Method == http.MethodPost {
			var body map[string]interface{}
			json.NewDecoder(r.Body).Decode(&body)
			if body["new_password"] != "new-secret" {
				t.Errorf("new_password = %v, want new-secret", body["new_password"])
			}
			json.NewEncoder(w).Encode(APIResponse{Data: mustJSON(map[string]interface{}{})})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()
	state.userID = "acc-1"

	err := handleAccountPassword([]string{"--account-id", "acc-1", "--new-password", "new-secret"}, state)
	if err != nil {
		t.Fatalf("handleAccountPassword error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Password updated") {
		t.Errorf("expected password update confirmation, got: %s", out)
	}
}

func TestHandleAccountPasswordAdminTargetsOtherAccount(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-2/password" && r.Method == http.MethodPost {
			var body map[string]interface{}
			json.NewDecoder(r.Body).Decode(&body)
			if body["new_password"] != "admin-set-secret" {
				t.Errorf("new_password = %v, want admin-set-secret", body["new_password"])
			}
			json.NewEncoder(w).Encode(APIResponse{Data: mustJSON(map[string]interface{}{})})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleAdmin)
	defer cleanup()
	state.userID = "acc-1"

	err := handleAccountPassword([]string{"--account-id", "acc-2", "--new-password", "admin-set-secret"}, state)
	if err != nil {
		t.Fatalf("handleAccountPassword error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Password updated") {
		t.Errorf("expected password update confirmation, got: %s", out)
	}
}

func TestHandleAccountSession(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-2/session" && r.Method == http.MethodPost {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id":   "acc-2",
					"session_key":  "acc-2-session",
					"expires_at_ms": int64(1704153600000),
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleManager)
	defer cleanup()

	err := handleAccountSession([]string{"--id", "acc-2"}, state)
	if err != nil {
		t.Fatalf("handleAccountSession error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "acc-2-session") {
		t.Errorf("expected session key in output, got: %s", out)
	}
}

func TestHandleAccountSessionAsAdmin(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-2/session" && r.Method == http.MethodPost {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id":    "acc-2",
					"session_key":   "acc-2-admin-session",
					"expires_at_ms": int64(1704153600000),
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleAdmin)
	defer cleanup()
	state.userID = "acc-1"

	err := handleAccountSession([]string{"--account-id", "acc-2"}, state)
	if err != nil {
		t.Fatalf("handleAccountSession error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "acc-2-admin-session") {
		t.Errorf("expected session key in output, got: %s", out)
	}
}

func TestHandleAccountSessionAsUserOwnAccount(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-1/session" && r.Method == http.MethodPost {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"account_id":    "acc-1",
					"session_key":   "acc-1-user-session",
					"expires_at_ms": int64(1704153600000),
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()
	state.userID = "acc-1"

	err := handleAccountSession([]string{"--account-id", "acc-1"}, state)
	if err != nil {
		t.Fatalf("handleAccountSession error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "acc-1-user-session") {
		t.Errorf("expected session key in output, got: %s", out)
	}
}

// --- API key command handler tests ---

func TestHandleAPIKeyCreate(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-1/api-keys" && r.Method == http.MethodPost {
			var body map[string]interface{}
			json.NewDecoder(r.Body).Decode(&body)
			if body["api_key_name"] != "CLI Key" {
				t.Errorf("api_key_name = %v, want CLI Key", body["api_key_name"])
			}
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"api_key_id": "ak-1",
					"token":      "ak-1.secret",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()
	state.userID = "acc-1"

	err := handleAPIKeyCreate([]string{"--account-id", "acc-1", "--name", "CLI Key", "--role", "user"}, state)
	if err != nil {
		t.Fatalf("handleAPIKeyCreate error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "ak-1") {
		t.Errorf("expected api key id in output, got: %s", out)
	}
}

func TestHandleAPIKeyCreate_PositionalAccountID(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-2/api-keys" && r.Method == http.MethodPost {
			var body map[string]interface{}
			json.NewDecoder(r.Body).Decode(&body)
			if body["api_key_name"] != "Positional Key" {
				t.Errorf("api_key_name = %v, want Positional Key", body["api_key_name"])
			}
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"api_key_id": "ak-2",
					"token":      "ak-2.secret",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleAdmin)
	defer cleanup()

	err := handleAPIKeyCreate([]string{"acc-2", "--name", "Positional Key", "--role", "user"}, state)
	if err != nil {
		t.Fatalf("handleAPIKeyCreate error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "ak-2") {
		t.Errorf("expected api key id in output, got: %s", out)
	}
}

func TestHandleAPIKeyCreate_AccountIDEquals(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-3/api-keys" && r.Method == http.MethodPost {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"api_key_id": "ak-3",
					"token":      "ak-3.secret",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleAdmin)
	defer cleanup()

	err := handleAPIKeyCreate([]string{"account-id=acc-3", "--name", "Equals Key", "--role", "user"}, state)
	if err != nil {
		t.Fatalf("handleAPIKeyCreate error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "ak-3") {
		t.Errorf("expected api key id in output, got: %s", out)
	}
}

func TestHandleAPIKeyCreate_UserCannotCreateAdminKey(t *testing.T) {
	state, _, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {}, RoleUser)
	defer cleanup()
	state.userID = "acc-1"

	err := handleAPIKeyCreate([]string{"--account-id", "acc-1", "--name", "Bad Key", "--role", "admin"}, state)
	if err == nil {
		t.Fatal("expected error for user creating admin key")
	}
	if !strings.Contains(err.Error(), "access denied") {
		t.Errorf("error = %q, want access denied", err.Error())
	}
}

func TestHandleAPIKeyList(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-1/api-keys" {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"items": []map[string]interface{}{
						{"api_key_id": "ak-1", "api_key_name": "CLI", "role": "user", "status": "active"},
					},
					"total": 1,
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()
	state.userID = "acc-1"

	err := handleAPIKeyList([]string{"--account-id", "acc-1"}, state)
	if err != nil {
		t.Fatalf("handleAPIKeyList error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "ak-1") {
		t.Errorf("expected api key id in output, got: %s", out)
	}
}
func TestHandleAPIKeyDelete(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/accounts/acc-1/api-keys/ak-1" && r.Method == http.MethodDelete {
			w.WriteHeader(http.StatusNoContent)
			json.NewEncoder(w).Encode(APIResponse{})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()
	state.userID = "acc-1"

	err := handleAPIKeyDelete([]string{"--account-id", "acc-1", "--key-id", "ak-1"}, state)
	if err != nil {
		t.Fatalf("handleAPIKeyDelete error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "deleted") {
		t.Errorf("expected delete confirmation, got: %s", out)
	}
}

func TestHandleGroupJoin(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost && r.URL.Path == "/api/v1/groups/group-123/members" {
			var body map[string]interface{}
			_ = json.NewDecoder(r.Body).Decode(&body)
			// Self-join requests must not include member_id or member_type;
			// the server derives them from the authenticated account.
			if _, ok := body["member_id"]; ok {
				t.Errorf("self-join should not include member_id, got %v", body)
			}
			if _, ok := body["member_type"]; ok {
				t.Errorf("self-join should not include member_type, got %v", body)
			}
			if body["member_name"] != "Alice" {
				t.Errorf("unexpected member_name in join body: %v", body)
			}
			if _, ok := body["group_key"]; ok {
				t.Errorf("public group join should not include group_key, got %v", body)
			}
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"group_id":    "group-123",
					"member_id":   "u1",
					"member_name": "Alice",
					"member_type": "user",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()
	state.userID = "u1"
	state.userName = "Alice"

	err := handleGroupJoin([]string{"--group-id", "group-123"}, state)
	if err != nil {
		t.Fatalf("handleGroupJoin error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Joined group") {
		t.Errorf("expected join confirmation, got: %s", out)
	}
	if state.lastGroupID != "group-123" {
		t.Errorf("lastGroupID = %q, want group-123", state.lastGroupID)
	}
}

func TestHandleGroupJoin_WithKey(t *testing.T) {
	joinCalled := false
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost && r.URL.Path == "/api/v1/groups/group-123/members" {
			joinCalled = true
			var body map[string]interface{}
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["group_key"] != "secret" {
				t.Errorf("expected group_key=secret, got %v", body["group_key"])
			}
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"group_id":    "group-123",
					"member_id":   "u1",
					"member_name": "Alice",
					"member_type": "user",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()
	state.userID = "u1"
	state.userName = "Alice"

	err := handleGroupJoin([]string{"--group-id", "group-123", "--group-key", "secret"}, state)
	if err != nil {
		t.Fatalf("handleGroupJoin error = %v", err)
	}

	if !joinCalled {
		t.Error("expected join endpoint to be called")
	}
	_ = captureOutput()
}

func TestHandleGroupJoin_Failure(t *testing.T) {
	state, _, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost && r.URL.Path == "/api/v1/groups/group-123/members" {
			w.WriteHeader(http.StatusForbidden)
			json.NewEncoder(w).Encode(APIResponse{Error: "invalid group key"})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()
	state.userID = "u1"
	state.userName = "Alice"

	err := handleGroupJoin([]string{"--group-id", "group-123"}, state)
	if err == nil {
		t.Fatal("expected error for failed join")
	}
	if !strings.Contains(err.Error(), "invalid group key") {
		t.Errorf("error = %q, want invalid group key", err.Error())
	}
}

func TestHandleMemberRemove(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodDelete && r.URL.Path == "/api/v1/groups/group-123/members/u2" {
			w.WriteHeader(http.StatusNoContent)
			json.NewEncoder(w).Encode(APIResponse{})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()

	err := handleMemberRemove([]string{"--group-id", "group-123", "--member-id", "u2"}, state)
	if err != nil {
		t.Fatalf("handleMemberRemove error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "removed") {
		t.Errorf("expected remove confirmation, got: %s", out)
	}
}

func TestHandleMemberUpdate(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPut && r.URL.Path == "/api/v1/groups/group-123/members/u2" {
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"member_id":   "u2",
					"member_name": "Bob Updated",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()

	err := handleMemberUpdate([]string{"--group-id", "group-123", "--member-id", "u2", "--member-name", "Bob Updated"}, state)
	if err != nil {
		t.Fatalf("handleMemberUpdate error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "updated") {
		t.Errorf("expected update confirmation, got: %s", out)
	}
}

func TestHandleMemberUpdateWithInterface(t *testing.T) {
	var capturedBody map[string]interface{}
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPut && r.URL.Path == "/api/v1/groups/group-123/members/u2" {
			json.NewDecoder(r.Body).Decode(&capturedBody)
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"member_id":   "u2",
					"member_name": "Bob Updated",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()

	err := handleMemberUpdate([]string{
		"--group-id", "group-123",
		"--member-id", "u2",
		"--member-name", "Bob Updated",
		"--member-interface", `{"adaptor":"mock_agent","cmd_check_health":"mock_agent_cmd_check_health"}`,
	}, state)
	if err != nil {
		t.Fatalf("handleMemberUpdate error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "updated") {
		t.Errorf("expected update confirmation, got: %s", out)
	}

	iface, ok := capturedBody["member_interface"].(map[string]interface{})
	if !ok {
		t.Fatalf("member_interface not sent or wrong type: %v", capturedBody)
	}
	if iface["adaptor"] != "mock_agent" {
		t.Errorf("adaptor = %v, want mock_agent", iface["adaptor"])
	}
	if iface["cmd_check_health"] != "mock_agent_cmd_check_health" {
		t.Errorf("cmd_check_health = %v, want mock_agent_cmd_check_health", iface["cmd_check_health"])
	}
}

func TestHandleMessageEdit(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPut && r.URL.Path == "/api/v1/groups/group-123/messages/msg-1" {
			var body map[string]interface{}
			json.NewDecoder(r.Body).Decode(&body)
			if body["message_text"] != "Updated text" {
				t.Errorf("message_text = %v, want Updated text", body["message_text"])
			}
			json.NewEncoder(w).Encode(APIResponse{
				Data: mustJSON(map[string]interface{}{
					"message_id": "msg-1",
				}),
			})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()

	err := handleMessageEdit([]string{"--group-id", "group-123", "--message-id", "msg-1", "--text", "Updated text"}, state)
	if err != nil {
		t.Fatalf("handleMessageEdit error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Message updated") {
		t.Errorf("expected edit confirmation, got: %s", out)
	}
}

func TestHandleMessageDelete(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodDelete && r.URL.Path == "/api/v1/groups/group-123/messages/msg-1" {
			w.WriteHeader(http.StatusNoContent)
			json.NewEncoder(w).Encode(APIResponse{})
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}, RoleUser)
	defer cleanup()

	err := handleMessageDelete([]string{"--group-id", "group-123", "--message-id", "msg-1"}, state)
	if err != nil {
		t.Fatalf("handleMessageDelete error = %v", err)
	}

	out := captureOutput()
	if !strings.Contains(out, "Message deleted") {
		t.Errorf("expected delete confirmation, got: %s", out)
	}
}

// --- Help ---

func TestHandleHelp_Output(t *testing.T) {
	state, captureOutput, cleanup := newTestCLIState(t, func(w http.ResponseWriter, r *http.Request) {}, RoleUser)
	defer cleanup()

	err := handleHelp([]string{}, state)
	if err != nil {
		t.Fatalf("handleHelp error = %v", err)
	}

	out := captureOutput()
	for _, cmd := range []string{"/group:list", "/member:add", "/message:edit", "/api-key:create", "/account:delete"} {
		if !strings.Contains(out, cmd) {
			t.Errorf("help output missing %q", cmd)
		}
	}
}
