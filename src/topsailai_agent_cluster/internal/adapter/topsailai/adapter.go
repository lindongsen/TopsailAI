package topsailai

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

const (
	defaultTimeout = 30 * time.Second
	defaultMaxOut  = 8 << 20
)

// Config configures one local TopsailAI CLI binding.
type Config struct {
	AdapterID      string
	Executable     string
	Version        string
	Timeout        time.Duration
	MaxOutput      int
	PlatformProbe  PlatformCapabilityProbe
	ResourceMapper adapter.ResourceMapper
	// ControlActions is the Endpoint-local catalog of ctl. actions. A nil set
	// advertises no action and refuses every ctl. operation, because the catalog
	// is the only source of actions and an Endpoint cannot serve an action it was
	// never told about.
	ControlActions *ControlActionSet
}

// PlatformCapabilities describes host support required by agent.stop.
type PlatformCapabilities struct {
	ProcAvailable  bool
	PidfdAvailable bool
}

// PlatformCapabilityProbe detects host capabilities once during adapter initialization.
type PlatformCapabilityProbe func() (PlatformCapabilities, error)

// Adapter implements the Endpoint-private TopsailAI provider contract.
type Adapter struct {
	config       Config
	mapper       adapter.ResourceMapper
	runner       commandRunner
	execRunner   commandExecRunner
	followRunner followRunner
	platformStop bool
}

// ResourceMapping aliases the shared adapter resource mapping contract.
type ResourceMapping = adapter.ResourceMapping

// ResourceMapper aliases the shared adapter resource mapper contract.
type ResourceMapper = adapter.ResourceMapper

// New constructs a shell-free TopsailAI adapter.
func New(config Config) (*Adapter, error) {
	if config.AdapterID == "" || config.Executable == "" {
		return nil, errors.New("adapter ID and executable are required")
	}
	if config.Timeout <= 0 {
		config.Timeout = defaultTimeout
	}
	if config.MaxOutput <= 0 {
		config.MaxOutput = defaultMaxOut
	}
	probe := config.PlatformProbe
	if probe == nil {
		probe = defaultPlatformProbe
	}
	capabilities, err := probe()
	if err != nil {
		capabilities = PlatformCapabilities{}
	}
	return &Adapter{config: config, mapper: config.ResourceMapper, runner: execRunner{timeout: config.Timeout}, execRunner: execCommandRunner{timeout: config.Timeout}, followRunner: execFollowRunner{timeout: config.Timeout}, platformStop: capabilities.ProcAvailable && capabilities.PidfdAvailable}, nil
}

func newWithRunner(config Config, runner commandRunner) (*Adapter, error) {
	result, err := New(config)
	if err != nil {
		return nil, err
	}
	result.runner = runner
	return result, nil
}

// Describe declares the reviewed TopsailAI operations and their revision.
func (a *Adapter) Describe(context.Context) (adapter.Descriptor, error) {
	descriptor := adapter.Descriptor{
		AdapterID: a.config.AdapterID, ProviderType: "topsailai", DisplayName: "TopsailAI", Version: a.config.Version,
		Capabilities: protocol.CapabilityDescriptor{Revision: "topsailai-v1", Capabilities: []protocol.Capability{
			{Name: protocol.OperationDiscover, Version: "v1", TargetKinds: []string{"session"}},
			{Name: protocol.OperationMessageSend, Version: "v1", TargetKinds: []string{"session"}},
			{Name: protocol.OperationContextInject, Version: "v1", TargetKinds: []string{"session"}},
			{Name: protocol.OperationExecutionInterrupt, Version: "v1", TargetKinds: []string{"session"}},
			{Name: protocol.OperationOutputRead, Version: "v1", TargetKinds: []string{"session"}},
			// output.follow is advertised only because this adapter can stream
			// provider records. A provider without a streaming entry point must
			// omit it so the Endpoint reports the gap instead of degrading a
			// follow into a snapshot that never updates.
			{Name: protocol.OperationOutputFollow, Version: "v1", TargetKinds: []string{"session"}},
			{Name: protocol.OperationAgentStart, Version: "v1", TargetKinds: []string{"endpoint"}},
			{Name: protocol.OperationAgentResume, Version: "v1", TargetKinds: []string{"session"}},
			{Name: protocol.OperationAgentDriveStart, Version: "v1", TargetKinds: []string{"session"}},
			{Name: protocol.OperationAgentDriveStop, Version: "v1", TargetKinds: []string{"session"}},
			// command.exec runs an operator-supplied argv array, so it declares the
			// control permission: an operator who may not control a session must not
			// be able to run commands in its working directory either.
			{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion, TargetKinds: []string{"session"}, SafetyClass: protocol.SafetyClassMutating, RequiredPermission: "control"},
			// agent.model.select changes the model a running agent uses, so it
			// declares the control permission and the mutating safety class. A
			// credential that may only read output must not be able to change what
			// the agent is running on.
			{Name: protocol.OperationAgentModelSelect, Version: protocol.ModelSelectPayloadVersion, TargetKinds: []string{"session"}, SafetyClass: protocol.SafetyClassMutating, RequiredPermission: "control"},
			// agent.model.list reads the profiles a session can select, so it
			// declares the view permission and the read-only safety class. It is
			// advertised separately from select because a credential that may look
			// at the menu must not thereby be able to change the model.
			{Name: protocol.OperationAgentModelList, Version: "v1", TargetKinds: []string{"session"}, SafetyClass: protocol.SafetyClassReadOnly, RequiredPermission: "view"},
		}},
	}
	// The provider control family is advertised per enabled action so an operator
	// sees exactly the actions this Endpoint serves, and each action carries the
	// scope it requires instead of inheriting one blanket permission. A configured
	// control action file narrows this list; an omitted action becomes unreachable
	// because the Endpoint rejects an operation it does not advertise.
	descriptor.Capabilities.Capabilities = append(descriptor.Capabilities.Capabilities, controlActionCapabilities(a.config.ControlActions)...)
	if a.platformStop {
		descriptor.Capabilities.Capabilities = append(descriptor.Capabilities.Capabilities, protocol.Capability{Name: protocol.OperationAgentStop, Version: "v1", TargetKinds: []string{"session"}})
	}
	return descriptor, nil
}

