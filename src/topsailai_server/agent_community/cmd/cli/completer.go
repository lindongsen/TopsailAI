// Package main provides tab auto-completion for the ACS CLI terminal.
package main

import (
	"strings"

	"github.com/chzyer/readline"
)

// newNormalCompleter returns a readline PrefixCompleter for normal mode commands.
func newNormalCompleter() readline.PrefixCompleterInterface {
	return readline.NewPrefixCompleter(
		readline.PcItem("/group:list"),
		readline.PcItem("/group:create"),
		readline.PcItem("/group:enter"),
		readline.PcItem("/group:update"),
		readline.PcItem("/group:delete"),
		readline.PcItem("/member:list"),
		readline.PcItem("/member:add"),
		readline.PcItem("/member:remove"),
		readline.PcItem("/member:update"),
		readline.PcItem("/message:list"),
		readline.PcItem("/message:edit"),
		readline.PcItem("/message:delete"),
		readline.PcItem("/help"),
		readline.PcItem("/exit"),
		readline.PcItem("exit"),
		readline.PcItem("quit"),
		readline.PcItem("help"),
	)
}

// newChatCompleter returns a readline PrefixCompleter for chat mode commands.
func newChatCompleter() readline.PrefixCompleterInterface {
	return readline.NewPrefixCompleter(
		readline.PcItem("/members"),
		readline.PcItem("/help"),
		readline.PcItem("/exit"),
		readline.PcItem("exit"),
		readline.PcItem("quit"),
	)
}

// completerFromCommands builds a PrefixCompleter from a slice of command strings.
func completerFromCommands(commands []string) readline.PrefixCompleterInterface {
	items := make([]readline.PrefixCompleterInterface, 0, len(commands))
	for _, cmd := range commands {
		items = append(items, readline.PcItem(cmd))
	}
	return readline.NewPrefixCompleter(items...)
}

// filterCommands returns commands that start with the given prefix.
func filterCommands(prefix string, commands []string) []string {
	var result []string
	lowerPrefix := strings.ToLower(prefix)
	for _, cmd := range commands {
		if strings.HasPrefix(strings.ToLower(cmd), lowerPrefix) {
			result = append(result, cmd)
		}
	}
	return result
}
