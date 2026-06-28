// Package main provides a status bar for the ACS chat CLI.
package main

import (
	"fmt"
	"strings"
)

// StatusBar renders a compact member status bar for chat mode.
type StatusBar struct {
	maxMembers int
	members    []Member
}

// NewStatusBar creates a new status bar.
func NewStatusBar(maxMembers int) *StatusBar {
	if maxMembers <= 0 {
		maxMembers = 8
	}
	return &StatusBar{maxMembers: maxMembers}
}

// Update refreshes the member list used by the status bar.
func (sb *StatusBar) Update(members []Member) {
	sb.members = members
}

// Render returns the status bar string.
func (sb *StatusBar) Render() string {
	if len(sb.members) == 0 {
		return ""
	}
	var parts []string
	limit := sb.maxMembers
	if len(sb.members) < limit {
		limit = len(sb.members)
	}
	for i := 0; i < limit; i++ {
		m := sb.members[i]
		status := m.MemberStatus
		if status == "" {
			status = "online"
		}
		parts = append(parts, fmt.Sprintf("%s(%s)", m.MemberName, status))
	}
	if len(sb.members) > limit {
		parts = append(parts, fmt.Sprintf("+%d", len(sb.members)-limit))
	}
	return strings.Join(parts, " | ")
}