type workspaceResponse struct {
	Items []workspaceItem `json:"items"`
	Total *int            `json:"total"`
}

type workspaceItem struct {
	SessionID         string          `json:"session_id"`
	ProviderRowKey    string          `json:"filename"`
	SessionName       string          `json:"session_name"`
	SessionQualifier  string          `json:"session_qualifier"`
	IsTask            bool            `json:"is_task"`
	ProcessGeneration json.RawMessage `json:"process_generation"`
	State             string          `json:"state"`
	Status            string          `json:"status"`
	AgentID           string          `json:"agent_id"`
	// PID is the provider's own process identity for this session. It is forwarded
	// as display evidence only: a provider PID is not a cluster generation, so it
	// never selects a target or authorizes a signal. A null value decodes to zero,
	// which is reported as "no PID reported" rather than as a process identity.
	PID int64 `json:"pid"`
	// ProjectWorkspace is the workspace this session is working on. It is
	// forwarded as descriptive report data, never as a routing input.
	ProjectWorkspace string `json:"project_workspace"`
	// Driver is the provider's own controller observation. It is null when the
	// provider reported no observation for this row, which is not the same as a
	// confirmed absence of a controller.
	Driver *workspaceDriver `json:"driver"`
}

// workspaceDriver mirrors the provider's driver observation document.
type workspaceDriver struct {
	State         string `json:"state"`
	Reason        string `json:"reason"`
	DriverPID     int64  `json:"driver_pid"`
	RunID         string `json:"run_id"`
	Verification  string `json:"verification"`
	MetadataState string `json:"metadata_status"`
}

// driveSummary maps the provider's driver vocabulary onto the standard states.
//
// The provider distinguishes a verified controller from an unverified record, so
// STALE and "?" must never be reported as running: an operator who believes a
// controller is active when it is not would stop supervising the session.
func driveSummary(driver *workspaceDriver, observedAtMS int64) *protocol.DriveSummary {
	if driver == nil {
		return nil
	}
	summary := &protocol.DriveSummary{
		Reason:        boundedDriveReason(driver.Reason),
		ControllerPID: driver.DriverPID,
		RunID:         driver.RunID,
		Verified:      driver.Verification == "verified",
		ObservedAtMS:  observedAtMS,
	}
	switch driver.State {
	case "ON":
		summary.State = protocol.DriveStateRunning
	case "STALE":
		summary.State = protocol.DriveStateStale
	case "EXIT":
		summary.State = protocol.DriveStateExited
	case "FAIL":
		summary.State = protocol.DriveStateFailed
	case "-":
		summary.State = protocol.DriveStateNone
	default:
		// "?" and any unrecognized value stay unknown rather than defaulting to
		// a state that would imply a verified controller.
		summary.State = protocol.DriveStateUnknown
	}
	if summary.State != protocol.DriveStateRunning {
		summary.Verified = false
	}
	return summary
}

