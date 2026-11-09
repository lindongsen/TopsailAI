package tui

import (
	"context"
	"fmt"
	"io"
	"strings"
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
	err := interactiveList(ctx, api, state, "", false, false, out, errOut, color)
	controller.clearCancel()
	cancel()
	if controller.takeCommandInterrupted() {
		_, writeErr := fmt.Fprintln(errOut, "interrupted")
		return writeErr
	}
	if err == nil {
		return writeStartupGuide(out, color)
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

// startupGuideSegments derives the guide's entries from startupGuide itself, so
// the styled and plain forms can never drift apart.
var startupGuideSegments = strings.Split(startupGuide, " | ")

// writeStartupGuide renders the startup hint, colouring each command key and
// dimming its description. With colour disabled it emits the exact plain
// startupGuide string so redirected output stays byte-identical.
func writeStartupGuide(out io.Writer, policy ColorPolicy) error {
	if !policy.Enabled {
		_, err := io.WriteString(out, startupGuide+"\n")
		return err
	}
	for i, segment := range startupGuideSegments {
		if i > 0 {
			if err := writeStyled(out, ansiDim, " | ", policy); err != nil {
				return err
			}
		}
		key, description, found := strings.Cut(segment, ": ")
		if !found {
			if err := writeStyled(out, ansiBoldCyan, segment, policy); err != nil {
				return err
			}
			continue
		}
		if err := writeStyled(out, ansiBoldCyan, key, policy); err != nil {
			return err
		}
		if err := writeStyled(out, ansiDim, ": ", policy); err != nil {
			return err
		}
		if err := writeStyled(out, ansiCyan, description, policy); err != nil {
			return err
		}
	}
	_, err := io.WriteString(out, "\n")
	return err
}
