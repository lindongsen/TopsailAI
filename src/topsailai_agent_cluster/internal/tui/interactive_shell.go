package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// shellPrefix marks a line as an allowlisted command instead of a REPL command.
// It is an input-prefix form, not a command word: the line is recognised before
// the command word is split, so "!git status" never reaches the dispatcher as a
// command named "!git".
const shellPrefix = "!"

// shellUsage is the uniform usage message for the prefix form.
const shellUsage = "usage: !<program> [arguments...]"

// isShellLine reports whether a REPL line is an allowlisted command.
func isShellLine(line string) bool {
	return strings.HasPrefix(strings.TrimSpace(line), shellPrefix)
}

// tokenizeCommandLine splits one command line into an argv array.
//
// The result is an argv array, never a command string, because the Endpoint must
// not parse or split a string: doing so would reintroduce shell semantics that
// the allowlist cannot reason about. Quotes group one token and are removed, so
// an argument containing a space stays one argument. No other shell feature is
// interpreted: there is no variable expansion, globbing, redirection, pipeline
// or command substitution, so a token is always literal text.
func tokenizeCommandLine(text string) ([]string, error) {
	var argv []string
	var word strings.Builder
	var quote rune
	started := false
	for _, character := range text {
		if quote != 0 {
			if character == quote {
				quote = 0
				continue
			}
			word.WriteRune(character)
			continue
		}
		switch {
		case character == '\'' || character == '"':
			quote = character
			started = true
		case character == ' ' || character == '\t':
			if started {
				argv = append(argv, word.String())
				word.Reset()
				started = false
			}
		default:
			started = true
			word.WriteRune(character)
		}
	}
	if quote != 0 {
		return nil, fmt.Errorf("unterminated quote in command line")
	}
	if started {
		argv = append(argv, word.String())
	}
	if len(argv) == 0 {
		return nil, fmt.Errorf("%s", shellUsage)
	}
	return argv, nil
}

// shellArgv converts one REPL line into the argv array of a command.exec request.
// The prefix is removed before tokenizing, so the program name is the first
// token and never carries the prefix.
func shellArgv(line string) ([]string, error) {
	trimmed := strings.TrimSpace(line)
	if !strings.HasPrefix(trimmed, shellPrefix) {
		return nil, fmt.Errorf("%s", shellUsage)
	}
	return tokenizeCommandLine(strings.TrimPrefix(trimmed, shellPrefix))
}

// commandExecPayload encodes one argv array as the standard command.exec payload.
// The payload carries the array, so the Endpoint never receives a command string.
func commandExecPayload(argv []string) (json.RawMessage, error) {
	request := protocol.CommandExecRequest{Argv: argv}
	if err := request.Validate(); err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(request)
	if err != nil {
		return nil, fmt.Errorf("encode payload: %w", err)
	}
	return json.RawMessage(encoded), nil
}

// ExecPayload encodes one argv array for the standalone exec command.
//
// The standalone surface receives an already-split argv array from the shell, so
// it never re-tokenizes: re-splitting a string would reintroduce the shell
// semantics the allowlist cannot reason about.
func ExecPayload(argv []string) (json.RawMessage, error) {
	return commandExecPayload(argv)
}

