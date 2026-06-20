// Package main provides unit tests for display and formatting utilities.
package main

import (
	"strings"
	"testing"
	"time"
)

func TestInitColor(t *testing.T) {
	old := noColor
	defer func() { noColor = old }()

	noColor = false
	initColor([]string{"--no-color"})
	if !noColor {
		t.Error("expected noColor to be true with --no-color flag")
	}

	noColor = false
	initColor([]string{})
	if noColor {
		t.Error("expected noColor to remain false without flag/env")
	}
}

func TestColorize(t *testing.T) {
	old := noColor
	defer func() { noColor = old }()

	noColor = false
	got := colorize("text", colorRed)
	if !strings.Contains(got, "text") {
		t.Errorf("colorize() = %q, want colored text", got)
	}
	if !strings.Contains(got, colorRed) {
		t.Errorf("colorize() = %q, want red color code", got)
	}

	noColor = true
	got = colorize("text", colorRed)
	if got != "text" {
		t.Errorf("colorize() with noColor = %q, want plain text", got)
	}
}

func TestColorHelpers(t *testing.T) {
	old := noColor
	noColor = false
	defer func() { noColor = old }()

	for _, fn := range []func(string) string{red, green, yellow, blue, cyan, white} {
		got := fn("x")
		if !strings.Contains(got, "x") {
			t.Errorf("color helper output %q does not contain text", got)
		}
	}
}

func TestFormatTime(t *testing.T) {
	ts := time.Date(2024, 1, 2, 3, 4, 5, 0, time.UTC)
	got := formatTime(ts)
	want := "2024-01-02T03:04:05"
	if got != want {
		t.Errorf("formatTime() = %q, want %q", got, want)
	}
}

func TestFormatTimeMs(t *testing.T) {
	ms := time.Date(2024, 1, 2, 3, 4, 5, 0, time.UTC).UnixMilli()
	got := formatTimeMs(ms)
	want := "2024-01-02T03:04:05"
	if got != want {
		t.Errorf("formatTimeMs() = %q, want %q", got, want)
	}
}

func TestFormatTimeMsFloat(t *testing.T) {
	ms := float64(time.Date(2024, 1, 2, 3, 4, 5, 0, time.UTC).UnixMilli())
	got := formatTimeMsFloat(ms)
	want := "2024-01-02T03:04:05"
	if got != want {
		t.Errorf("formatTimeMsFloat() = %q, want %q", got, want)
	}
}

func TestFormatMessage(t *testing.T) {
	msg := map[string]interface{}{
		"sender_id":      "u1",
		"sender_name":    "Alice",
		"sender_type":    "user",
		"message_text":   "hello",
		"create_at_ms":   float64(time.Date(2024, 1, 2, 3, 4, 5, 0, time.UTC).UnixMilli()),
	}
	got := formatMessage(msg)
	if !strings.Contains(got, "Alice") {
		t.Errorf("formatMessage() = %q, want sender name", got)
	}
	if !strings.Contains(got, "hello") {
		t.Errorf("formatMessage() = %q, want message text", got)
	}
}

func TestFormatGroupLine(t *testing.T) {
	got := formatGroupLine("group-123", "Team")
	if !strings.Contains(got, "group-123") {
		t.Errorf("formatGroupLine() = %q, want group id", got)
	}
	if !strings.Contains(got, "Team") {
		t.Errorf("formatGroupLine() = %q, want group name", got)
	}
}

func TestFormatMemberLine(t *testing.T) {
	cases := []struct {
		memberType string
	}{
		{"user"},
		{"manager-agent"},
		{"worker-agent"},
		{"unknown"},
	}
	for _, tc := range cases {
		got := formatMemberLine(tc.memberType, "Alice", "u1", "online")
		if !strings.Contains(got, "Alice") || !strings.Contains(got, "u1") {
			t.Errorf("formatMemberLine(%q) = %q", tc.memberType, got)
		}
	}
}

