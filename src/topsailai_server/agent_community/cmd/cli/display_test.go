// Package main provides unit tests for display and formatting utilities.
package main

import (
	"strings"
	"testing"
	"time"
)

func TestColorize(t *testing.T) {
	// Save original state and restore after test.
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	tests := []struct {
		name     string
		noColor  bool
		text     string
		color    string
		expected string
	}{
		{
			name:     "color enabled",
			noColor:  false,
			text:     "hello",
			color:    colorRed,
			expected: colorRed + "hello" + colorReset,
		},
		{
			name:     "color disabled",
			noColor:  true,
			text:     "hello",
			color:    colorRed,
			expected: "hello",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			noColor = tt.noColor
			got := colorize(tt.text, tt.color)
			if got != tt.expected {
				t.Errorf("colorize() = %q, want %q", got, tt.expected)
			}
		})
	}
}

func TestColorHelpers(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = false

	if got := red("test"); !strings.Contains(got, "test") {
		t.Errorf("red() = %q, should contain 'test'", got)
	}
	if got := green("test"); !strings.Contains(got, "test") {
		t.Errorf("green() = %q, should contain 'test'", got)
	}
	if got := yellow("test"); !strings.Contains(got, "test") {
		t.Errorf("yellow() = %q, should contain 'test'", got)
	}
	if got := blue("test"); !strings.Contains(got, "test") {
		t.Errorf("blue() = %q, should contain 'test'", got)
	}
	if got := cyan("test"); !strings.Contains(got, "test") {
		t.Errorf("cyan() = %q, should contain 'test'", got)
	}
	if got := white("test"); !strings.Contains(got, "test") {
		t.Errorf("white() = %q, should contain 'test'", got)
	}
}

func TestColorHelpersNoColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = true

	if got := red("test"); got != "test" {
		t.Errorf("red() with noColor = %q, want %q", got, "test")
	}
	if got := green("test"); got != "test" {
		t.Errorf("green() with noColor = %q, want %q", got, "test")
	}
	if got := yellow("test"); got != "test" {
		t.Errorf("yellow() with noColor = %q, want %q", got, "test")
	}
}

func TestFormatTime(t *testing.T) {
	tm := time.Date(2024, 6, 12, 14, 30, 45, 0, time.UTC)
	got := formatTime(tm)
	want := "2024-06-12T14:30:45"
	if got != want {
		t.Errorf("formatTime() = %q, want %q", got, want)
	}
}

func TestFormatTimeMs(t *testing.T) {
	// 2024-06-12T15:10:45 UTC = 1718205045000 ms
	ms := int64(1718205045000)
	got := formatTimeMs(ms)
	want := "2024-06-12T15:10:45"
	if got != want {
		t.Errorf("formatTimeMs() = %q, want %q", got, want)
	}
}

func TestFormatTimeMsFloat(t *testing.T) {
	ms := float64(1718205045000)
	got := formatTimeMsFloat(ms)
	want := "2024-06-12T15:10:45"
	if got != want {
		t.Errorf("formatTimeMsFloat() = %q, want %q", got, want)
	}
}

func TestPS1Normal(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = true
	got := ps1Normal("alice", "acc-test-123", "user")
	want := "acs@alice(acc-test-123)[user]: "
	if got != want {
		t.Errorf("ps1Normal() = %q, want %q", got, want)
	}
}

func TestPS1Chat(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = true
	got := ps1Chat("alice", "acc-test-123", "user", "grp-123")
	want := "acs@alice(acc-test-123)[user]:grp-123# "
	if got != want {
		t.Errorf("ps1Chat() = %q, want %q", got, want)
	}
}

func TestFormatMessage(t *testing.T) {
	tests := []struct {
		name string
		msg  map[string]interface{}
		want string
	}{
		{
			name: "basic user message",
			msg: map[string]interface{}{
				"sender_id":    "u1",
				"sender_name":  "Alice",
				"sender_type":  "user",
				"message_text": "Hello world",
				"create_at_ms": float64(1718205045000),
			},
			want: "Alice",
		},
		{
			name: "agent message",
			msg: map[string]interface{}{
				"sender_id":    "a1",
				"sender_name":  "Bot",
				"sender_type":  "manager-agent",
				"message_text": "I am a bot",
				"create_at_ms": float64(1718205045000),
			},
			want: "Bot",
		},
		{
			name: "deleted message",
			msg: map[string]interface{}{
				"sender_id":    "u1",
				"sender_name":  "Alice",
				"sender_type":  "user",
				"message_text": "Hello world",
				"create_at_ms": float64(1718205045000),
				"is_deleted":   true,
			},
			want: "[message deleted]",
		},
		{
			name: "message without sender_name",
			msg: map[string]interface{}{
				"sender_id":    "u1",
				"sender_type":  "user",
				"message_text": "Hello",
				"create_at_ms": float64(1718205045000),
			},
			want: "u1",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := formatMessage(tt.msg)
			if !strings.Contains(got, tt.want) {
				t.Errorf("formatMessage() = %q, should contain %q", got, tt.want)
			}
			// Verify timestamp format is present.
			if !strings.Contains(got, "2024-06-12T15:10:45") {
				t.Errorf("formatMessage() = %q, should contain timestamp", got)
			}
		})
	}
}

