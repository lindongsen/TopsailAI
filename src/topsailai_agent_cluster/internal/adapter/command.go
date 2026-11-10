package adapter

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// CommandConfig configures an adapter backed by one external provider command.
type CommandConfig struct {
	AdapterID      string
	ProviderType   string
	Command        string
	Args           []string
	Timeout        time.Duration
	ResourceMapper ResourceMapper
	Capabilities   *protocol.CapabilityDescriptor
}

var ErrOutputTooLarge = errors.New("adapter output exceeds bounded read limit")

type commandAdapter struct {
	config CommandConfig
}

// commandResponse is the provider's own discovery document. Its tags are the
// provider's field names, not the cluster's, because this struct decodes what a
// provider command printed. Renaming a tag here silently decodes every session to
// an empty value, and validation then rejects the whole report, so these names
// must stay exactly as the provider writes them.
type commandResponse struct {
	Sessions []commandSession `json:"sessions"`
	Complete bool             `json:"complete"`
}

// commandSession is one provider session row in the provider's own vocabulary.
// It is mapped into protocol.Session by Discover, which is the only place the
// provider names and the cluster names meet.
type commandSession struct {
	SessionID        string                 `json:"session_id"`
	Generation       string                 `json:"generation"`
	State            string                 `json:"state"`
	AgentID          string                 `json:"agent_id"`
	DisplayName      string                 `json:"display_name"`
	ProjectWorkspace string                 `json:"project_workspace"`
	PID              int64                  `json:"pid"`
	Drive            *protocol.DriveSummary `json:"drive"`
}

// NewCommandAdapter creates a shell-free adapter backed by an absolute command path.
func NewCommandAdapter(config CommandConfig) (Adapter, error) {
	if config.AdapterID == "" || config.ProviderType == "" || config.Command == "" || config.Timeout <= 0 {
		return nil, fmt.Errorf("adapter ID, provider type, command, and positive timeout are required")
	}
	return &commandAdapter{config: config}, nil
}

// Describe returns the adapter identity and supported capabilities.
func (a *commandAdapter) Describe(context.Context) (Descriptor, error) {
	capabilities := protocol.CapabilityDescriptor{Capabilities: []protocol.Capability{{Name: "message.send", Version: "v1"}, {Name: protocol.OperationExecutionInterrupt, Version: "v1"}, {Name: protocol.OperationAgentStop, Version: "v1"}}}
	if a.config.Capabilities != nil {
		capabilities = *a.config.Capabilities
	}
	return Descriptor{
		AdapterID:    a.config.AdapterID,
		ProviderType: a.config.ProviderType,
		DisplayName:  a.config.AdapterID,
		Capabilities: capabilities,
	}, nil
}

// Discover collects sessions from the configured provider command.
func (a *commandAdapter) Discover(parent context.Context, _ DiscoverRequest) (DiscoverResult, error) {
	ctx, cancel := context.WithTimeout(parent, a.config.Timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, a.config.Command, a.config.Args...)
	output, err := cmd.Output()
	if err != nil {
		return DiscoverResult{}, fmt.Errorf("run adapter %q: %w", a.config.AdapterID, err)
	}
	var response commandResponse
	if err := json.Unmarshal(output, &response); err != nil {
		return DiscoverResult{}, fmt.Errorf("decode adapter %q response: %w", a.config.AdapterID, err)
	}
	sessions := make([]protocol.Session, 0, len(response.Sessions))
	for _, row := range response.Sessions {
		// The provider row carries the provider's own key. Mint the opaque cluster
		// resource ID from it, and keep the provider key as evidence. Both values
		// are read from the provider row before either is stored, so the provider
		// key can never be overwritten by the cluster ID.
		providerSessionID := row.SessionID
		clusterSessionID := providerSessionID
		if a.config.ResourceMapper != nil {
			mapping, err := a.config.ResourceMapper.GetOrCreateResourceID(ctx, a.config.AdapterID, providerSessionID, time.Now().UnixMilli())
			if err != nil {
				return DiscoverResult{}, fmt.Errorf("map adapter %q resource: %w", a.config.AdapterID, err)
			}
			clusterSessionID = mapping.ResourceID
		}
		sessions = append(sessions, protocol.Session{
			ClusterSessionID:         clusterSessionID,
			ProviderSessionID:        providerSessionID,
			ProviderPID:              row.PID,
			ProviderDisplayName:      row.DisplayName,
			ProviderProjectWorkspace: row.ProjectWorkspace,
			ProviderAgentID:          row.AgentID,
			ProviderGeneration:       row.Generation,
			AdapterID:                a.config.AdapterID,
			State:                    row.State,
			Drive:                    row.Drive,
		})
	}
	return DiscoverResult{Sessions: sessions, Complete: response.Complete, CollectionStatus: protocol.CollectionSucceeded}, nil
}

