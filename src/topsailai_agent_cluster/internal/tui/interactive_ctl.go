package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// ctlOperationPrefix marks a standard provider control operation. The prefix is
// the whole routing rule: an operation carrying it is a provider control action,
// so the Endpoint advertises each action as its own capability and the Server
// never needs to know which actions exist.
const ctlOperationPrefix = "ctl."

// ctlUsage is the uniform usage message for the command.
const ctlUsage = "usage: ctl <action> [json]"

// ctlActionNames returns the advertised control actions in stable order.
//
// The list is derived from the Endpoint's own capability descriptor rather than
// from a hardcoded table, so the prompt can never offer an action the Endpoint
// does not support and a newly advertised action needs no client change.
func ctlActionNames(descriptor protocol.CapabilityDescriptor) []string {
	names := make([]string, 0, len(descriptor.Capabilities))
	for _, capability := range descriptor.Capabilities {
		if !strings.HasPrefix(capability.Name, ctlOperationPrefix) {
			continue
		}
		names = append(names, strings.TrimPrefix(capability.Name, ctlOperationPrefix))
	}
	sort.Strings(names)
	return names
}

// ctlPayload validates the optional payload argument.
//
// A control action takes a JSON object, so an omitted payload becomes the empty
// object and a supplied payload must already be an object. A bare scalar is
// rejected instead of being wrapped, because the Endpoint validates the payload
// against the advertised schema and a silent wrapper would hide the mistake.
func ctlPayload(text string) (json.RawMessage, error) {
	trimmed := strings.TrimSpace(text)
	if trimmed == "" {
		return json.RawMessage(`{}`), nil
	}
	if !strings.HasPrefix(trimmed, "{") || !json.Valid([]byte(trimmed)) {
		return nil, fmt.Errorf("payload must be a JSON object")
	}
	return json.RawMessage(trimmed), nil
}

// parseCtlArguments splits the action and the optional payload.
func parseCtlArguments(rest string) (string, json.RawMessage, error) {
	trimmed := strings.TrimSpace(rest)
	if trimmed == "" {
		return "", nil, fmt.Errorf("%s", ctlUsage)
	}
	action, payloadText := trimmed, ""
	if index := strings.IndexAny(trimmed, " \t"); index >= 0 {
		action, payloadText = trimmed[:index], trimmed[index+1:]
	}
	if action == "" || strings.HasPrefix(action, "-") {
		return "", nil, fmt.Errorf("%s", ctlUsage)
	}
	payload, err := ctlPayload(payloadText)
	if err != nil {
		return "", nil, err
	}
	return action, payload, nil
}

// promptCtlAction renders the advertised actions and reads one choice.
//
// The operator may answer with the number, the action name, or an empty line to
// cancel. An empty answer cancels instead of selecting the first action, because
// a control action is a mutating request and must never be chosen by accident.
func promptCtlAction(parent context.Context, api InteractiveAPI, state *interactiveState, lines <-chan lineReadResult, out io.Writer, options InteractiveOptions) (string, error) {
	ctx, cancel := commandContext(parent)
	defer cancel()
	descriptor, err := api.GetCapabilities(ctx, state.EndpointID)
	if err != nil {
		return "", fmt.Errorf("capability query failed for endpoint %q: %w", state.EndpointID, err)
	}
	names := ctlActionNames(descriptor)
	if len(names) == 0 {
		return "", fmt.Errorf("endpoint %q advertises no control actions", state.EndpointID)
	}
	if _, err := fmt.Fprintln(out, "Control actions:"); err != nil {
		return "", err
	}
	for index, name := range names {
		if _, err := fmt.Fprintf(out, "  %d. %s\n", index+1, name); err != nil {
			return "", err
		}
	}
	if _, err := fmt.Fprintln(out, "Enter a number or an action name; empty cancels."); err != nil {
		return "", err
	}
	markRecoverablePromptFailure(parent)
	answer, err := readStartAnswer(parent, lines, "ctl.action> ")
	if err != nil {
		return "", err
	}
	trimmed := strings.TrimSpace(answer)
	if trimmed == "" {
		return "", fmt.Errorf("ctl cancelled")
	}
	for index, name := range names {
		if trimmed == fmt.Sprintf("%d", index+1) || trimmed == name {
			return name, nil
		}
	}
	return "", fmt.Errorf("unknown control action %q; %s", trimmed, ctlUsage)
}

// interactiveCtl prepares, confirms and submits one provider control action.
//
// The action is a mutating request, so it goes through the same confirmation and
// capability revalidation path as every other mutating interactive command. The
// operation name is the advertised ctl.<action> spelling, so the Endpoint matches
// it against its own descriptor and the Server never interprets the action.
func interactiveCtl(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := state.requireUsable(); err != nil {
		return err
	}
	// A bare command line is the interactive prompt form, so the action is read
	// from the rendered advertised list instead of being reported as a usage
	// error. A supplied action is parsed directly, because the operator already
	// named what to send.
	action, payload := "", json.RawMessage(`{}`)
	var err error
	if strings.TrimSpace(rest) == "" {
		action, err = promptCtlAction(parent, api, state, lines, out, options)
	} else {
		action, payload, err = parseCtlArguments(rest)
	}
	if err != nil {
		return err
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	_, _, session, err := findSelected(ctx, api, state)
	if err != nil {
		return err
	}
	return interactiveConfirmedAction(parent, api, state, ctlOperationPrefix+action, "ctl "+action, confirmationTargetFor(*session), session.Generation, payload, lines, out, trustedOut, options, nil, nil)
}

// CtlPayload validates one non-interactive control payload.
func CtlPayload(text string) (json.RawMessage, error) {
	return ctlPayload(text)
}

// CtlOperation returns the advertised operation name for one action.
func CtlOperation(action string) (string, error) {
	trimmed := strings.TrimSpace(action)
	if trimmed == "" || strings.HasPrefix(trimmed, "-") {
		return "", fmt.Errorf("%s", ctlUsage)
	}
	return ctlOperationPrefix + trimmed, nil
}
