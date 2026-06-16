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

// chatMentionCompleter provides auto-completion for chat mode,
// including slash commands and @member_name mentions.
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
// and completes @member_name when the current word starts with '@'.
//
// readline contract: offset is the number of shared characters before pos
// that should be kept; candidates are the suffixes to append after those
// shared characters.
// Example: Do("@d", 2) for member "dawson" => ["awson "], 2
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
		if line[i] == ' ' || line[i] == '\t' {
			break
		}
		wordStart = i
	}
	wordRunes := line[wordStart:pos]
	word := string(wordRunes)

	if !strings.HasPrefix(word, "@") {
		return nil, 0
	}

	mentionPrefix := strings.ToLower(strings.TrimPrefix(word, "@"))
	members := c.membersGetter()
	var candidates [][]rune
	seen := make(map[string]bool)

	for _, m := range members {
		name, _ := m["member_name"].(string)
		if name == "" || seen[name] {
			continue
		}
		seen[name] = true
		if mentionPrefix == "" || strings.HasPrefix(strings.ToLower(name), mentionPrefix) {
			// Return only the suffix after the already-typed prefix.
			suffix := name[len(mentionPrefix):] + " "
			candidates = append(candidates, []rune(suffix))
		}
	}

	// Also suggest @all.
	if mentionPrefix == "" || strings.HasPrefix("all", mentionPrefix) {
		suffix := "all"[len(mentionPrefix):] + " "
		candidates = append(candidates, []rune(suffix))
	}

	return candidates, len(wordRunes)
}