func TestFormatGroupLine(t *testing.T) {
	got := formatGroupLine("grp-1", "My Group")
	if !strings.Contains(got, "grp-1") {
		t.Errorf("formatGroupLine() = %q, should contain 'grp-1'", got)
	}
	if !strings.Contains(got, "My Group") {
		t.Errorf("formatGroupLine() = %q, should contain 'My Group'", got)
	}
}

func TestFormatMemberLine(t *testing.T) {
	got := formatMemberLine("user", "Alice", "u1", "online")
	if !strings.Contains(got, "Alice") {
		t.Errorf("formatMemberLine() = %q, should contain 'Alice'", got)
	}
	if !strings.Contains(got, "u1") {
		t.Errorf("formatMemberLine() = %q, should contain 'u1'", got)
	}
	if !strings.Contains(got, "online") {
		t.Errorf("formatMemberLine() = %q, should contain 'online'", got)
	}
}

func TestFormatMemberLineAgentTypes(t *testing.T) {
	tests := []struct {
		memberType string
	}{
		{"user"},
		{"manager-agent"},
		{"worker-agent"},
		{"unknown"},
	}

	for _, tt := range tests {
		t.Run(tt.memberType, func(t *testing.T) {
			got := formatMemberLine(tt.memberType, "Name", "id", "online")
			if !strings.Contains(got, "Name") {
				t.Errorf("formatMemberLine() = %q, should contain 'Name'", got)
			}
		})
	}
}

func TestFormatGroupEvent(t *testing.T) {
	got := formatGroupEvent("create", "grp-1")
	if !strings.Contains(got, "create") {
		t.Errorf("formatGroupEvent() = %q, should contain 'create'", got)
	}
	if !strings.Contains(got, "grp-1") {
		t.Errorf("formatGroupEvent() = %q, should contain 'grp-1'", got)
	}
}

func TestFormatMemberEvent(t *testing.T) {
	got := formatMemberEvent("add", "grp-1")
	if !strings.Contains(got, "add") {
		t.Errorf("formatMemberEvent() = %q, should contain 'add'", got)
	}
	if !strings.Contains(got, "grp-1") {
		t.Errorf("formatMemberEvent() = %q, should contain 'grp-1'", got)
	}
}

func TestFormatGenericEvent(t *testing.T) {
	got := formatGenericEvent("message", "create", "grp-1")
	if !strings.Contains(got, "message") {
		t.Errorf("formatGenericEvent() = %q, should contain 'message'", got)
	}
	if !strings.Contains(got, "create") {
		t.Errorf("formatGenericEvent() = %q, should contain 'create'", got)
	}
	if !strings.Contains(got, "grp-1") {
		t.Errorf("formatGenericEvent() = %q, should contain 'grp-1'", got)
	}
}

func TestInitColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	tests := []struct {
		name     string
		args     []string
		envValue string
		expected bool
	}{
		{
			name:     "no-color flag",
			args:     []string{"cli", "--no-color"},
			envValue: "",
			expected: true,
		},
		{
			name:     "NO_COLOR env",
			args:     []string{"cli"},
			envValue: "1",
			expected: true,
		},
		{
			name:     "no color disabled",
			args:     []string{"cli"},
			envValue: "",
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			noColor = false
			if tt.envValue != "" {
				t.Setenv("NO_COLOR", tt.envValue)
			}
			initColor(tt.args)
			if noColor != tt.expected {
				t.Errorf("initColor() noColor = %v, want %v", noColor, tt.expected)
			}
		})
	}
}

func TestBoxHorizontalNoColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = true
	if got := boxHorizontal(); got != "-" {
		t.Errorf("boxHorizontal() with noColor = %q, want %q", got, "-")
	}
	if got := boxDoubleHorizontal(); got != "=" {
		t.Errorf("boxDoubleHorizontal() with noColor = %q, want %q", got, "=")
	}
}

func TestBoxHorizontalColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = false
	if got := boxHorizontal(); got != "─" {
		t.Errorf("boxHorizontal() with color = %q, want %q", got, "─")
	}
	if got := boxDoubleHorizontal(); got != "═" {
		t.Errorf("boxDoubleHorizontal() with color = %q, want %q", got, "═")
	}
}

func TestBannerBorderNoColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = true
	top, middle, bottom := bannerBorder()
	wantTop := "+------------------------------------------+"
	wantMiddle := "|     ACS CLI Terminal                     |"
	wantBottom := "+------------------------------------------+"
	if top != wantTop {
		t.Errorf("bannerBorder() top = %q, want %q", top, wantTop)
	}
	if middle != wantMiddle {
		t.Errorf("bannerBorder() middle = %q, want %q", middle, wantMiddle)
	}
	if bottom != wantBottom {
		t.Errorf("bannerBorder() bottom = %q, want %q", bottom, wantBottom)
	}
}

func TestBannerBorderColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = false
	top, middle, bottom := bannerBorder()
	wantTop := "╔══════════════════════════════════════════╗"
	wantMiddle := "║     ACS CLI Terminal                     ║"
	wantBottom := "╚══════════════════════════════════════════╝"
	if top != wantTop {
		t.Errorf("bannerBorder() top = %q, want %q", top, wantTop)
	}
	if middle != wantMiddle {
		t.Errorf("bannerBorder() middle = %q, want %q", middle, wantMiddle)
	}
	if bottom != wantBottom {
		t.Errorf("bannerBorder() bottom = %q, want %q", bottom, wantBottom)
	}
}

func TestPrintableSeparatorNoColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = true
	got := printableSeparator()
	want := strings.Repeat("-", 42)
	if got != want {
		t.Errorf("printableSeparator() = %q, want %q", got, want)
	}
}

func TestPrintableSeparatorColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = false
	got := printableSeparator()
	want := strings.Repeat("─", 42)
	if got != want {
		t.Errorf("printableSeparator() = %q, want %q", got, want)
	}
}

func TestAgentIcon(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	tests := []struct {
		name     string
		noColor  bool
		expected string
	}{
		{"color enabled", false, "🤖"},
		{"no color", true, "[BOT]"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			noColor = tt.noColor
			if got := agentIcon(); got != tt.expected {
				t.Errorf("agentIcon() = %q, want %q", got, tt.expected)
			}
		})
	}
}

func TestEventIcon(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	tests := []struct {
		name     string
		noColor  bool
		expected string
	}{
		{"color enabled", false, "📢"},
		{"no color", true, "[EVENT]"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			noColor = tt.noColor
			if got := eventIcon(); got != tt.expected {
				t.Errorf("eventIcon() = %q, want %q", got, tt.expected)
			}
		})
	}
}

func TestMemberIcon(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	tests := []struct {
		name     string
		noColor  bool
		expected string
	}{
		{"color enabled", false, "👤"},
		{"no color", true, "[MEMBER]"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			noColor = tt.noColor
			if got := memberIcon(); got != tt.expected {
				t.Errorf("memberIcon() = %q, want %q", got, tt.expected)
			}
		})
	}
}

func TestGenericEventIcon(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	tests := []struct {
		name     string
		noColor  bool
		expected string
	}{
		{"color enabled", false, "📰"},
		{"no color", true, "[EVENT]"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			noColor = tt.noColor
			if got := genericEventIcon(); got != tt.expected {
				t.Errorf("genericEventIcon() = %q, want %q", got, tt.expected)
			}
		})
	}
}

func TestFormatMessageNoColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = true
	msg := map[string]interface{}{
		"sender_id":    "a1",
		"sender_name":  "Bot",
		"sender_type":  "manager-agent",
		"message_text": "I am a bot",
		"create_at_ms": float64(1718205045000),
	}
	got := formatMessage(msg)
	if strings.Contains(got, "🤖") {
		t.Errorf("formatMessage() with noColor should not contain emoji, got %q", got)
	}
	if !strings.Contains(got, "[BOT]") {
		t.Errorf("formatMessage() with noColor should contain [BOT] label, got %q", got)
	}
}

func TestFormatGroupEventNoColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = true
	got := formatGroupEvent("create", "grp-1")
	if strings.Contains(got, "📢") {
		t.Errorf("formatGroupEvent() with noColor should not contain emoji, got %q", got)
	}
	if !strings.Contains(got, "[EVENT]") {
		t.Errorf("formatGroupEvent() with noColor should contain [EVENT] label, got %q", got)
	}
}

func TestFormatMemberEventNoColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = true
	got := formatMemberEvent("add", "grp-1")
	if strings.Contains(got, "👤") {
		t.Errorf("formatMemberEvent() with noColor should not contain emoji, got %q", got)
	}
	if !strings.Contains(got, "[MEMBER]") {
		t.Errorf("formatMemberEvent() with noColor should contain [MEMBER] label, got %q", got)
	}
}

func TestFormatGenericEventNoColor(t *testing.T) {
	origNoColor := noColor
	defer func() { noColor = origNoColor }()

	noColor = true
	got := formatGenericEvent("message", "create", "grp-1")
	if strings.Contains(got, "📰") {
		t.Errorf("formatGenericEvent() with noColor should not contain emoji, got %q", got)
	}
	if !strings.Contains(got, "[EVENT]") {
		t.Errorf("formatGenericEvent() with noColor should contain [EVENT] label, got %q", got)
	}
}
