package tui

import (
	"context"
	"fmt"
	"io"
)

// startupListHint tells the operator how to retry a failed startup inventory.
const startupListHint = `hint: run "refresh" to retry the inventory`
const startupGuide = "list: view sessions | <n> or cd <n>: select | start: launch agent | help: commands | q: quit"

// runStartupList renders the initial workspace inventory before the first prompt.
// It reuses the manual list path, honors the color policy, and never aborts the
// REPL: a failure is reported on stderr and the workspace scope is preserved.
func runStartupList(parent context.Context, api InteractiveAPI, state *interactiveState, controller *interruptController, out, errOut io.Writer, color ColorPolicy) error {
	ctx, cancel := context.WithCancel(parent)
	controller.setCancel(cancel)
	err := interactiveList(ctx, api, state, "", false, out, errOut, color)
	controller.clearCancel()
	cancel()
	if controller.takeCommandInterrupted() {
		_, writeErr := fmt.Fprintln(errOut, "interrupted")
		return writeErr
	}
	if err == nil {
		_, writeErr := fmt.Fprintln(out, startupGuide)
		return writeErr
	}
	if _, writeErr := fmt.Fprintln(errOut, "error:", err); writeErr != nil {
		return writeErr
	}
	if _, writeErr := fmt.Fprintln(errOut, "usage: refresh"); writeErr != nil {
		return writeErr
	}
	_, writeErr := fmt.Fprintln(errOut, "next:", startupListHint)
	return writeErr
}
