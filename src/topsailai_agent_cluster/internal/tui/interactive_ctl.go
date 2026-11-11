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

// ctlInteractiveUsage is the usage message for the interactive spelling.
//
// The interactive form takes guided key=value parameters, never a JSON object:
// the operator is a human at a prompt, so the surface must not require them to
// compose JSON by hand. The standalone spelling keeps its explicit JSON payload
// and therefore has its own usage message.
const ctlInteractiveUsage = "usage: ctl <action> [key=value ...]"

// ctlDottedUsage is the usage message for the dotted spelling without an action.
const ctlDottedUsage = "usage: ctl.<action> [key=value ...]"

// ctlStandaloneUsage is the usage message for the non-interactive spelling.
const ctlStandaloneUsage = "usage: ctl <endpoint-id> <resource-id> <action> [json] [generation]"

// ctlDottedAction reports whether a command word is the dotted control spelling
// and returns the action it names.
//
// The dotted spelling is a form of the ctl command, not a second command: it
// carries the action inside the command word so the operator skips the action
// prompt. The prefix is disjoint from every registered command word and alias,
// because none of them contains a dot, so it can never shadow another command.
func ctlDottedAction(word string) (string, bool) {
	if !strings.HasPrefix(word, ctlOperationPrefix) {
		return "", false
	}
	return strings.TrimPrefix(word, ctlOperationPrefix), true
}

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

// ctlPayload validates one explicit JSON payload argument.
//
// This is the standalone contract: a script supplies a JSON object, so an
// omitted payload becomes the empty object and a supplied payload must already be
// an object. A bare scalar is rejected instead of being wrapped, because the
// Endpoint validates the payload against the advertised schema and a silent
// wrapper would hide the mistake. The interactive surface never calls this
// function, because a human at a prompt must not have to compose JSON.
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

// ctlParameterPayload builds the payload object from guided key=value parameters.
//
// The interactive surface collects parameters one pair at a time instead of
// asking for a JSON document, so the operator never has to know JSON syntax. A
// value is typed by its own shape: a quoted value is always a literal string, and
// an unquoted value that parses as a JSON scalar keeps that type, so
// timeout_seconds=300 sends a number and default=continue sends a string. An
// empty parameter list sends the empty object, which is what an action with no
// arguments expects.
//
// A raw JSON object is rejected rather than accepted as a convenience: accepting
// both forms would leave two payload syntaxes on one surface, and the guided form
// is the one the interactive surface promises.
func ctlParameterPayload(parameters []string) (json.RawMessage, error) {
	if len(parameters) == 0 {
		return json.RawMessage(`{}`), nil
	}
	payload := make(map[string]json.RawMessage, len(parameters))
	for _, parameter := range parameters {
		key, value, found := strings.Cut(parameter, "=")
		key = strings.TrimSpace(key)
		if !found || key == "" {
			return nil, fmt.Errorf("parameter %q must be key=value", parameter)
		}
		if _, duplicate := payload[key]; duplicate {
			return nil, fmt.Errorf("parameter %q is supplied twice", key)
		}
		encoded, err := ctlParameterValue(value)
		if err != nil {
			return nil, fmt.Errorf("parameter %q: %w", key, err)
		}
		payload[key] = encoded
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("encode control parameters: %w", err)
	}
	return encoded, nil
}

// ctlParameterValue encodes one guided parameter value.
//
// A quoted value is unquoted and sent as a string, so an operator can force a
// literal that would otherwise be read as a number or a boolean. An unquoted
// value keeps its JSON scalar type when it parses as one, and is otherwise sent
// as a string, so a plain word such as continue needs no quoting.
func ctlParameterValue(value string) (json.RawMessage, error) {
	trimmed := strings.TrimSpace(value)
	if len(trimmed) >= 2 && strings.HasPrefix(trimmed, `"`) && strings.HasSuffix(trimmed, `"`) {
		var literal string
		if err := json.Unmarshal([]byte(trimmed), &literal); err != nil {
			return nil, fmt.Errorf("quoted value is not a valid string: %w", err)
		}
		encoded, err := json.Marshal(literal)
		if err != nil {
			return nil, fmt.Errorf("encode quoted value: %w", err)
		}
		return encoded, nil
	}
	if trimmed != "" && json.Valid([]byte(trimmed)) {
		var scalar any
		if err := json.Unmarshal([]byte(trimmed), &scalar); err == nil {
			switch scalar.(type) {
			case bool, float64, nil:
				return json.RawMessage(trimmed), nil
			}
		}
	}
	encoded, err := json.Marshal(trimmed)
	if err != nil {
		return nil, fmt.Errorf("encode value: %w", err)
	}
	return encoded, nil
}