// normalizeSessionState maps the provider's session vocabulary onto the standard
// states declared by the protocol.
//
// The provider reports "input" for a live process that holds its session pipe,
// which is the state an operator reacts to. Forwarding that word verbatim made
// the cluster contract depend on one provider's spelling: the TUI ordered
// "waiting_input", which no producer emitted, while the real value fell into the
// unrecognized-state fallback. Mapping here keeps one vocabulary on the wire and
// lets a second adapter report the same standard value.
//
// An unrecognized value becomes unknown rather than being forwarded as if it
// were standard, because a consumer cannot interpret a word the contract does
// not define. The unverified override is applied by the caller after this
// mapping, so an empty generation still reports unknown with its own reason.
func normalizeSessionState(state string) string {
	switch state {
	case protocol.SessionStateRunning:
		return protocol.SessionStateRunning
	case "input", protocol.SessionStateWaitingInput:
		return protocol.SessionStateWaitingInput
	case protocol.SessionStateIdle:
		return protocol.SessionStateIdle
	default:
		return protocol.SessionStateUnknown
	}
}

// boundedDriveReason keeps a provider reason code short enough to store and
// render. Provider diagnostics stay local; only a bounded code is published.
func boundedDriveReason(reason string) string {
	const limit = 64
	reason = strings.TrimSpace(reason)
	if len(reason) <= limit {
		return reason
	}
	cut := limit
	for cut > 0 && !utf8.RuneStart(reason[cut]) {
		cut--
	}
	return reason[:cut]
}

func workspaceGeneration(raw json.RawMessage) (string, error) {
	raw = bytes.TrimSpace(raw)
	if len(raw) == 0 || bytes.Equal(raw, []byte("null")) {
		return "", nil
	}
	if raw[0] == '"' {
		var value string
		if err := json.Unmarshal(raw, &value); err != nil {
			return "", err
		}
		return value, nil
	}
	if raw[0] == '-' || (raw[0] >= '0' && raw[0] <= '9') {
		start := 0
		if raw[0] == '-' {
			start = 1
		}
		if start == len(raw) {
			return "", fmt.Errorf("generation number is not an integer: %s", raw)
		}
		for _, character := range raw[start:] {
			if character < '0' || character > '9' {
				return "", fmt.Errorf("generation number is not an integer: %s", raw)
			}
		}
		return string(raw), nil
	}
	return "", fmt.Errorf("generation must be a string, integer, or null")
}

// Discover reads the bounded workspace JSON and returns opaque session resources.
//
// The provider only accepts --local on its `workspace list` subcommand; the
// parent `workspace --format json` form parses unknown flags silently and would
// ignore it. Both forms emit the same document, so the list form is used to
// carry the flag. --local keeps only rows produced on this host, which is the
// scope an Endpoint owns: a row recorded on another machine describes a session
// this Endpoint cannot address, and its provider key would resolve to a process
// that does not exist here.
func (a *Adapter) Discover(ctx context.Context, _ adapter.DiscoverRequest) (adapter.DiscoverResult, error) {
	output, err := a.run(ctx, []string{"workspace", "list", "--json", "--local"}, nil)
	if err != nil {
		return adapter.DiscoverResult{}, err
	}
	var response workspaceResponse
	if err := json.Unmarshal(output, &response); err != nil {
		return adapter.DiscoverResult{}, fmt.Errorf("decode workspace JSON: %w", err)
	}
	if response.Items == nil {
		return adapter.DiscoverResult{}, errors.New("workspace JSON has no items")
	}
	nowMS := time.Now().UnixMilli()
	result := adapter.DiscoverResult{Complete: true, CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: nowMS, LastSuccessAtMS: nowMS, DataKnown: true}
	for _, item := range response.Items {
		generation, err := workspaceGeneration(item.ProcessGeneration)
		if err != nil {
			return adapter.DiscoverResult{}, fmt.Errorf("decode workspace generation: %w", err)
		}
		// A workspace row without a provider generation is a real record whose
		// liveness the provider could not verify: it reports no generation when no
		// process holds the session output file. Dropping such a row made the
		// session disappear from the only surface that can address it, so an
		// operator saw a shorter list instead of an unverified session. It is
		// reported as unknown with no generation, which keeps it visible and
		// resumable while every operation that needs a live target still fails
		// closed on the empty generation.
		if item.SessionID == "" {
			continue
		}
		providerKey, err := providerSessionKey(item)
		if err != nil {
			return adapter.DiscoverResult{}, err
		}
		resourceID, err := a.resourceID(ctx, providerKey)
		if err != nil {
			return adapter.DiscoverResult{}, err
		}
		state := normalizeSessionState(item.State)
		if item.State == "" {
			state = normalizeSessionState(item.Status)
		}
		stateReason := ""
		if generation == "" {
			state = protocol.SessionStateUnknown
			stateReason = protocol.StateReasonLivenessUnverified
		}
		observedAtMS := time.Now().UnixMilli()
		result.Sessions = append(result.Sessions, protocol.Session{ClusterSessionID: resourceID, ProviderSessionID: item.SessionID, ProviderPID: item.PID, ProviderDisplayName: item.SessionName, ProviderSessionQualifier: item.SessionQualifier, ProviderProjectWorkspace: item.ProjectWorkspace, ProviderAgentID: item.AgentID, ProviderGeneration: generation, AdapterID: a.config.AdapterID, State: state, StateReason: stateReason, ObservedAtMS: observedAtMS, Drive: driveSummary(item.Driver, observedAtMS)})
	}
	if response.Total != nil && *response.Total > len(response.Items) {
		result.Complete = false
		result.CollectionStatus = protocol.CollectionPartial
		result.ErrorCode = "discovery_truncated"
		result.ErrorMessage = "workspace result is truncated"
	}
	return result, nil
}

