package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"strings"
)

// maxProviderResponseBytes bounds the provider document carried in one result.
//
// The bound matches the frozen response contract, so a shortened provider answer
// is always labelled instead of being presented as complete evidence.
const maxProviderResponseBytes = 64 << 10

// supportedMutationOperations lists the standard operations this Provider serves.
//
// The list is the single source of truth for both dispatch and the advertised
// descriptor, so a capability cannot be advertised without a handler and a handler
// cannot exist without being advertised. The provider control family is addressed
// by a dynamic ctl.<action> name and is therefore not listed here.
var supportedMutationOperations = [...]string{
	operationMessageSend,
	operationContextInject,
	operationAgentStart,
	operationAgentResume,
	operationAgentStop,
	operationAgentDriveStart,
	operationAgentDriveStop,
	operationWorkspaceClean,
	operationAgentModelSelect,
	operationExecutionInterrupt,
}

// mutationOperations returns the advertised standard operations in a stable order.
func mutationOperations() []namedContract {
	contracts := make([]namedContract, 0, len(supportedMutationOperations))
	for _, operation := range supportedMutationOperations {
		contracts = append(contracts, namedContract{Name: operation, Version: operationVersion})
	}
	return contracts
}

// supportedMutationOperation reports whether this Provider serves one operation.
func supportedMutationOperation(operation string) bool {
	if strings.HasPrefix(operation, controlOperationPrefix) {
		return true
	}
	for _, candidate := range supportedMutationOperations {
		if candidate == operation {
			return true
		}
	}
	return false
}

// execute performs one standard mutation and reports Provider evidence only.
//
// The order is fixed and load-bearing: validate the request, revalidate the target
// authority, then build and run the business argv. Authority is decided before any
// argv exists, so a stale, missing or ambiguous target can never reach the provider
// CLI. A rejected request returns an error and no result, because nothing ran.
func (p *provider) execute(ctx context.Context, request request) (*operationResult, error) {
	operation, err := validateExecuteRequest(request)
	if err != nil {
		return nil, err
	}
	args, err := p.mutationArgs(ctx, request, operation)
	if err != nil {
		return nil, err
	}
	return p.runMutation(ctx, request, args), nil
}

// validateExecuteRequest checks the frozen execute request contract.
//
// The checks mirror protocol/provider-cli/v1/request.schema.json. They are
// implemented here as well because this executable is an independent module that
// cannot import the Cluster validator, and because a caller may reach dispatch
// without passing through the request envelope decoder.
func validateExecuteRequest(request request) (string, error) {
	if strings.TrimSpace(request.InvocationID) == "" {
		return "", fmt.Errorf("%w: invocation_id is required", errInvalidRequest)
	}
	if request.Operation == nil {
		return "", fmt.Errorf("%w: operation is required", errInvalidRequest)
	}
	operation := request.Operation.Name
	if strings.TrimSpace(operation) == "" {
		return "", fmt.Errorf("%w: operation name is required", errInvalidRequest)
	}
	if request.Operation.Version != operationVersion {
		return "", fmt.Errorf("%w: operation version %q is not supported", errInvalidRequest, request.Operation.Version)
	}
	if request.Target == nil {
		return "", fmt.Errorf("%w: target is required", errInvalidRequest)
	}
	if request.Query != nil {
		return "", fmt.Errorf("%w: execute request must not contain query", errInvalidRequest)
	}
	if !supportedMutationOperation(operation) {
		return "", fmt.Errorf("%w: provider operation %q is not implemented", errUnsupported, operation)
	}
	if operationNeedsLiveGeneration(operation) && request.Target.ExpectedGeneration == "" {
		return "", fmt.Errorf("%w: target expected_generation is required for %s", errInvalidRequest, operation)
	}
	return operation, nil
}