// parseCtlArguments splits the action and the guided parameters.
//
// The action is the first token and every remaining token is one key=value
// parameter, so the interactive surface never accepts a JSON document.
func parseCtlArguments(rest string) (string, json.RawMessage, error) {
	fields := strings.Fields(rest)
	if len(fields) == 0 {
		return "", nil, fmt.Errorf("%s", ctlInteractiveUsage)
	}
	action := fields[0]
	if strings.HasPrefix(action, "-") {
		return "", nil, fmt.Errorf("%s", ctlInteractiveUsage)
	}
	payload, err := ctlParameterPayload(fields[1:])
	if err != nil {
		return "", nil, err
	}
	return action, payload, nil
}

// parseCtlDottedArguments validates the guided parameters of the dotted spelling.
//
// The action already came from the command word, so every remaining token is one
// key=value parameter. A second bare word is rejected as a malformed parameter
// rather than being reinterpreted as another action, so the dotted form can never
// silently drop an argument the operator typed.
func parseCtlDottedArguments(action, rest string) (string, json.RawMessage, error) {
	if action == "" || strings.HasPrefix(action, "-") {
		return "", nil, fmt.Errorf("%s", ctlDottedUsage)
	}
	payload, err := ctlParameterPayload(strings.Fields(rest))
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
func promptCtlAction(parent context.Context, api InteractiveAPI, state *interactiveState, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) (string, error) {
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
	// Only a resolved selection echoes, because the echo must name the action
	// that will actually be sent. An empty answer cancels and an unknown answer
	// is rejected, so neither echoes: an echo would claim a selection that was
	// never made. The echo resolves through the same function that selects the
	// action, so the echoed name and the returned name cannot disagree.
	echo := func(answer string) string {
		name, ok := resolveCtlActionName(names, answer)
		if !ok {
			return ""
		}
		return RenderAnswerEcho(name, options.Color)
	}
	markRecoverablePromptFailure(parent)
	answer, err := readStartAnswerWithEcho(parent, lines, trustedOut, echo, "ctl.action> ")
	if err != nil {
		return "", err
	}
	name, ok := resolveCtlActionName(names, answer)
	if ok {
		return name, nil
	}
	trimmed := strings.TrimSpace(answer)
	if trimmed == "" {
		return "", fmt.Errorf("ctl cancelled")
	}
	return "", fmt.Errorf("unknown control action %q; %s", trimmed, ctlInteractiveUsage)
}

// resolveCtlActionName maps one answer to an advertised action name.
//
// The operator may answer with the number or the exact name. The same function
// resolves the answer for selection and for the echo, so the name shown beside
// the answer is always the name that is returned. An empty or unknown answer
// reports false, which is what keeps a cancel or a rejected answer from echoing.
func resolveCtlActionName(names []string, answer string) (string, bool) {
	trimmed := strings.TrimSpace(answer)
	if trimmed == "" {
		return "", false
	}
	for index, name := range names {
		if trimmed == fmt.Sprintf("%d", index+1) || trimmed == name {
			return name, true
		}
	}
	return "", false
}

// promptCtlParameters guides the operator through the parameters of one action.
//
// The interactive surface never asks for a JSON document. The operator types
// key=value pairs separated by spaces, and an empty answer sends the empty
// object, which is what an action without arguments expects. The prompt is
// always offered when no parameter was supplied on the command line, because the
// Endpoint advertises no per-action field schema, so the client cannot know which
// actions take arguments and must not guess.
func promptCtlParameters(parent context.Context, action string, lines <-chan lineReadResult, out io.Writer) (json.RawMessage, error) {
	if _, err := fmt.Fprintf(out, "Parameters for %s: key=value pairs separated by spaces; empty sends none.\n", sanitizeInlineText(action)); err != nil {
		return nil, err
	}
	markRecoverablePromptFailure(parent)
	answer, err := readStartAnswer(parent, lines, "ctl.param> ")
	if err != nil {
		return nil, err
	}
	return ctlParameterPayload(strings.Fields(answer))
}

// ctlParameterSummary renders one payload as readable key=value pairs.
//
// The confirmation gate exists so the operator verifies what will be sent, so the
// parameters are echoed in the same guided form they were entered in rather than
// as a JSON document. Keys are sorted so the echo is stable across runs.
func ctlParameterSummary(payload json.RawMessage) string {
	var decoded map[string]json.RawMessage
	if err := json.Unmarshal(payload, &decoded); err != nil || len(decoded) == 0 {
		return "none"
	}
	keys := make([]string, 0, len(decoded))
	for key := range decoded {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	pairs := make([]string, 0, len(keys))
	for _, key := range keys {
		value := strings.Trim(string(decoded[key]), `"`)
		pairs = append(pairs, key+"="+sanitizeInlineText(value))
	}
	return strings.Join(pairs, " ")
}

// ctlInvocation is one parsed control command line.
//
// The dotted spelling carries the action inside the command word, so the action
// prompt is skipped and the whole remainder is the guided parameters. The spaced
// spelling keeps the action as the first argument, and a bare line keeps the
// action prompt.
type ctlInvocation struct {
	dotted bool
	action string
	rest   string
	// spelling is the command word the operator typed, so the confirmation gate
	// and the progress label echo "control" when that is what was typed. The
	// protocol operation stays the canonical ctl.<action> spelling, because the
	// alias is a CLI convenience and never a second wire identity.
	spelling string
}

// displayName is the command word used in operator-facing text.
func (invocation ctlInvocation) displayName() string {
	if invocation.spelling == "" {
		return "ctl"
	}
	return invocation.spelling
}

// ctlSuppliedParameters reports whether the command line already carried at least
// one guided parameter.
//
// The dotted spelling puts the action in the command word, so any remainder is a
// parameter. The spaced spelling puts the action in the first token, so a second
// token is a parameter. A bare line carries neither.
func ctlSuppliedParameters(invocation ctlInvocation) bool {
	fields := strings.Fields(invocation.rest)
	if invocation.dotted {
		return len(fields) > 0
	}
	return len(fields) > 1
}

// interactiveCtl prepares, confirms and submits one provider control action.
//
// The action is a mutating request, so it goes through the same confirmation and
// capability revalidation path as every other mutating interactive command. The
// operation name is the advertised ctl.<action> spelling, so the Endpoint matches
// it against its own descriptor and the Server never interprets the action.
//
// The interactive surface never asks for a JSON document. The action is resolved
// first, then validated against the advertised capabilities, and only then are the
// parameters collected, so an action the Endpoint does not support fails before
// the operator is asked to type anything for it.
func interactiveCtl(parent context.Context, api InteractiveAPI, state *interactiveState, invocation ctlInvocation, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) error {
	if err := state.requireUsable(); err != nil {
		return err
	}
	action, payload, err := ctlResolveAction(parent, api, state, invocation, lines, out, trustedOut, options)
	if err != nil {
		return err
	}
	// Reject an unadvertised action before any parameter prompt, so the operator
	// never types parameters for an action that cannot be sent.
	if err := ctlPreflightAction(parent, api, state, action); err != nil {
		return err
	}
	if !ctlSuppliedParameters(invocation) {
		payload, err = promptCtlActionParameters(parent, api, state, action, lines, out)
		if err != nil {
			return err
		}
	}
	if _, err := fmt.Fprintf(out, "Parameters: %s\n", ctlParameterSummary(payload)); err != nil {
		return err
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	_, _, session, err := findSelected(ctx, api, state)
	if err != nil {
		return err
	}
	return interactiveConfirmedAction(parent, api, state, ctlOperationPrefix+action, invocation.displayName()+" "+action, confirmationTargetFor(*session), session.ProviderGeneration, payload, lines, out, trustedOut, options, nil, nil)
}

// ctlResolveAction returns the action and the payload the command line already
// determined, prompting for the action when the line names none.
func ctlResolveAction(parent context.Context, api InteractiveAPI, state *interactiveState, invocation ctlInvocation, lines <-chan lineReadResult, out, trustedOut io.Writer, options InteractiveOptions) (string, json.RawMessage, error) {
	switch {
	case invocation.dotted:
		return parseCtlDottedArguments(invocation.action, invocation.rest)
	case strings.TrimSpace(invocation.rest) == "":
		action, err := promptCtlAction(parent, api, state, lines, out, trustedOut, options)
		if err != nil {
			return "", nil, err
		}
		return action, json.RawMessage(`{}`), nil
	default:
		return parseCtlArguments(invocation.rest)
	}
}

// ctlPreflightAction validates one action against the advertised capabilities.
//
// The check runs before the parameter prompt and again inside the shared
// submission path, because the descriptor can change between the two reads. The
// early check exists so the operator is not asked for parameters of an action the
// Endpoint does not advertise.
func ctlPreflightAction(parent context.Context, api InteractiveAPI, state *interactiveState, action string) error {
	ctx, cancel := commandContext(parent)
	defer cancel()
	_, err := PreflightCapability(ctx, api, state.EndpointID, ctlOperationPrefix+action)
	return err
}

// CtlPayload validates one non-interactive control payload.
func CtlPayload(text string) (json.RawMessage, error) {
	return ctlPayload(text)
}

// CtlOperation returns the advertised operation name for one action.
func CtlOperation(action string) (string, error) {
	trimmed := strings.TrimSpace(action)
	if trimmed == "" || strings.HasPrefix(trimmed, "-") {
		return "", fmt.Errorf("%s", ctlStandaloneUsage)
	}
	return ctlOperationPrefix + trimmed, nil
}