func (a *Adapter) resourceID(ctx context.Context, providerKey string) (string, error) {
	if a.mapper == nil {
		return "", errors.New("durable resource mapper is required")
	}
	mapping, err := a.mapper.GetOrCreateResourceID(ctx, a.config.AdapterID, providerKey, time.Now().UnixMilli())
	if err != nil {
		return "", err
	}
	return mapping.ResourceID, nil
}

// Inspect revalidates a mapped resource and reports its current provider state.
//
// A generation is not required. Resume authorizes on the absence of a live target,
// and a history row has no generation because the session is not running, so
// demanding one would make every history resume fail before the provider was ever
// asked. The absence proof still comes from the provider's own answer, which is
// reported as two separate facts: Found means the provider still lists the record,
// and Live means it also proved a process currently holds that session output file.
// A listed record without that proof is found but not live, so resume reads Live
// rather than Found; reading Found would refuse to resume exactly the sessions
// whose process is gone, which is the only case resume exists for. Callers that
// need a generation match compare the returned value themselves, so this
// relaxation cannot silently authorize a stale generation.
func (a *Adapter) Inspect(ctx context.Context, request adapter.InspectRequest) (adapter.InspectResult, error) {
	if request.Target.ResourceID == "" {
		return adapter.InspectResult{}, errors.New("resource ID is required")
	}
	if a.mapper == nil {
		return adapter.InspectResult{}, errors.New("durable resource mapper is required")
	}
	mapping, err := a.mapper.LookupResourceID(ctx, request.Target.ResourceID)
	if err != nil {
		return adapter.InspectResult{}, err
	}
	// Query only the requested provider session. A full workspace discovery scans
	// the complete provider history, which costs seconds per command, so the
	// targeted list is used instead; it reports the same generation evidence for
	// the one session being revalidated.
	//
	// --local is deliberately NOT passed here, unlike Discover. The inventory lists
	// only what this Endpoint can control, so it stays local. Inspect must not,
	// because resume authorizes on the absence of a live target: a session recorded
	// on another machine is absent from a --local read, so --local would report it
	// as not found and authorize a resume the operator asked for. A task directory
	// shared between hosts is exactly the case where resuming another host's
	// session is intended, and the provider applies no host filter to resume. Such
	// a row still reports an empty generation, because this host cannot verify a
	// process it cannot see, so it is found but not live.
	target, err := decodeProviderSessionKey(mapping.ProviderKey)
	if err != nil {
		return adapter.InspectResult{}, err
	}
	output, err := a.run(ctx, []string{"workspace", "list", "-s", target.SessionID, "--json"}, nil)
	if err != nil {
		return adapter.InspectResult{}, err
	}
	var response workspaceResponse
	if err := json.Unmarshal(output, &response); err != nil {
		return adapter.InspectResult{}, fmt.Errorf("decode workspace list JSON: %w", err)
	}
	for _, item := range response.Items {
		if !target.matchesWorkspaceItem(item) {
			continue
		}
		generation, err := workspaceGeneration(item.ProcessGeneration)
		if err != nil {
			return adapter.InspectResult{}, fmt.Errorf("decode workspace generation: %w", err)
		}
		state := normalizeSessionState(item.State)
		if item.State == "" {
			state = normalizeSessionState(item.Status)
		}
		// Found means the provider still lists the record; Live means it also
		// proved a process holds the session output file. A record without a
		// generation is listed but unverified, so it is found and not live.
		// Resume authorizes on the absence of a live target, so it must read Live
		// rather than Found: reading Found would refuse to resume exactly the
		// sessions whose process is gone, which is the only case resume exists for.
		return adapter.InspectResult{Found: true, Live: generation != "", ProviderGeneration: generation, State: state}, nil
	}
	// An empty targeted result is a legitimate absence, not a malformed report.
	return adapter.InspectResult{Found: false}, nil
}