// runShellCommand executes one allowlisted command in the selected session.
//
// The command is one-shot: it submits one command.exec intent, waits for the
// durable result and renders one bounded snapshot. It never starts a periodic
// refresh, because the design forbids periodic stdout snapshot polling.
//
// The allowlist decision belongs to the Endpoint policy hook, so this path never
// decides policy locally. A denied command therefore surfaces as a durable
// rejected receipt with policy_denied, which is the same evidence an operator
// would see for any other admission refusal.
func runShellCommand(parent context.Context, api InteractiveAPI, state *interactiveState, line string, out io.Writer, options InteractiveOptions) error {
	if err := state.requireUsable(); err != nil {
		return err
	}
	argv, err := shellArgv(line)
	if err != nil {
		return err
	}
	payload, err := commandExecPayload(argv)
	if err != nil {
		return err
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	_, _, session, err := findSelected(ctx, api, state)
	if err != nil {
		return err
	}
	runner := CommandRunner{API: api, Policy: InteractivePolicy, NewID: func() string { return fmt.Sprintf("cli-%d", time.Now().UnixNano()) }}
	actionRequest := ActionRequest{
		Operation:           protocol.OperationCommandExec,
		OperationLabel:      "exec",
		EndpointID:          state.EndpointID,
		ResourceID:          session.ClusterSessionID,
		ProviderDisplayName: session.ProviderDisplayName,
		ProviderSessionID:   session.ProviderSessionID,
		ProviderGeneration:  session.ProviderGeneration,
		Payload:             payload,
		Confirmed:           true,
		WaitTimeoutMS:       options.WaitTimeoutMS,
	}
	progress := NewActionProgress(options.ProgressWriter, actionRequest)
	intent, err := runner.PrepareAction(ctx, actionRequest)
	if err != nil {
		return err
	}
	state.commandID = intent.CommandID
	action, err := runner.SubmitAction(ctx, intent)
	if err != nil {
		return fmt.Errorf("command %s result unknown; use status %s to query; %w", intent.CommandID, intent.CommandID, err)
	}
	state.commandID = action.CommandID
	result, err := runner.WaitActionWithProgress(ctx, action, intent.Budget, progress)
	if err != nil {
		return fmt.Errorf("command %s status unavailable; use status %s to query; %w", state.commandID, state.commandID, err)
	}
	return renderCommandExecResult(out, result, options.Color)
}

// renderCommandExecResult writes the durable receipt and, when the command
// actually ran, the bounded output snapshot.
//
// The snapshot is written through the trusted writer path used by logs, because
// the stored document must stay faithful to what the provider returned; the
// terminal boundary sanitizes it. Provider output is untrusted, so every escape
// sequence is stripped here and SGR colour survives only when the colour policy
// is enabled. A rejected or unconfirmed command prints no output section, so a
// refusal is never mistaken for an empty result.
func renderCommandExecResult(out io.Writer, result map[string]any, policy ColorPolicy) error {
	if _, err := fmt.Fprintf(out, "CommandID: %s\nStatus: %s\nDeliveryBoundary: %s\nEffectCertainty: %s\nErrorCode: %s\n",
		valueString(result, "command_id", "CommandID"),
		valueString(result, "status", "Status"),
		valueString(result, "delivery_boundary", "DeliveryBoundary"),
		valueString(result, "effect_certainty", "EffectCertainty"),
		valueString(result, "error_code", "ErrorCode")); err != nil {
		return err
	}
	receipt := ReceiptForStatus(result)
	if receipt.ProviderResponse == "" {
		return nil
	}
	var snapshot protocol.CommandExecResult
	if err := json.Unmarshal([]byte(receipt.ProviderResponse), &snapshot); err != nil {
		// An unreadable document is reported as a diagnostic instead of being
		// silently dropped, so the operator knows output exists but is unusable.
		_, writeErr := fmt.Fprintf(out, "output unavailable: %v\n", err)
		return writeErr
	}
	if _, err := fmt.Fprintf(out, "exit_code: %d\ntruncated: %t\n", snapshot.ExitCode, snapshot.Truncated); err != nil {
		return err
	}
	if snapshot.Stdout != "" {
		if _, err := fmt.Fprintf(out, "stdout:\n%s\n", filterProviderOutput(snapshot.Stdout, policy)); err != nil {
			return err
		}
	}
	if snapshot.Stderr != "" {
		if _, err := fmt.Fprintf(out, "stderr:\n%s\n", filterProviderOutput(snapshot.Stderr, policy)); err != nil {
			return err
		}
	}
	return nil
}

// RenderCommandExecResult renders one command.exec receipt and its bounded output
// snapshot for the standalone surface.
//
// The interactive form and the standalone form share this renderer, so the two
// surfaces cannot disagree about which receipt fields are shown or how provider
// output is sanitized.
func RenderCommandExecResult(out io.Writer, result map[string]any, policy ColorPolicy) error {
	return renderCommandExecResult(out, result, policy)
}
