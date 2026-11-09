package tui

import (
	"context"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// launchEndpointChoices renders the numbered endpoint inventory for the start wizard.
// Endpoint identifiers are long and unstructured, so the wizard shows a numbered
// list and accepts a bare number instead of demanding the identifier.
func launchEndpointChoices(ctx context.Context, api InteractiveAPI, out io.Writer) ([]protocol.Endpoint, error) {
	queryCtx, cancel := commandContext(ctx)
	endpoints, err := api.ListEndpoints(queryCtx)
	cancel()
	if err != nil {
		return nil, err
	}
	if len(endpoints) == 0 {
		return nil, fmt.Errorf("no endpoint is registered; register an endpoint before starting an agent")
	}
	for index, endpoint := range endpoints {
		label := endpoint.DisplayName
		if label == "" {
			label = endpoint.EndpointID
		}
		hostname := endpoint.Hostname
		if hostname == "" {
			hostname = endpoint.EndpointID
		}
		if _, err := fmt.Fprintf(out, "%d. %s / %s / %s\n", index+1, hostname, endpoint.EndpointID, label); err != nil {
			return nil, err
		}
	}
	if _, err := fmt.Fprintln(out, "Choose an endpoint number or enter an endpoint ID; empty/cancel cancels."); err != nil {
		return nil, err
	}
	return endpoints, nil
}

// resolveLaunchEndpointAnswer maps a numbered answer to its endpoint identifier.
// A non-numeric answer stays a literal endpoint identifier, so existing scripts
// that pass an identifier keep working unchanged.
func resolveLaunchEndpointAnswer(endpoints []protocol.Endpoint, answer string) (string, error) {
	trimmed := strings.TrimSpace(answer)
	if !isASCIIDecimal(trimmed) {
		return answer, nil
	}
	if len(endpoints) == 0 {
		return "", fmt.Errorf("endpoint list is unavailable; enter an endpoint ID")
	}
	number, numeric := parseRowNumber(trimmed)
	if !numeric {
		return "", fmt.Errorf("row number exceeds the supported integer range")
	}
	if number < 1 || number > len(endpoints) {
		return "", fmt.Errorf("endpoint number %d is out of range; valid numbers are 1-%d", number, len(endpoints))
	}
	return endpoints[number-1].EndpointID, nil
}

// resolveLaunchEndpoint returns the endpoint already in scope, or asks for one.
// The numbered list is printed before the prompt so a bare number is enough;
// a failed inventory read degrades to the free-text identifier prompt instead of
// aborting the wizard, and control words keep working in both cases. The field
// prompt carries application styling, so it is written through the trusted writer.
func resolveLaunchEndpoint(ctx context.Context, api InteractiveAPI, state *interactiveState, endpointID string, lines <-chan lineReadResult, out, trustedOut io.Writer, color ColorPolicy) (string, error) {
	if endpointID != "" {
		return endpointID, nil
	}
	endpoints, listErr := launchEndpointChoices(ctx, api, out)
	if listErr != nil {
		if _, writeErr := fmt.Fprintf(out, "Endpoint list unavailable (%v); enter an endpoint ID.\n", listErr); writeErr != nil {
			return "", writeErr
		}
	}
	answer, err := launchAnswerValueOrControl(ctx, lines, out, trustedOut, state, "endpoint", color)
	if err != nil || answer == "" {
		return "", err
	}
	if listErr != nil {
		// Without an inventory there is nothing to resolve against, so keep the
		// literal identifier and reject only a bare number.
		return resolveLaunchEndpointAnswer(endpoints, answer)
	}
	return resolveLaunchEndpointValue(endpoints, answer)
}

// resolveLaunchEndpointTarget resolves an explicit start argument against the
// endpoint inventory. An exact endpoint identifier wins, a unique hostname maps
// to its endpoint, and a bare decimal selects the numbered row the wizard prints.
// A failed inventory read keeps the literal value so an identifier-only script
// still works; an unknown value fails locally instead of being sent to the
// server, where it would surface as a misleading availability error.
func resolveLaunchEndpointTarget(ctx context.Context, api InteractiveAPI, target string) (string, error) {
	trimmed := strings.TrimSpace(target)
	if trimmed == "" {
		return "", nil
	}
	queryCtx, cancel := commandContext(ctx)
	endpoints, err := api.ListEndpoints(queryCtx)
	cancel()
	if err != nil {
		return target, nil
	}
	return resolveLaunchEndpointValue(endpoints, trimmed)
}

// resolveLaunchEndpointValue maps one operator answer onto an endpoint identifier
// using an already-fetched inventory. The exact identifier is checked first, so a
// numeric identifier is never mistaken for a row number.
func resolveLaunchEndpointValue(endpoints []protocol.Endpoint, answer string) (string, error) {
	trimmed := strings.TrimSpace(answer)
	if trimmed == "" {
		return "", nil
	}
	if endpoint, ok := endpointByID(reportLoad{endpoints: endpoints}, trimmed); ok {
		return endpoint.EndpointID, nil
	}
	if isASCIIDecimal(trimmed) {
		return resolveLaunchEndpointAnswer(endpoints, trimmed)
	}
	matches := launchEndpointsByHostname(endpoints, trimmed)
	switch len(matches) {
	case 1:
		return matches[0].EndpointID, nil
	case 0:
		return "", nonSyntaxError{message: fmt.Sprintf("endpoint %q was not found", trimmed)}
	default:
		return "", nonSyntaxError{message: fmt.Sprintf("hostname %q matches %d endpoints; enter an endpoint identifier instead", trimmed, len(matches))}
	}
}

// launchEndpointsByHostname returns every endpoint reporting the exact hostname.
func launchEndpointsByHostname(endpoints []protocol.Endpoint, target string) []protocol.Endpoint {
	matches := make([]protocol.Endpoint, 0, 2)
	for _, endpoint := range endpoints {
		if endpoint.Hostname != "" && endpoint.Hostname == target {
			matches = append(matches, endpoint)
		}
	}
	return matches
}