// Execute invokes one fixed TopsailAI operation without a shell.
func (a *Adapter) Execute(ctx context.Context, request adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	intent := request.Intent
	operation := intent.Operation
	if intent.Target == nil && operation != protocol.OperationAgentStart {
		return adapter.ExecuteResult{Receipt: failedReceipt(intent, "target_required")}, errors.New("target is required")
	}
	if operation == protocol.OperationAgentStop && !a.platformStop {
		return adapter.ExecuteResult{}, adapter.ErrUnsupported
	}
	providerKey, err := a.providerTarget(ctx, intent.Target)
	if err != nil && operation != protocol.OperationAgentStart {
		return adapter.ExecuteResult{Receipt: failedReceipt(intent, "unknown_target")}, err
	}
	var args []string
	var stdin []byte
	switch operation {
	case protocol.OperationCommandExec:
		// command.exec does not build a provider argv: it runs the operator's own
		// argv array locally, so it returns before the provider invocation path.
		return a.executeCommand(ctx, intent)
	case "send", protocol.OperationMessageSend:
		message, err := runtimeMessage(intent.Payload)
		if err != nil {
			return adapter.ExecuteResult{Receipt: failedReceipt(intent, "invalid_payload")}, err
		}
		// The provider parser classifies a separate argv element, so a message that is
		// one dash-leading token would be consumed as an option. The assignment form
		// keeps the value attached to its flag without adding a shell or quoting layer.
		args = []string{"runtime", "send", "-s", providerKey, "-m=" + message, "--json"}
	case "btw", protocol.OperationContextInject:
		message, err := runtimeMessage(intent.Payload)
		if err != nil {
			return adapter.ExecuteResult{Receipt: failedReceipt(intent, "invalid_payload")}, err
		}
		args = []string{"runtime", "btw", "-s", providerKey, "-m=" + message, "--json"}
	case protocol.OperationExecutionInterrupt, "control":
		action, payload, err := interruptControlPayload(intent.Payload)
		if err != nil {
			return adapter.ExecuteResult{Receipt: failedReceipt(intent, "invalid_payload")}, err
		}
		args = []string{"runtime", "control", action, "-s", providerKey, "-a", string(payload), "--json"}
	case protocol.OperationAgentStart:
		if intent.LaunchProfileID == "" {
			return adapter.ExecuteResult{Receipt: failedReceipt(intent, "profile_required")}, errors.New("launch profile is required")
		}
		args = []string{"workspace", "agent"}
		if intent.Folder != "" {
			args = append(args, intent.Folder)
		}
		task, supplied, err := initialTask(intent.Payload)
		if err != nil {
			return adapter.ExecuteResult{Receipt: failedReceipt(intent, "invalid_payload")}, err
		}
		args = append(args, "--background", "--json", "--non-interactive")
		if supplied {
			args = append(args, "--task="+task)
		}
	case protocol.OperationAgentResume:
		args = []string{"workspace", "resume", "-s", providerKey, "--background", "--json"}
	case protocol.OperationAgentStop:
		if intent.Target.ProviderGeneration == "" {
			return adapter.ExecuteResult{Receipt: failedReceipt(intent, "generation_required")}, errors.New("generation is required for stop")
		}
		args = []string{"workspace", "kill", providerKey, "-g", intent.Target.ProviderGeneration, "--json"}
	case protocol.OperationAgentDriveStart:
		// The provider selects the unique live row for the session and rejects an
		// ambiguous target itself. The adapter passes no PID: a cluster generation
		// is not a provider PID, and inventing one would address a different
		// process than the one the Endpoint just revalidated.
		args = []string{"workspace", "driver", "start", "-s", providerKey, "--json"}
	case protocol.OperationAgentDriveStop:
		// Stop addresses the recorded controller, including a residual record whose
		// process is already gone, so it must not require a live target.
		args = []string{"workspace", "driver", "stop", "-s", providerKey, "--json"}
	case protocol.OperationAgentModelSelect:
		// The profile identifier is resolved through the durable mapping before any
		// provider call, so an identifier this Endpoint never minted is rejected
		// instead of being forwarded as a guess. A malformed payload is reported
		// separately, because it is a different failure from an unknown profile.
		modelArgs, modelCode, modelErr := a.selectModel(ctx, intent, providerKey)
		if modelErr != nil {
			return adapter.ExecuteResult{Receipt: failedReceipt(intent, modelCode)}, modelErr
		}
		args = modelArgs
	default:
		// The provider control family is addressed by a dynamic ctl.<action>
		// operation, so it cannot be a constant case label. controlActionArgs
		// matches the configured catalog before building any argv, so an action
		// the operator did not configure never reaches the provider.
		if !strings.HasPrefix(operation, security.ProviderControlPrefix) {
			return adapter.ExecuteResult{Receipt: failedReceipt(intent, "unsupported")}, adapter.ErrUnsupported
		}
		controlArgs, controlErr := controlActionArgs(a.config.ControlActions, operation, providerKey, intent.Payload)
		if controlErr != nil {
			// A payload that disagrees with a value the catalog entry fixes itself
			// is a different failure from an action the Endpoint does not serve.
			// Reporting "unconfigured" would send the operator looking for a
			// missing catalog entry when the entry exists and the payload is wrong.
			code := "control_action_unconfigured"
			if errors.Is(controlErr, errControlPayloadConflict) {
				code = "control_payload_conflict"
			}
			return adapter.ExecuteResult{Receipt: failedReceipt(intent, code)}, controlErr
		}
		args = controlArgs
	}
	output, runErr := a.run(ctx, args, stdin)
	if runErr != nil {
		// A non-zero exit still carries the provider's structured outcome document
		// for a rejected, failed or unconfirmed result. Decoding it preserves the
		// real effect certainty instead of flattening every failure to unknown.
		if receipt, ok := decodedFailureReceipt(intent, output); ok {
			return adapter.ExecuteResult{Receipt: receipt}, runErr
		}
		receipt := failedReceipt(intent, "provider_failed")
		receipt.EffectCertainty = protocol.EffectUnknown
		// The provider's own diagnostic is the only evidence of why the call
		// failed, so carry it verbatim instead of discarding it.
		receipt.ProviderResponse, receipt.ProviderResponseTruncated = adapter.BoundedProviderResponse(adapter.ProviderFailureText(runErr))
		return adapter.ExecuteResult{Receipt: receipt}, runErr
	}
	receipt := receiptFromJSON(intent, output)
	receipt.ProviderResponse, receipt.ProviderResponseTruncated = adapter.BoundedProviderResponse(string(output))
	return adapter.ExecuteResult{Receipt: receipt}, nil
}

