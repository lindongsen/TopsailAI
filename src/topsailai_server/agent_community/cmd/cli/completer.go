// Package main provides tab auto-completion for the ACS CLI terminal.
package main

import (
	"strings"
	"unicode"

	"github.com/chzyer/readline"
)

// newNormalCompleter returns a readline PrefixCompleter for normal mode commands.
func newNormalCompleter() readline.PrefixCompleterInterface {
	return readline.NewPrefixCompleter(
		readline.PcItem("/login"),
		readline.PcItem("/logout"),
		readline.PcItem("/account:me"),
		readline.PcItem("/account:create"),
		readline.PcItem("/account:list"),
		readline.PcItem("/account:get"),
		readline.PcItem("/account:update"),
		readline.PcItem("/account:delete"),
		readline.PcItem("/account:password"),
		readline.PcItem("/account:session"),
		readline.PcItem("/api-key:create"),
		readline.PcItem("/api-key:list"),
		readline.PcItem("/api-key:delete"),
		readline.PcItem("/group:list"),
		readline.PcItem("/group:create"),
		readline.PcItem("/group:enter"),
		readline.PcItem("/group:join"),
		readline.PcItem("/group:update"),
		readline.PcItem("/group:delete"),
		readline.PcItem("/member:list"),
		readline.PcItem("/member:add"),
		readline.PcItem("/member:remove"),
		readline.PcItem("/member:update"),
		readline.PcItem("/message:list"),
		readline.PcItem("/message:update"),
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

// chatMentionCompleter provides auto-completion for chat mode,
// including slash commands and @member_id/@member_name mentions.
// It matches against both member_id and member_name, but always inserts the
// unambiguous member_id so duplicate display names do not collide.
type chatMentionCompleter struct {
	cmdCompleter  readline.PrefixCompleterInterface
	membersGetter func() []map[string]interface{}
}

// newChatMentionCompleter creates a chat completer that supports @mentions.
func newChatMentionCompleter(membersGetter func() []map[string]interface{}) readline.AutoCompleter {
	return &chatMentionCompleter{
		cmdCompleter:  newChatCompleter(),
		membersGetter: membersGetter,
	}
}

// Do implements readline.AutoCompleter.
// It completes slash commands when the line starts with '/',
// and completes @member_id/@member_name when the current word starts with '@'.
//
// For @mentions, the entire current word (including '@') is replaced with the
// selected member ID to avoid ambiguity when multiple members share the same
// display name.
func (c *chatMentionCompleter) Do(line []rune, pos int) ([][]rune, int) {
	if len(line) == 0 || pos == 0 {
		return nil, 0
	}

	// Delegate slash commands to the prefix completer.
	if line[0] == '/' {
		return c.cmdCompleter.Do(line, pos)
	}

	// Find the current word being typed (from last whitespace to cursor).
	wordStart := pos
	for i := pos - 1; i >= 0; i-- {
		if unicode.IsSpace(rune(line[i])) {
			wordStart = i + 1
			break
		}
		wordStart = i
	}

	wordRunes := line[wordStart:pos]
	if len(wordRunes) == 0 || wordRunes[0] != '@' {
		return nil, 0
	}

	mentionPrefix := strings.ToLower(string(wordRunes[1:]))
	members := c.membersGetter()
	var candidates [][]rune
	seen := make(map[string]bool)

	for _, m := range members {
		name, _ := m["member_name"].(string)
		id, _ := m["member_id"].(string)
		if id == "" || seen[id] {
			continue
		}
		seen[id] = true

		nameLower := strings.ToLower(name)
		idLower := strings.ToLower(id)

		// Match by member_id prefix or member_name prefix.
		if strings.HasPrefix(idLower, mentionPrefix) || strings.HasPrefix(nameLower, mentionPrefix) {
			candidates = append(candidates, []rune("@"+id+" "))
		}
	}

	// Also suggest @all.
	if mentionPrefix == "" || strings.HasPrefix("all", mentionPrefix) {
		candidates = append(candidates, []rune("@all "))
	}

	if len(candidates) == 0 {
		return nil, 0
	}

	// Replace the entire current word (including '@') with the candidate.
	return candidates, wordStart
}
