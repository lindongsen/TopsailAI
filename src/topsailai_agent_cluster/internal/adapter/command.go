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

type commandResponse struct {
	Sessions []protocol.Session `json:"sessions"`
	Complete bool               `json:"complete"`
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
	if a.config.ResourceMapper != nil {
		for index := range response.Sessions {
			session := &response.Sessions[index]
			// Keep the provider-native identifier before replacing it with the
			// opaque cluster resource ID used for routing.
			providerSessionID := session.SessionID
			mapping, err := a.config.ResourceMapper.GetOrCreateResourceID(ctx, a.config.AdapterID, session.SessionID, time.Now().UnixMilli())
			if err != nil {
				return DiscoverResult{}, fmt.Errorf("map adapter %q resource: %w", a.config.AdapterID, err)
			}
			session.SessionID = mapping.ResourceID
			if session.ProviderSessionID == "" {
				session.ProviderSessionID = providerSessionID
			}
			if session.AdapterID == "" {
				session.AdapterID = a.config.AdapterID
			}
		}
	}
	return DiscoverResult{Sessions: response.Sessions, Complete: response.Complete, CollectionStatus: protocol.CollectionSucceeded}, nil
}

// Inspect verifies that a resource exists and returns its current state.

func (a *commandAdapter) Inspect(ctx context.Context, request InspectRequest) (InspectResult, error) {
	if request.Target.ResourceID == "" || request.Target.Generation == "" {
		return InspectResult{}, fmt.Errorf("resource ID and generation are required")
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
		if session.SessionID != request.Target.ResourceID {
			continue
		}
		return InspectResult{Found: true, Generation: session.Generation, State: session.State}, nil
	}
	return InspectResult{}, fmt.Errorf("unknown resource ID %q", request.Target.ResourceID)
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
		args = append(args, "--target-resource-id", providerKey, "--target-generation", request.Intent.Target.Generation)
	}
	args = append(args, "--payload", string(request.Intent.Payload))
	output, err := exec.CommandContext(ctx, a.config.Command, args...).Output()
	if err != nil {
		return ExecuteResult{Receipt: protocol.ExecutionReceipt{CommandID: request.Intent.CommandID, Outcome: "unknown", EffectCertainty: protocol.EffectUnknown}}, fmt.Errorf("execute adapter %q: %w", a.config.AdapterID, err)
	}
	var receipt struct {
		protocol.ExecutionReceipt
		DeliveryState string `json:"delivery_state"`
		SignalSent    bool   `json:"signal_sent"`
	}
	if err := json.Unmarshal(output, &receipt); err != nil {
		return ExecuteResult{Receipt: protocol.ExecutionReceipt{CommandID: request.Intent.CommandID, Outcome: "unknown", EffectCertainty: protocol.EffectUnknown}}, fmt.Errorf("decode adapter %q execution response: %w", a.config.AdapterID, err)
	}
	if receipt.DeliveryState != "" {
		receipt.DeliveryBoundary = protocol.DeliveryBoundary(receipt.DeliveryState)
	}
	if receipt.SignalSent && !receipt.ExitConfirmed {
		receipt.DeliveryBoundary = protocol.DeliverySignalSent
	}
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
	args = append(args, "--read-output", providerKey, "--max-bytes", fmt.Sprint(request.Limit))
	cmd := exec.CommandContext(ctx, a.config.Command, args...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return OutputResult{}, fmt.Errorf("prepare adapter %q output: %w", a.config.AdapterID, err)
	}
	if err := cmd.Start(); err != nil {
		return OutputResult{}, fmt.Errorf("start adapter %q output: %w", a.config.AdapterID, err)
	}
	maxRead := request.Limit*6 + 4096
	if maxRead < 4096 || maxRead < request.Limit {
		maxRead = request.Limit
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