// decodedFailureReceipt decodes the provider's own outcome document from a
// non-zero exit. It reports false when stdout carries no provider document, so
// the caller can fall back to the stderr diagnostic instead of losing it.
func decodedFailureReceipt(intent protocol.ImmutableIntent, output []byte) (protocol.ExecutionReceipt, bool) {
	trimmed := bytes.TrimSpace(output)
	if len(trimmed) == 0 {
		return protocol.ExecutionReceipt{}, false
	}
	// Only a document that actually carries a provider outcome is evidence. Any
	// other stdout content must not mask the stderr diagnostic.
	var probe map[string]json.RawMessage
	if json.Unmarshal(trimmed, &probe) != nil {
		return protocol.ExecutionReceipt{}, false
	}
	if _, ok := probe["delivery_state"]; !ok {
		if _, ok := probe["delivery_boundary"]; !ok {
			if _, ok := probe["error_code"]; !ok {
				return protocol.ExecutionReceipt{}, false
			}
		}
	}
	receipt := receiptFromJSON(intent, trimmed)
	receipt.ProviderResponse, receipt.ProviderResponseTruncated = adapter.BoundedProviderResponse(string(trimmed))
	return receipt, true
}

func interruptControlPayload(payload []byte) (string, []byte, error) {
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(payload, &envelope); err != nil || envelope == nil {
		return "", nil, errors.New("interrupt payload must be a JSON object")
	}
	var action string
	if err := json.Unmarshal(envelope["action"], &action); err != nil || action == "" {
		return "", nil, errors.New("interrupt payload action must be soft_interrupt or hard_interrupt")
	}
	delete(envelope, "action")
	switch action {
	case "soft_interrupt":
		if len(envelope) > 1 || (len(envelope) == 1 && envelope["message"] == nil) {
			return "", nil, errors.New("soft_interrupt accepts only an optional message")
		}
		if raw, ok := envelope["message"]; ok {
			var message string
			if err := json.Unmarshal(raw, &message); err != nil {
				return "", nil, errors.New("soft_interrupt message must be a string")
			}
		}
	case "hard_interrupt":
		if len(envelope) != 0 {
			return "", nil, errors.New("hard_interrupt does not accept arguments")
		}
	default:
		return "", nil, errors.New("interrupt payload action must be soft_interrupt or hard_interrupt")
	}
	args, err := json.Marshal(envelope)
	if err != nil {
		return "", nil, fmt.Errorf("encode interrupt payload: %w", err)
	}
	return action, args, nil
}