// Inspect verifies that a resource exists and returns its current state.
//
// A generation is not required, matching the TopsailAI adapter. Resume authorizes
// on the absence of a live target, and a history row has no generation because the
// session is not running, so demanding one would make every history resume fail
// before the provider was ever asked. The result still separates Found from Live,
// so a caller that needs a generation match compares the returned value itself.
func (a *commandAdapter) Inspect(ctx context.Context, request InspectRequest) (InspectResult, error) {
	if request.Target.ResourceID == "" {
		return InspectResult{}, fmt.Errorf("resource ID is required")
	}
	if a.config.ResourceMapper != nil {
		mapping, err := a.config.ResourceMapper.LookupResourceID(ctx, request.Target.ResourceID)
		if err != nil || mapping.AdapterID != a.config.AdapterID {
			return InspectResult{}, fmt.Errorf("unknown resource ID %q", request.Target.ResourceID)
		}
	}
	result, err := a.Discover(ctx, DiscoverRequest{})
	if err != nil {
		return InspectResult{}, err
	}
	for _, session := range result.Sessions {
		if session.ClusterSessionID != request.Target.ResourceID {
			continue
		}
		return InspectResult{Found: true, Live: session.ProviderGeneration != "", ProviderGeneration: session.ProviderGeneration, State: session.State}, nil
	}
	// A resource that is absent from a successful discovery is a legitimate
	// absence, not an observation failure. Reporting it as an error makes the
	// caller treat "not found" as "could not observe", which permanently blocks
	// operations that authorize on absence, such as agent.resume.
	return InspectResult{Found: false}, nil
}

// Execute invokes the configured provider and decodes its execution receipt.
func (a *commandAdapter) Execute(parent context.Context, request ExecuteRequest) (ExecuteResult, error) {
	ctx, cancel := context.WithTimeout(parent, a.config.Timeout)
	defer cancel()
	args := append([]string(nil), a.config.Args...)
	args = append(args, "--execute-command-id", request.Intent.CommandID, "--operation", request.Intent.Operation)
	if request.Intent.Target != nil {
		providerKey := request.Intent.Target.ResourceID
		if a.config.ResourceMapper != nil {
			mapping, err := a.config.ResourceMapper.LookupResourceID(ctx, providerKey)
			if err != nil || mapping.AdapterID != a.config.AdapterID {
				return ExecuteResult{}, fmt.Errorf("unknown resource ID %q", providerKey)
			}
			providerKey = mapping.ProviderKey
		}
		args = append(args, "--target-resource-id", providerKey, "--target-generation", request.Intent.Target.ProviderGeneration)
	}
	args = append(args, "--payload", string(request.Intent.Payload))
	output, err := exec.CommandContext(ctx, a.config.Command, args...).Output()
	if err != nil {
		receipt := protocol.ExecutionReceipt{CommandID: request.Intent.CommandID, Outcome: "unknown", EffectCertainty: protocol.EffectUnknown}
		// The provider's own diagnostic is the only evidence of why the call
		// failed, so carry it verbatim instead of discarding it.
		receipt.ProviderResponse, receipt.ProviderResponseTruncated = BoundedProviderResponse(ProviderFailureText(err))
		return ExecuteResult{Receipt: receipt}, fmt.Errorf("execute adapter %q: %w", a.config.AdapterID, err)
	}
	var receipt struct {
		protocol.ExecutionReceipt
		DeliveryState string `json:"delivery_state"`
		SignalSent    bool   `json:"signal_sent"`
	}
	if err := json.Unmarshal(output, &receipt); err != nil {
		decoded := protocol.ExecutionReceipt{CommandID: request.Intent.CommandID, Outcome: "unknown", EffectCertainty: protocol.EffectUnknown}
		// A document that cannot be decoded is still the provider's own answer,
		// so keep it as evidence instead of reporting only a decode error.
		decoded.ProviderResponse, decoded.ProviderResponseTruncated = BoundedProviderResponse(string(output))
		return ExecuteResult{Receipt: decoded}, fmt.Errorf("decode adapter %q execution response: %w", a.config.AdapterID, err)
	}
	if receipt.DeliveryState != "" {
		receipt.DeliveryBoundary = protocol.DeliveryBoundary(receipt.DeliveryState)
	}
	if receipt.SignalSent && !receipt.ExitConfirmed {
		receipt.DeliveryBoundary = protocol.DeliverySignalSent
	}
	receipt.ProviderResponse, receipt.ProviderResponseTruncated = BoundedProviderResponse(string(output))
	return ExecuteResult{Receipt: receipt.ExecutionReceipt}, nil
}