// mutationArgs revalidates the target authority and builds the business argv.
//
// Each branch performs exactly one authority read and then one pure argv mapping,
// so the decision and the invocation cannot disagree about which target they mean.
func (p *provider) mutationArgs(ctx context.Context, request request, operation string) ([]string, error) {
	if strings.HasPrefix(operation, controlOperationPrefix) {
		if _, err := p.requireLiveGeneration(ctx, request.Target); err != nil {
			return nil, err
		}
		return p.control.args(operation, request.Target.ProviderResourceKey, request.Payload)
	}
	switch operation {
	case operationAgentStart:
		// A launch profile is not a live process, so its authority is the frozen
		// profile identity and revision rather than a process generation.
		if err := p.requireLaunchProfile(request.Target); err != nil {
			return nil, err
		}
		return mutationArgs(mutationInvocation{Operation: operation, Payload: request.Payload})
	case operationAgentResume:
		resolved, err := p.requireResumableRecord(ctx, request.Target)
		if err != nil {
			return nil, err
		}
		return mutationArgs(mutationInvocation{Operation: operation, ProviderKey: request.Target.ProviderResourceKey, Resolved: resolved, Payload: request.Payload})
	case operationAgentDriveStop:
		// Stop addresses the recorded controller, including a residual record whose
		// process is already gone, so it must not require a live target.
		resolved, err := p.requireNonLiveRecord(ctx, request.Target)
		if err != nil {
			return nil, err
		}
		return mutationArgs(mutationInvocation{Operation: operation, ProviderKey: request.Target.ProviderResourceKey, Resolved: resolved, Payload: request.Payload})
	case operationWorkspaceClean:
		resolved, err := p.requireNonLiveRecord(ctx, request.Target)
		if err != nil {
			return nil, err
		}
		return mutationArgs(mutationInvocation{Operation: operation, ProviderKey: request.Target.ProviderResourceKey, Resolved: resolved, Payload: request.Payload})
	default:
		resolved, err := p.requireLiveGeneration(ctx, request.Target)
		if err != nil {
			return nil, err
		}
		return mutationArgs(mutationInvocation{Operation: operation, ProviderKey: request.Target.ProviderResourceKey, Generation: request.Target.ExpectedGeneration, Resolved: resolved, Payload: request.Payload})
	}
}

// runMutation invokes one business argv and converts the outcome into evidence.
//
// A completed invocation is acknowledged even when it failed, because the exit
// status is known and the operator needs it. Only a start failure is not applied,
// and only an unconfirmed exit is unknown. An unknown effect is never upgraded to
// acknowledged and is never retried here.
func (p *provider) runMutation(ctx context.Context, request request, args []string) *operationResult {
	started := p.now().UnixMilli()
	stdout, stderr, runErr := p.runner.Run(ctx, args, nil)
	finished := p.now().UnixMilli()
	result := &operationResult{
		ProviderRequestRef: request.InvocationID,
		StartedAtMS:        started,
		FinishedAtMS:       finished,
	}
	switch {
	case runErr == nil:
		result.DeliveryBoundary = deliverySubmitted
		result.EffectCertainty = effectAcknowledged
		result.ProviderOutcome = "succeeded"
		result.ProviderResponse, result.ProviderResponseTruncated = boundedProviderResponse(stdout)
	case errors.Is(runErr, context.DeadlineExceeded), errors.Is(runErr, context.Canceled):
		// The process may have acted before it was terminated, so the effect is
		// unknown rather than failed.
		result.DeliveryBoundary = deliverySubmitted
		result.EffectCertainty = effectUnknown
		result.ProviderOutcome = "unconfirmed"
		result.ProviderResponse, result.ProviderResponseTruncated = boundedProviderResponse(stderr)
	default:
		var exitError *exec.ExitError
		if !errors.As(runErr, &exitError) {
			// The process never started, so nothing was delivered.
			result.DeliveryBoundary = deliveryNotStarted
			result.EffectCertainty = effectNotApplied
			result.ProviderOutcome = "failed"
			result.ProviderResponse, result.ProviderResponseTruncated = boundedProviderResponse(stderr)
			break
		}
		if document, ok := providerOutcomeDocument(stdout); ok {
			// The provider ran and reported its own outcome document, so the effect
			// is acknowledged and that document is the evidence.
			result.DeliveryBoundary = deliverySubmitted
			result.EffectCertainty = effectAcknowledged
			result.ProviderOutcome = "failed"
			result.ProviderResponse, result.ProviderResponseTruncated = boundedProviderResponse(document)
			break
		}
		// The provider ran but left no structured outcome, so whether the mutation
		// applied is unknown. The stderr diagnostic is the only evidence available.
		result.DeliveryBoundary = deliverySubmitted
		result.EffectCertainty = effectUnknown
		result.ProviderOutcome = "unconfirmed"
		result.ProviderResponse, result.ProviderResponseTruncated = boundedProviderResponse(stderr)
	}
	return result
}

// providerOutcomeDocument returns stdout when it is exactly one JSON object.
//
// A non-zero exit still carries the provider's own outcome document on stdout, so
// that document must reach the caller instead of being flattened into a generic
// failure. Anything that is not a JSON object is not evidence of an outcome.
func providerOutcomeDocument(stdout []byte) ([]byte, bool) {
	trimmed := bytes.TrimSpace(stdout)
	if len(trimmed) == 0 || trimmed[0] != '{' || !json.Valid(trimmed) {
		return nil, false
	}
	return trimmed, true
}

// boundedProviderResponse truncates one provider document and labels it.
func boundedProviderResponse(document []byte) (string, bool) {
	if len(document) <= maxProviderResponseBytes {
		return string(document), false
	}
	return boundedString(string(document), maxProviderResponseBytes), true
}