func runtimeMessage(payload []byte) (string, error) {
	var value struct {
		Text    string `json:"text"`
		Message string `json:"message"`
	}
	if err := json.Unmarshal(payload, &value); err != nil {
		return "", fmt.Errorf("decode runtime payload: %w", err)
	}
	if value.Text != "" {
		return value.Text, nil
	}
	if value.Message != "" {
		return value.Message, nil
	}
	return "", errors.New("runtime payload requires text or message")
}

func (a *Adapter) run(ctx context.Context, args []string, stdin []byte) ([]byte, error) {
	output, err := a.runner.Run(ctx, a.config.Executable, args, stdin)
	if len(output) > a.config.MaxOutput {
		return nil, fmt.Errorf("provider output exceeds limit")
	}
	// A non-zero provider exit still carries its structured outcome document on
	// stdout, so the captured bytes must reach the caller that decodes them.
	// Callers that treat any error as a plain failure simply ignore the output.
	return output, err
}

// ReadOutput returns one bounded runtime log snapshot.
func (a *Adapter) ReadOutput(ctx context.Context, request adapter.OutputRequest) (adapter.OutputResult, error) {
	target, err := a.providerSessionTarget(ctx, &request.Target)
	if err != nil {
		return adapter.OutputResult{}, err
	}
	lines := request.MaxLines
	if lines <= 0 || lines > 10000 {
		lines = 20
	}
	output, err := a.run(ctx, runtimeLogArgs(target, lines, false), nil)
	if err != nil {
		return adapter.OutputResult{}, err
	}
	var envelope struct {
		OK        bool   `json:"ok"`
		ErrorCode string `json:"error_code"`
		Response  *struct {
			Lines       []string `json:"lines"`
			Truncated   bool     `json:"truncated"`
			ScanLimited bool     `json:"scan_limited"`
		} `json:"response"`
	}
	if err := json.Unmarshal(output, &envelope); err != nil {
		return adapter.OutputResult{}, fmt.Errorf("decode runtime logs for %q: %w", target.SessionID, err)
	}
	if !envelope.OK || envelope.ErrorCode != "" {
		return adapter.OutputResult{}, fmt.Errorf("runtime logs for %q failed (ok=%t, error_code=%q)", target.SessionID, envelope.OK, envelope.ErrorCode)
	}
	if envelope.Response == nil || envelope.Response.Lines == nil {
		return adapter.OutputResult{}, fmt.Errorf("runtime logs for %q: missing response.lines", target.SessionID)
	}
	response := envelope.Response
	return adapter.OutputResult{Lines: response.Lines, Truncated: response.Truncated || response.ScanLimited, ScanLimited: response.ScanLimited, ObservedAtMS: time.Now().UnixMilli()}, nil
}

// FollowOutput streams runtime log records until the consumer stops or the
// provider stream ends.
//
// The provider rejects --json together with --follow, so this path passes plain
// text arguments and never decodes a document. Records are delivered as complete
// lines, and the runner sets PYTHONUNBUFFERED so they arrive as they are written
// instead of only at process exit.
//
// MaxBytes bounds one record, because one record is one chunk. A record longer
// than the budget is truncated and labelled rather than ending the stream, so an
// oversized provider line cannot be reported as a provider failure.
func (a *Adapter) FollowOutput(ctx context.Context, request protocol.OutputFollowRequest, emit func(protocol.OutputChunk) error) error {
	target, err := a.providerSessionTarget(ctx, &protocol.CommandTarget{Kind: "session", ResourceID: request.ResourceID, ProviderGeneration: request.ProviderGeneration})
	if err != nil {
		return err
	}
	lines := request.MaxLines
	if lines <= 0 || lines > 10000 {
		lines = 20
	}
	limit := request.MaxBytes
	if limit <= 0 {
		limit = followDefaultRecordBytes
	}
	if limit > followMaxRecordBytes {
		limit = followMaxRecordBytes
	}
	args := runtimeLogArgs(target, lines, true)
	return a.followRunner.Follow(ctx, a.config.Executable, args, limit, func(record followRecord) error {
		return emit(protocol.OutputChunk{Lines: []string{record.Line}, Truncated: record.Truncated, ObservedAtMS: time.Now().UnixMilli()})
	})
}

