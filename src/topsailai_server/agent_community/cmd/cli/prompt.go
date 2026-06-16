package main

import (
	"fmt"
	"strings"

	"github.com/chzyer/readline"
)

// promptState holds a reference to the CLI state so that prompt-aware output
// functions can locate the currently active readline instance (normal or chat).
var promptState *CLIState

// setPromptState registers the CLI state with the prompt manager.
func setPromptState(s *CLIState) {
	promptState = s
}

// activeReadline returns the readline instance that currently owns the prompt.
// When the user is in chat mode, the chat readline is returned so messages are
// printed above the chat prompt and the chat prompt is redrawn. Otherwise the
// main readline instance is returned.
func activeReadline() *readline.Instance {
	if promptState == nil {
		return nil
	}
	if promptState.chatMode != nil && promptState.chatMode.active && promptState.chatMode.rl != nil {
		return promptState.chatMode.rl
	}
	return promptState.rl
}

// promptPrintln prints a line while keeping the active prompt at the bottom.
func promptPrintln(a ...interface{}) {
	rl := activeReadline()
	if rl != nil {
		rl.Clean()
	}
	fmt.Println(a...)
	if rl != nil {
		rl.Refresh()
	}
}

// promptPrintf prints formatted text while keeping the active prompt at the bottom.
func promptPrintf(format string, a ...interface{}) {
	rl := activeReadline()
	if rl != nil {
		rl.Clean()
	}
	fmt.Printf(format, a...)
	if rl != nil {
		rl.Refresh()
	}
}

// promptPrintLines prints multiple lines while keeping the active prompt at the bottom.
func promptPrintLines(lines ...string) {
	promptPrintln(strings.Join(lines, "\n"))
}