// ReadOutput retrieves bounded provider output for a resource.
func (a *commandAdapter) ReadOutput(parent context.Context, request OutputRequest) (OutputResult, error) {
	if commandOutputUnsupported() {
		return OutputResult{}, ErrUnsupported
	}
	ctx, cancel := context.WithTimeout(parent, a.config.Timeout)
	defer cancel()
	args := append([]string(nil), a.config.Args...)
	mapping := ResourceMapping{}
	if a.config.ResourceMapper != nil {
		var err error
		mapping, err = a.config.ResourceMapper.LookupResourceID(ctx, request.Target.ResourceID)
		if err != nil {
			return OutputResult{}, fmt.Errorf("map adapter %q resource: %w", a.config.AdapterID, err)
		}
		if mapping.AdapterID != a.config.AdapterID {
			return OutputResult{}, fmt.Errorf("resource %q belongs to adapter %q", request.Target.ResourceID, mapping.AdapterID)
		}
	}
	providerKey := request.Target.ResourceID
	if mapping.ProviderKey != "" {
		providerKey = mapping.ProviderKey
	}

	// ReadOutput retrieves bounded provider output for a resource.
	args = append(args, "--read-output", providerKey, "--max-bytes", fmt.Sprint(request.MaxBytes))
	cmd := exec.CommandContext(ctx, a.config.Command, args...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return OutputResult{}, fmt.Errorf("prepare adapter %q output: %w", a.config.AdapterID, err)
	}
	if err := cmd.Start(); err != nil {
		return OutputResult{}, fmt.Errorf("start adapter %q output: %w", a.config.AdapterID, err)
	}
	maxRead := request.MaxBytes*6 + 4096
	if maxRead < 4096 || maxRead < request.MaxBytes {
		maxRead = request.MaxBytes
	}
	// The provider envelope has bounded JSON overhead; never buffer beyond this fixed multiple.
	maxRead++
	output, readErr := io.ReadAll(io.LimitReader(stdout, int64(maxRead)))
	if readErr != nil {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
		return OutputResult{}, fmt.Errorf("read adapter %q output: %w", a.config.AdapterID, readErr)
	}
	if len(output) >= maxRead {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
		return OutputResult{}, fmt.Errorf("%w: adapter %q", ErrOutputTooLarge, a.config.AdapterID)
	}
	waitErr := cmd.Wait()
	if waitErr != nil {
		return OutputResult{}, fmt.Errorf("read adapter %q output: %w", a.config.AdapterID, waitErr)
	}
	var response struct {
		Data      string   `json:"data"`
		Lines     []string `json:"lines"`
		Truncated bool     `json:"truncated"`
	}
	if err := json.Unmarshal(output, &response); err != nil {
		return OutputResult{}, fmt.Errorf("decode adapter %q output: %w", a.config.AdapterID, err)
	}
	if response.Data != "" {
		response.Lines = []string{response.Data}
	}
	return OutputResult{Lines: response.Lines, Truncated: response.Truncated, ObservedAtMS: time.Now().UnixMilli()}, nil
}

// QueryCommand reports that command reconciliation is unsupported.
func (a *commandAdapter) QueryCommand(context.Context, CommandQuery) (CommandResult, error) {
	return CommandResult{}, ErrUnsupported
}

// Watch reports that event streaming is unsupported.
func (a *commandAdapter) Watch(context.Context) (<-chan Event, error) { return nil, ErrUnsupported }

// Close releases adapter-local resources.
func (a *commandAdapter) Close() error { return nil }
