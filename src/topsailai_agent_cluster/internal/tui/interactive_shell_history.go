package tui

import (
	"context"
	"fmt"
	"io"
	"strconv"
	"strings"
)

// shellHistoryLimit bounds the bare-prefix menu. Ten is the number the operator
// asked for, and it is a constant rather than a setting because the menu is a
// convenience over the recall list, not a second configuration surface.
const shellHistoryLimit = 10

// shellHistoryPrompt is the question shown under the numbered list. It names the
// cancel form explicitly, because an empty answer cancels and an operator who
// does not know that may type a number they did not intend.
const shellHistoryPrompt = "Choose a command number; empty/cancel cancels."

// shellHistoryCandidates selects the commands the bare-prefix menu offers.
//
// The recall list holds every REPL command, so two filters are load-bearing:
//
//   - Only prefixed lines are offered, because the menu exists to run an
//     allowlisted command and an ordinary REPL command would be dispatched as
//     one instead.
//   - A bare prefix is dropped, because selecting it would reopen this menu and
//     the operator would be unable to leave it by choosing a row.
//
// The filter runs before the ten-item cut. Filtering after the cut would return
// fewer than ten rows whenever ordinary commands occupy the tail of the list,
// which is the common case because most REPL input is not a shell command.
//
// The result is newest first, so row 1 is the command the operator ran most
// recently. The recall list is oldest first, so the order is reversed here rather
// than in the renderer, and the renderer and the resolver therefore share one
// slice in one order.
func shellHistoryCandidates(commands []string) []string {
	candidates := make([]string, 0, shellHistoryLimit)
	for index := len(commands) - 1; index >= 0 && len(candidates) < shellHistoryLimit; index-- {
		line := strings.TrimSpace(commands[index])
		if !isShellLine(line) {
			continue
		}
		// A bare prefix carries no program, so it is not a command to offer.
		if _, err := shellArgv(line); err != nil {
			continue
		}
		candidates = append(candidates, line)
	}
	return candidates
}

// promptShellHistory prints the numbered candidates and reads one answer.
//
// The answer is resolved against the same slice that was printed, so a number can
// never address a command that was not shown. An empty answer cancels and returns
// an empty line, which the caller treats as "nothing to do" rather than as an
// error: cancelling a prompt is a decision, not a failure.
//
// The prompt runs on the parent context, because it waits for a human and a
// command budget would expire while the operator is still reading the list. Only
// the command that follows is bounded.
func promptShellHistory(ctx context.Context, commands []string, lines <-chan lineReadResult, out, trustedOut io.Writer, color ColorPolicy) (string, error) {
	candidates := shellHistoryCandidates(commands)
	if len(candidates) == 0 {
		return "", fmt.Errorf("%s no earlier command was recorded; type %s<program> [arguments...] to run one", shellUsage, shellPrefix)
	}
	for index, candidate := range candidates {
		if _, err := fmt.Fprintf(out, "%d. %s\n", index+1, sanitizeInlineText(candidate)); err != nil {
			return "", err
		}
	}
	if _, err := fmt.Fprintln(out, shellHistoryPrompt); err != nil {
		return "", err
	}
	echo := func(answer string) string {
		return RenderAnswerEcho(shellHistoryEchoLabel(candidates, answer), color)
	}
	// A failed answer cancels only this command. Without the marker the REPL
	// classifies the failure as a wizard abort and terminates the whole session,
	// so one unusable answer would end an otherwise healthy session.
	markRecoverablePromptFailure(ctx)
	answer, ok := nextPromptLineWithEcho(ctx, lines, trustedOut, echo)
	if !ok || answer.overflow || answer.err != nil {
		return "", nil
	}
	return resolveShellHistoryChoice(candidates, answer.line)
}

// resolveShellHistoryChoice maps one answer onto a printed candidate.
//
// A number is the only accepted selection form. Any other text is an error rather
// than a command, because treating it as a command would run something the
// operator did not select from the list they were shown.
func resolveShellHistoryChoice(candidates []string, answer string) (string, error) {
	choice := strings.TrimSpace(answer)
	if choice == "" || strings.EqualFold(choice, "cancel") {
		return "", nil
	}
	number, err := strconv.Atoi(choice)
	if err != nil || number < 1 || number > len(candidates) {
		return "", fmt.Errorf("choose a number between 1 and %d, or leave the answer empty to cancel", len(candidates))
	}
	return candidates[number-1], nil
}

// shellHistoryEchoLabel names the command a number selected, so the choice stays
// readable after the list has scrolled away.
func shellHistoryEchoLabel(candidates []string, answer string) string {
	choice := strings.TrimSpace(answer)
	if choice == "" || strings.EqualFold(choice, "cancel") {
		return ""
	}
	number, err := strconv.Atoi(choice)
	if err != nil || number < 1 || number > len(candidates) {
		return ""
	}
	return candidates[number-1]
}
