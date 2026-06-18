package main

import (
	"io"
	"testing"
)

// mockLineReader is defined in interactive.go so tests can construct prompts
// without a real terminal. This test file exercises the prompt helpers and
// predefined flows.

func TestPromptStringWithDefault_EmptyUsesDefault(t *testing.T) {
	mr := &mockLineReader{lines: []string{""}}
	p := newInteractivePromptWithReader(mr)

	got, err := p.PromptStringWithDefault("Role", "user")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "user" {
		t.Fatalf("expected default 'user', got %q", got)
	}
}

func TestPromptStringWithDefault_InputOverridesDefault(t *testing.T) {
	mr := &mockLineReader{lines: []string{"admin"}}
	p := newInteractivePromptWithReader(mr)

	got, err := p.PromptStringWithDefault("Role", "user")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "admin" {
		t.Fatalf("expected input 'admin', got %q", got)
	}
}

func TestPromptStringWithDefault_TrimsWhitespace(t *testing.T) {
	mr := &mockLineReader{lines: []string{"  admin  "}}
	p := newInteractivePromptWithReader(mr)

	got, err := p.PromptStringWithDefault("Role", "user")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "admin" {
		t.Fatalf("expected trimmed input 'admin', got %q", got)
	}
}

func TestPromptString_RequiredRejectsEmpty(t *testing.T) {
	mr := &mockLineReader{lines: []string{"", "alice"}}
	p := newInteractivePromptWithReader(mr)

	got, err := p.PromptString("Account name", true)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "alice" {
		t.Fatalf("expected 'alice', got %q", got)
	}
}

