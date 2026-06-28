// Package main provides display helpers for the ACS chat CLI.
package main

import (
	"fmt"
	"os"
	"strings"
	"time"
)

// Display handles terminal output formatting.
type Display struct {
	noColor bool
}

// NewDisplay creates a new Display.
func NewDisplay(noColor bool) *Display {
	return &Display{noColor: noColor}
}

// Error formats an error message with optional suggestion.
func (d *Display) Error(message, suggestion string) string {
	if suggestion == "" {
		return red("Error: ") + message
	}
	return red("Error: ") + message + "\n" + yellow("Suggestion: ") + suggestion
}

// Success formats a success message.
func (d *Display) Success(message string) string {
	return green(message)
}

// Info formats an info message.
func (d *Display) Info(message string) string {
	return cyan(message)
}

// Warning formats a warning message.
func (d *Display) Warning(message string) string {
	return yellow(message)
}

// Warn is an alias for Warning.
func (d *Display) Warn(message string) string {
	return d.Warning(message)
}

// PrintError prints an error with a suggestion.
func (d *Display) PrintError(err error, suggestion string) {
	fmt.Fprintln(os.Stderr, d.Error(err.Error(), suggestion))
}

// Groups returns a compact string representation of groups.
func (d *Display) Groups(groups []Group) string {
	if len(groups) == 0 {
		return dim("No groups found.")
	}
	var b strings.Builder
	fmt.Fprintln(&b, bold("Groups"))
	fmt.Fprintln(&b, strings.Repeat("-", 60))
	for _, g := range groups {
		privacy := "public"
		if g.GroupKey != "" {
			privacy = "private"
		}
		fmt.Fprintf(&b, "%s %s (%s)\n", bold(g.GroupID), dim(g.GroupName), privacy)
		if g.GroupContext != "" {
			fmt.Fprintf(&b, "  %s\n", truncate(g.GroupContext, 80))
		}
		fmt.Fprintf(&b, "  creator: %s  owner: %s  created: %s\n", g.CreatorID, g.OwnerID, formatTime(g.CreateAtMs))
	}
	return b.String()
}

// Group returns a compact string representation of a single group.
func (d *Display) Group(g *Group) string {
	privacy := "public"
	if g.GroupKey != "" {
		privacy = "private"
	}
	var b strings.Builder
	fmt.Fprintln(&b, bold("Group created"))
	fmt.Fprintln(&b, strings.Repeat("-", 60))
	fmt.Fprintf(&b, "%s %s (%s)\n", bold(g.GroupID), dim(g.GroupName), privacy)
	if g.GroupContext != "" {
		fmt.Fprintf(&b, "  %s\n", truncate(g.GroupContext, 80))
	}
	fmt.Fprintf(&b, "  creator: %s  owner: %s  created: %s\n", g.CreatorID, g.OwnerID, formatTime(g.CreateAtMs))
	return b.String()
}

// Members returns a compact string representation of members.
func (d *Display) Members(members []Member) string {
	if len(members) == 0 {
		return dim("No members found.")
	}
	var b strings.Builder
	fmt.Fprintln(&b, bold("Members"))
	fmt.Fprintln(&b, strings.Repeat("-", 60))
	for _, m := range members {
		fmt.Fprintf(&b, "%s %s [%s]\n", bold(m.MemberID), m.MemberName, m.MemberType)
		if m.MemberDescription != "" {
			fmt.Fprintf(&b, "  %s\n", truncate(m.MemberDescription, 80))
		}
		fmt.Fprintf(&b, "  status: %s\n", m.MemberStatus)
	}
	return b.String()
}

// Member returns a compact string representation of a single member.
func (d *Display) Member(m *Member) string {
	var b strings.Builder
	fmt.Fprintln(&b, bold("Member added"))
	fmt.Fprintln(&b, strings.Repeat("-", 60))
	fmt.Fprintf(&b, "%s %s [%s]\n", bold(m.MemberID), m.MemberName, m.MemberType)
	if m.MemberDescription != "" {
		fmt.Fprintf(&b, "  %s\n", truncate(m.MemberDescription, 80))
	}
	fmt.Fprintf(&b, "  status: %s\n", m.MemberStatus)
	return b.String()
}

// Messages returns a compact string representation of messages.
func (d *Display) Messages(messages []Message) string {
	if len(messages) == 0 {
		return dim("No messages yet.")
	}
	var b strings.Builder
	for _, m := range messages {
		fmt.Fprintln(&b, d.Message(m, ""))
	}
	return b.String()
}

// Message returns a compact string representation of a single message.
func (d *Display) Message(m Message, accountID string) string {
	if m.IsDeleted {
		return fmt.Sprintf("%s %s %s", dim(formatTime(m.CreateAtMs)), dim(m.SenderName), dim("[deleted]"))
	}
	mentions := ""
	if len(m.Mentions) > 0 {
		var names []string
		for _, mention := range m.Mentions {
			names = append(names, "@"+mentionName(mention))
		}
		mentions = " " + cyan(strings.Join(names, " "))
	}
	return fmt.Sprintf("%s %s:%s %s", dim(formatTime(m.CreateAtMs)), bold(m.SenderName), mentions, m.MessageText)
}

func mentionName(v any) string {
	switch m := v.(type) {
	case map[string]any:
		if name, ok := m["member_name"].(string); ok {
			return name
		}
		if id, ok := m["member_id"].(string); ok {
			return id
		}
	case map[string]string:
		if name, ok := m["member_name"]; ok {
			return name
		}
		if id, ok := m["member_id"]; ok {
			return id
		}
	}
	return ""
}

func formatTime(ms int64) string {
	if ms == 0 {
		return ""
	}
	return time.UnixMilli(ms).UTC().Format("2006-01-02T15:04:05")
}

func truncate(s string, max int) string {
	if len(s) <= max {
		return s
	}
	return s[:max-3] + "..."
}