// QueryCommand reports that TopsailAI has no supported command reconciliation API.
// QueryCommand reports that command reconciliation is unsupported.
func (*Adapter) QueryCommand(context.Context, adapter.CommandQuery) (adapter.CommandResult, error) {
	return adapter.CommandResult{}, adapter.ErrUnsupported
}

// Watch reports that TopsailAI has no supported event stream.
// Watch reports that event streaming is unsupported.
func (*Adapter) Watch(context.Context) (<-chan adapter.Event, error) {
	return nil, adapter.ErrUnsupported
}

// Close releases adapter-local state and never stops an Agent.
// Close releases adapter-local resources.
func (a *Adapter) Close() error { return nil }

func receiptFromJSON(intent protocol.ImmutableIntent, output []byte) protocol.ExecutionReceipt {
	receipt := protocol.ExecutionReceipt{CommandID: intent.CommandID, Phase: protocol.PhaseReceiptRecorded, EffectCertainty: protocol.EffectUnknown, Outcome: "not_reported"}
	var response struct {
		DeliveryState    string `json:"delivery_state"`
		DeliveryBoundary string `json:"delivery_boundary"`
		SignalSent       bool   `json:"signal_sent"`
		ExitConfirmed    bool   `json:"exit_confirmed"`
		ErrorCode        string `json:"error_code"`
		Message          string `json:"message"`
	}
	if json.Unmarshal(output, &response) != nil {
		receipt.ErrorCode = "invalid_provider_response"
		return receipt
	}
	receipt.ExitConfirmed = response.ExitConfirmed
	boundary := response.DeliveryState
	if boundary == "" {
		boundary = response.DeliveryBoundary
	}
	switch boundary {
	case "submitted", "pipe_written", "injection_queued", "control_acknowledged":
		receipt.DeliveryBoundary = protocol.DeliverySubmitted
		receipt.EffectCertainty = protocol.EffectAcknowledged
	case "signal_sent":
		receipt.DeliveryBoundary = protocol.DeliverySignalSent
		receipt.EffectCertainty = protocol.EffectAcknowledged
	case "launched", "already_running", "status_read":
		// The provider verified the controller publication or read its state, so the
		// request itself is acknowledged. This is not a claim about agent work.
		receipt.DeliveryBoundary = protocol.DeliverySubmitted
		receipt.EffectCertainty = protocol.EffectAcknowledged
		receipt.Outcome = "succeeded"
	case "stopped", "already_stopped":
		// The provider confirmed the recorded controller process is absent, so the
		// signal is both sent and its exit confirmed.
		receipt.DeliveryBoundary = protocol.DeliverySignalSent
		receipt.EffectCertainty = protocol.EffectAcknowledged
		receipt.Outcome = "succeeded"
		receipt.ExitConfirmed = true
	case "rejected":
		receipt.Outcome = "rejected"
		receipt.EffectCertainty = protocol.EffectNotApplied
		receipt.ErrorCode = response.ErrorCode
	case "unconfirmed":
		// The provider delivered the request but could not confirm the outcome, so the
		// effect stays unknown instead of being reported as a definite failure.
		receipt.Outcome = "unconfirmed"
		receipt.EffectCertainty = protocol.EffectUnknown
		receipt.ErrorCode = response.ErrorCode
	case "failed":
		receipt.Outcome = "failed"
		receipt.EffectCertainty = protocol.EffectNotApplied
		receipt.ErrorCode = response.ErrorCode
	case "unknown":
		receipt.EffectCertainty = protocol.EffectUnknown
	default:
		if response.SignalSent && !response.ExitConfirmed {
			receipt.DeliveryBoundary = protocol.DeliverySignalSent
			receipt.EffectCertainty = protocol.EffectAcknowledged
		}
	}
	if response.Message != "" {
		receipt.ErrorMessage = strings.TrimSpace(response.Message)
	}
	return receipt
}

func failedReceipt(intent protocol.ImmutableIntent, code string) protocol.ExecutionReceipt {
	return protocol.ExecutionReceipt{CommandID: intent.CommandID, Phase: protocol.PhaseReceiptRecorded, EffectCertainty: protocol.EffectNotApplied, Outcome: "failed", ErrorCode: code}
}