func TestPromptString_OptionalAllowsEmpty(t *testing.T) {
	mr := &mockLineReader{lines: []string{""}}
	p := newInteractivePromptWithReader(mr)

	got, err := p.PromptString("Description", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != "" {
		t.Fatalf("expected empty string, got %q", got)
	}
}

func TestPromptString_CancellationOnEOF(t *testing.T) {
	mr := &mockLineReader{lines: []string{}}
	p := newInteractivePromptWithReader(mr)

	_, err := p.PromptString("Account name", true)
	if err != ErrCancelled {
		t.Fatalf("expected ErrCancelled, got %v", err)
	}
}

func TestPromptBool_DefaultTrue(t *testing.T) {
	mr := &mockLineReader{lines: []string{""}}
	p := newInteractivePromptWithReader(mr)

	got, err := p.PromptBool("Confirm", true)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !got {
		t.Fatal("expected true for empty input with default true")
	}
}

func TestPromptBool_DefaultFalse(t *testing.T) {
	mr := &mockLineReader{lines: []string{""}}
	p := newInteractivePromptWithReader(mr)

	got, err := p.PromptBool("Confirm", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got {
		t.Fatal("expected false for empty input with default false")
	}
}

func TestPromptBool_InputYes(t *testing.T) {
	mr := &mockLineReader{lines: []string{"Y"}}
	p := newInteractivePromptWithReader(mr)

	got, err := p.PromptBool("Confirm", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !got {
		t.Fatal("expected true for 'Y'")
	}
}

func TestPromptBool_PromptShowsDefault(t *testing.T) {
	mr := &mockLineReader{lines: []string{""}}
	p := newInteractivePromptWithReader(mr)

	_, err := p.PromptBool("Delete group X", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(mr.prompts) == 0 {
		t.Fatal("expected prompt to be set")
	}
	got := mr.prompts[len(mr.prompts)-1]
	want := "Delete group X [y/n] (default: n): "
	if got != want {
		t.Fatalf("expected prompt %q, got %q", want, got)
	}
}

func TestPromptBool_InputDoesNotAppendToDefault(t *testing.T) {
	// Simulates a user typing "y" into an empty buffer. With the old
	// implementation the buffer was pre-filled with "n", so the result would
	// have been "ny" and parsed as false.
	mr := &mockLineReader{lines: []string{"y"}}
	p := newInteractivePromptWithReader(mr)

	got, err := p.PromptBool("Delete group X", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !got {
		t.Fatal("expected true when user types 'y' with default false")
	}
}

func TestPromptChoice_ValidSelection(t *testing.T) {
	mr := &mockLineReader{lines: []string{"2"}}
	p := newInteractivePromptWithReader(mr)

	idx, val, err := p.PromptChoice("Role", []string{"user", "manager", "admin"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if idx != 1 || val != "manager" {
		t.Fatalf("expected idx=1 val=manager, got idx=%d val=%q", idx, val)
	}
}

func TestPromptChoice_EmptyThenValid(t *testing.T) {
	mr := &mockLineReader{lines: []string{"", "3"}}
	p := newInteractivePromptWithReader(mr)

	idx, val, err := p.PromptChoice("Role", []string{"user", "manager", "admin"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if idx != 2 || val != "admin" {
		t.Fatalf("expected idx=2 val=admin, got idx=%d val=%q", idx, val)
	}
}

func TestPromptAccountCreate_MapsFieldsCorrectly(t *testing.T) {
	// Simulate: name, desc, role choice (admin=3), login name, password, email, external id, auth provider, avatar url
	mr := &mockLineReader{lines: []string{
		"Alice",
		"Tester",
		"3",
		"alice@example.com",
		"secret",
		"alice@example.com",
		"ext-123",
		"oidc",
		"https://example.com/avatar.png",
	}}
	p := newInteractivePromptWithReader(mr)

	req, err := PromptAccountCreate(p, RoleAdmin)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if req["account_name"] != "Alice" {
		t.Fatalf("expected account_name Alice, got %v", req["account_name"])
	}
	if req["account_description"] != "Tester" {
		t.Fatalf("expected account_description Tester, got %v", req["account_description"])
	}
	if req["role"] != RoleAdmin {
		t.Fatalf("expected role admin, got %v", req["role"])
	}
	if req["login_name"] != "alice@example.com" {
		t.Fatalf("expected login_name alice@example.com, got %v", req["login_name"])
	}
	if req["login_password"] != "secret" {
		t.Fatalf("expected login_password secret, got %v", req["login_password"])
	}
	if req["email"] != "alice@example.com" {
		t.Fatalf("expected email alice@example.com, got %v", req["email"])
	}
	if req["external_id"] != "ext-123" {
		t.Fatalf("expected external_id ext-123, got %v", req["external_id"])
	}
	if req["auth_provider"] != "oidc" {
		t.Fatalf("expected auth_provider oidc, got %v", req["auth_provider"])
	}
	if req["avatar_url"] != "https://example.com/avatar.png" {
		t.Fatalf("expected avatar_url, got %v", req["avatar_url"])
	}
}

func TestPromptAccountCreate_ManagerForcesUserRole(t *testing.T) {
	mr := &mockLineReader{lines: []string{
		"Bob",
		"",
		"bob@example.com",
		"",
		"",
		"",
		"",
		"",
	}}
	p := newInteractivePromptWithReader(mr)

	req, err := PromptAccountCreate(p, RoleManager)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if req["role"] != RoleUser {
		t.Fatalf("expected role user for manager caller, got %v", req["role"])
	}
}

func TestPromptAPIKeyCreate_AdminCanChooseRole(t *testing.T) {
	mr := &mockLineReader{lines: []string{"", "CLI Key", "2"}}
	p := newInteractivePromptWithReader(mr)

	accountID, name, role, err := PromptAPIKeyCreate(p, RoleAdmin, "acc-123")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if accountID != "acc-123" {
		t.Fatalf("expected accountID acc-123, got %q", accountID)
	}
	if name != "CLI Key" {
		t.Fatalf("expected name CLI Key, got %q", name)
	}
	if role != RoleManager {
		t.Fatalf("expected role manager, got %q", role)
	}
}

func TestPromptAPIKeyCreate_UserForcedUserRole(t *testing.T) {
	mr := &mockLineReader{lines: []string{"", "CLI Key"}}
	p := newInteractivePromptWithReader(mr)

	accountID, _, role, err := PromptAPIKeyCreate(p, RoleUser, "acc-123")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if role != RoleUser {
		t.Fatalf("expected role user, got %q", role)
	}
	if accountID != "acc-123" {
		t.Fatalf("expected accountID acc-123, got %q", accountID)
	}
}

func TestPromptPasswordChange_Mismatch(t *testing.T) {
	mr := &mockLineReader{lines: []string{"newpass", "different"}}
	p := newInteractivePromptWithReader(mr)

	_, _, err := PromptPasswordChange(p, false)
	if err == nil || err.Error() != "passwords do not match" {
		t.Fatalf("expected passwords do not match error, got %v", err)
	}
}

func TestPromptPasswordChange_Match(t *testing.T) {
	mr := &mockLineReader{lines: []string{"newpass", "newpass"}}
	p := newInteractivePromptWithReader(mr)

	old, new, err := PromptPasswordChange(p, false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if old != "" {
		t.Fatalf("expected empty old password, got %q", old)
	}
	if new != "newpass" {
		t.Fatalf("expected new password newpass, got %q", new)
	}
}

func TestSequentialPrompts_DoNotShareState(t *testing.T) {
	// Simulate two consecutive prompts where the first answer must not leak
	// into the second.
	mr := &mockLineReader{lines: []string{"first", "second"}}
	p := newInteractivePromptWithReader(mr)

	v1, err := p.PromptString("First", true)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	v2, err := p.PromptString("Second", true)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if v1 != "first" || v2 != "second" {
		t.Fatalf("expected first/second, got %q/%q", v1, v2)
	}
}

func TestPromptStringWithDefault_CancellationOnEOF(t *testing.T) {
	mr := &mockLineReader{lines: []string{}}
	p := newInteractivePromptWithReader(mr)

	_, err := p.PromptStringWithDefault("Role", "user")
	if err != ErrCancelled {
		t.Fatalf("expected ErrCancelled, got %v", err)
	}
}

func TestPromptInt_Valid(t *testing.T) {
	mr := &mockLineReader{lines: []string{"42"}}
	p := newInteractivePromptWithReader(mr)

	got, err := p.PromptInt("Limit", true)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != 42 {
		t.Fatalf("expected 42, got %d", got)
	}
}

func TestPromptInt_InvalidThenValid(t *testing.T) {
	mr := &mockLineReader{lines: []string{"abc", "7"}}
	p := newInteractivePromptWithReader(mr)

	got, err := p.PromptInt("Limit", true)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != 7 {
		t.Fatalf("expected 7, got %d", got)
	}
}

func TestMockLineReader_ExhaustionReturnsEOF(t *testing.T) {
	mr := &mockLineReader{lines: []string{"only"}}
	if _, err := mr.Readline(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	_, err := mr.Readline()
	if err != io.EOF {
		t.Fatalf("expected io.EOF, got %v", err)
	}
}

func TestPromptAccountCreate_PasswordDoesNotLeakIntoEmail(t *testing.T) {
	// Regression test for the interactive prompt input misalignment issue where
	// the password entered at the "Login password" prompt leaked into the
	// "Email" prompt.
	mr := &mockLineReader{lines: []string{
		"Alice",
		"Tester",
		"3",
		"alice@example.com",
		"password123",
		"alice.email@example.com",
		"ext-123",
		"oidc",
		"https://example.com/avatar.png",
	}}
	p := newInteractivePromptWithReader(mr)

	req, err := PromptAccountCreate(p, RoleAdmin)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if req["login_password"] != "password123" {
		t.Fatalf("expected login_password password123, got %v", req["login_password"])
	}
	if req["email"] != "alice.email@example.com" {
		t.Fatalf("expected email alice.email@example.com, got %v", req["email"])
	}
}
