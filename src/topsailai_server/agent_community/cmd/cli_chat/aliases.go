// Package main provides legacy command aliases for the ACS chat CLI.
package main

import "strings"

var legacyAliases = map[string]string{
	"/group:list":  "/group list",
	"/group:create": "/group create",
	"/group:enter": "/chat",
	"/group:leave": "/group leave",
	"/member:list": "/member list",
	"/member:add":  "/member add",
	"/help":        "/help",
}

// expandAlias converts legacy colon-style commands to the new space style.
func expandAlias(line string) string {
	line = strings.TrimSpace(line)
	if alias, ok := legacyAliases[line]; ok {
		return alias
	}
	return line
}
