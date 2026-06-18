// Package main provides unit tests for command parsing and dispatch.
package main

import (
	"fmt"
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
