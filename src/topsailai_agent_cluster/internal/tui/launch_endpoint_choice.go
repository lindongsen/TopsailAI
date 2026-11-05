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
// aborting the wizard, and control words keep working in both cases.
func resolveLaunchEndpoint(ctx context.Context, api InteractiveAPI, state *interactiveState, endpointID string, lines <-chan lineReadResult, out io.Writer) (string, error) {
	if endpointID != "" {
		return endpointID, nil
	}
	endpoints, listErr := launchEndpointChoices(ctx, api, out)
	if listErr != nil {
		if _, writeErr := fmt.Fprintf(out, "Endpoint list unavailable (%v); enter an endpoint ID.\n", listErr); writeErr != nil {
			return "", writeErr
		}
	}
	answer, err := launchAnswerValueOrControl(ctx, lines, out, state, "endpoint")
	if err != nil || answer == "" {
		return "", err
	}
	return resolveLaunchEndpointAnswer(endpoints, answer)
}
