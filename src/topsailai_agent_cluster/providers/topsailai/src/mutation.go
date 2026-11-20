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
	operationProjectAdd,
	operationProjectRemove,
}

// operationNeedsStopSupport reports whether one operation is served only where the
// host can stop a provider process.
//
// agent.stop is the only operation with a host requirement: it terminates a
// provider process, so it needs a readable process table and a pidfd. Every other
// operation only reads or writes provider records.
func operationNeedsStopSupport(operation string) bool {
	return operation == operationAgentStop
}

// mutationOperations returns the advertised standard operations in a stable order.
//
// The platform is a parameter rather than a process read, so the advertised surface
// is decided from the value the boundary detected once and every later decision uses
// the same value.
func mutationOperations(platform platformCapabilities) []namedContract {
	contracts := make([]namedContract, 0, len(supportedMutationOperations))
	for _, operation := range supportedMutationOperations {
		if operationNeedsStopSupport(operation) && !platform.stopSupported() {
			continue
		}
		contracts = append(contracts, namedContract{Name: operation, Version: operationVersion})
	}
	return contracts
}

// supportedMutationOperation reports whether this Provider serves one operation.
//
// A host that cannot stop a provider process refuses agent.stop here, before any
// authority read and before any argv exists, so an unsupported operation can never
// reach the provider CLI.
func supportedMutationOperation(operation string, platform platformCapabilities) bool {
	if strings.HasPrefix(operation, controlOperationPrefix) {
		return true
	}
	if operationNeedsStopSupport(operation) && !platform.stopSupported() {
		return false
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
	operation, err := validateExecuteRequest(request, p.platform)
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
func validateExecuteRequest(request request, platform platformCapabilities) (string, error) {
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
		// project.add is the only standard mutation that carries no target: the
		// resource it creates does not exist yet, so it has no identity to address.
		// Every other execute still requires a target, so a missing target remains a
		// defect the Provider reports rather than a form it accepts.
		if operation != operationProjectAdd {
			return "", fmt.Errorf("%w: target is required", errInvalidRequest)
		}
	}
	if request.Query != nil {
		return "", fmt.Errorf("%w: execute request must not contain query", errInvalidRequest)
	}
	if !supportedMutationOperation(operation, platform) {
		return "", fmt.Errorf("%w: provider operation %q is not implemented", errUnsupported, operation)
	}
	if operationNeedsLiveGeneration(operation) && request.Target != nil && request.Target.ExpectedGeneration == "" {
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
		resolved, err := p.requireLiveGeneration(ctx, request.Target)
		if err != nil {
			return nil, err
		}
		// The catalog template expands {session} into the provider session
		// identifier, never the opaque mapping key: the provider CLI takes a
		// session identifier, and the mapping key is a Cluster-side spelling.
		return p.control.args(operation, resolved.SessionID, request.Payload)
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
		return mutationArgs(mutationInvocation{Operation: operation, Resolved: resolved, Payload: request.Payload})
	case operationAgentDriveStop:
		// Stop addresses the recorded controller, including a residual record whose
		// process is already gone, so it must not require a live target.
		resolved, err := p.requireNonLiveRecord(ctx, request.Target)
		if err != nil {
			return nil, err
		}
		return mutationArgs(mutationInvocation{Operation: operation, Resolved: resolved, Payload: request.Payload})
	case operationWorkspaceClean:
		resolved, err := p.requireNonLiveRecord(ctx, request.Target)
		if err != nil {
			return nil, err
		}
		return mutationArgs(mutationInvocation{Operation: operation, Resolved: resolved, Payload: request.Payload})
	case operationProjectAdd:
		// project.add creates the resource, so there is no target to revalidate and
		// no generation to compare. Its authority is the configured project root:
		// the folder is confined to that root here, in the same execution path that
		// builds the argv, so the Endpoint's pre-dispatch check and this check
		// cannot disagree about which folder is registered.
		return projectAddArgs(request.Payload, p.projectRoot)
	case operationProjectRemove:
		// Removal addresses a registry entry, not a live process, so it carries no
		// generation. The exact folder travels in the opaque provider_target slot,
		// and membership is decided by the registry owner: the provider CLI refuses
		// a path it does not list, so this Provider never guesses which entry the
		// operator meant. The folder on disk is never deleted.
		folder, err := decodeProjectTarget(request.Target.ProviderTarget)
		if err != nil {
			return nil, err
		}
		return projectRemoveArgs(folder, request.Target.ProviderResourceKey, p.projectRoot)
	default:
		resolved, err := p.requireLiveGeneration(ctx, request.Target)
		if err != nil {
			return nil, err
		}
		return mutationArgs(mutationInvocation{Operation: operation, Generation: request.Target.ExpectedGeneration, Resolved: resolved, Payload: request.Payload})
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