func TestFormatAccountLine(t *testing.T) {
	account := map[string]interface{}{
		"account_id":   "acc-1",
		"account_name": "Alice",
		"role":         "user",
		"status":       "active",
		"email":        "alice@example.com",
	}
	got := formatAccountLine(account)
	for _, want := range []string{"acc-1", "Alice", "user", "active", "alice@example.com"} {
		if !strings.Contains(got, want) {
			t.Errorf("formatAccountLine() = %q, missing %q", got, want)
		}
	}
}

func TestFormatAccountDetail(t *testing.T) {
	account := map[string]interface{}{
		"account_id":    "acc-1",
		"account_name":  "Alice",
		"role":          "user",
		"status":        "active",
		"email":         "alice@example.com",
		"external_id":   "ext-1",
		"auth_provider": "oidc",
		"avatar_url":    "https://example.com/avatar.png",
		"login_name":    "alice@example.com",
	}
	got := formatAccountDetail(account)
	for _, want := range []string{"acc-1", "Alice", "user", "active", "alice@example.com", "ext-1", "oidc", "avatar"} {
		if !strings.Contains(got, want) {
			t.Errorf("formatAccountDetail() = %q, missing %q", got, want)
		}
	}
}

func TestFormatAPIKeyLine(t *testing.T) {
	key := map[string]interface{}{
		"api_key_id": "ak-1",
		"api_key_name": "CLI",
		"role":       "user",
		"status":     "active",
	}
	got := formatAPIKeyLine(key)
	for _, want := range []string{"ak-1", "CLI", "user", "active"} {
		if !strings.Contains(got, want) {
			t.Errorf("formatAPIKeyLine() = %q, missing %q", got, want)
		}
	}
}

func TestFormatAPIKeyDetail(t *testing.T) {
	key := map[string]interface{}{
		"api_key_id":   "ak-1",
		"api_key_name": "CLI",
		"role":         "user",
		"status":       "active",
		"creator_id":   "acc-1",
		"owner_id":     "acc-1",
	}
	got := formatAPIKeyDetail(key)
	for _, want := range []string{"ak-1", "CLI", "user", "active", "acc-1"} {
		if !strings.Contains(got, want) {
			t.Errorf("formatAPIKeyDetail() = %q, missing %q", got, want)
		}
	}
}

func TestFormatSessionInfo(t *testing.T) {
	session := map[string]interface{}{
		"account_id":                 "acc-1",
		"account_name":               "Alice",
		"role":                       "user",
		"session_key":                "sk-1",
		"login_session_expired_time": float64(time.Date(2024, 1, 2, 3, 4, 5, 0, time.UTC).UnixMilli()),
	}
	got := formatSessionInfo(session)
	for _, want := range []string{"acc-1", "Alice", "user", "sk-1", "2024-01-02T03:04:05"} {
		if !strings.Contains(got, want) {
			t.Errorf("formatSessionInfo() = %q, missing %q", got, want)
		}
	}
}

func TestWriteField(t *testing.T) {
	var b strings.Builder
	writeField(&b, "Label", "value")
	if !strings.Contains(b.String(), "Label") || !strings.Contains(b.String(), "value") {
		t.Errorf("writeField() = %q", b.String())
	}

	b.Reset()
	writeField(&b, "Empty", "")
	if b.Len() != 0 {
		t.Errorf("writeField() with empty string should not write, got %q", b.String())
	}

	b.Reset()
	writeField(&b, "Nil", nil)
	if b.Len() != 0 {
		t.Errorf("writeField() with nil should not write, got %q", b.String())
	}

	b.Reset()
	writeField(&b, "Number", 42)
	if !strings.Contains(b.String(), "42") {
		t.Errorf("writeField() with number = %q", b.String())
	}
}

func TestPrintableSeparator(t *testing.T) {
	got := printableSeparator()
	if len(got) == 0 {
		t.Error("printableSeparator() returned empty string")
	}
}

func TestFormatGroupEvent(t *testing.T) {
	got := formatGroupEvent("create", "group-123")
	if !strings.Contains(got, "create") || !strings.Contains(got, "group-123") {
		t.Errorf("formatGroupEvent() = %q", got)
	}
}

func TestFormatMemberEvent(t *testing.T) {
	got := formatMemberEvent("join", "group-123")
	if !strings.Contains(got, "join") || !strings.Contains(got, "group-123") {
		t.Errorf("formatMemberEvent() = %q", got)
	}
}

func TestFormatGenericEvent(t *testing.T) {
	got := formatGenericEvent("message", "create", "group-123")
	if !strings.Contains(got, "message") || !strings.Contains(got, "create") || !strings.Contains(got, "group-123") {
		t.Errorf("formatGenericEvent() = %q", got)
	}
}

func TestPs1Normal(t *testing.T) {
	old := noColor
	defer func() { noColor = old }()

	noColor = true
	got := ps1Normal("alice", "acc-1", "user")
	if !strings.Contains(got, "alice") || !strings.Contains(got, "acc-1") || !strings.Contains(got, "user") {
		t.Errorf("ps1Normal() = %q", got)
	}

	got = ps1Normal("alice", "acc-1", "")
	if !strings.Contains(got, "alice") || !strings.Contains(got, "acc-1") {
		t.Errorf("ps1Normal() without role = %q", got)
	}
}

func TestPs1Chat(t *testing.T) {
	old := noColor
	defer func() { noColor = old }()

	noColor = true
	got := ps1Chat("alice", "acc-1", "user", "group-123")
	if !strings.Contains(got, "alice") || !strings.Contains(got, "acc-1") || !strings.Contains(got, "user") || !strings.Contains(got, "group-123") {
		t.Errorf("ps1Chat() = %q", got)
	}

	got = ps1Chat("alice", "acc-1", "", "group-123")
	if !strings.Contains(got, "alice") || !strings.Contains(got, "acc-1") || !strings.Contains(got, "group-123") {
		t.Errorf("ps1Chat() without role = %q", got)
	}
}

func TestBannerBorder(t *testing.T) {
	old := noColor
	defer func() { noColor = old }()

	noColor = true
	top, middle, bottom := bannerBorder()
	if !strings.Contains(top, "+") || !strings.Contains(middle, "ACS CLI Terminal") || !strings.Contains(bottom, "+") {
		t.Errorf("bannerBorder() noColor = top=%q middle=%q bottom=%q", top, middle, bottom)
	}
}

func TestAgentIcon(t *testing.T) {
	old := noColor
	defer func() { noColor = old }()

	noColor = true
	if got := agentIcon(); got != "[BOT]" {
		t.Errorf("agentIcon() noColor = %q, want [BOT]", got)
	}
}

func TestEventIcon(t *testing.T) {
	old := noColor
	defer func() { noColor = old }()

	noColor = true
	if got := eventIcon(); got != "[EVENT]" {
		t.Errorf("eventIcon() noColor = %q, want [EVENT]", got)
	}
}

func TestMemberIcon(t *testing.T) {
	old := noColor
	defer func() { noColor = old }()

	noColor = true
	if got := memberIcon(); got != "[MEMBER]" {
		t.Errorf("memberIcon() noColor = %q, want [MEMBER]", got)
	}
}

func TestGenericEventIcon(t *testing.T) {
	old := noColor
	defer func() { noColor = old }()

	noColor = true
	if got := genericEventIcon(); got != "[EVENT]" {
		t.Errorf("genericEventIcon() noColor = %q, want [EVENT]", got)
	}
}

func TestBoxHorizontal(t *testing.T) {
	old := noColor
	defer func() { noColor = old }()

	noColor = true
	if got := boxHorizontal(); got != "-" {
		t.Errorf("boxHorizontal() noColor = %q, want -", got)
	}
}

func TestBoxDoubleHorizontal(t *testing.T) {
	old := noColor
	defer func() { noColor = old }()

	noColor = true
	if got := boxDoubleHorizontal(); got != "=" {
		t.Errorf("boxDoubleHorizontal() noColor = %q, want =", got)
	}
}
