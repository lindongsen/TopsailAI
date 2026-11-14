package providercli

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// DecodeRequest decodes exactly one strict Provider CLI request.
func DecodeRequest(data []byte) (Request, error) {
	var request Request
	if err := decodeStrict(data, &request); err != nil {
		return Request{}, fmt.Errorf("decode provider request: %w", err)
	}
	if err := validateRequestPresence(data); err != nil {
		return Request{}, err
	}
	if err := request.Validate(); err != nil {
		return Request{}, err
	}
	return request, nil
}

// DecodeResponse decodes exactly one strict Provider CLI response.
func DecodeResponse(data []byte) (Response, error) {
	var response Response
	if err := decodeStrict(data, &response); err != nil {
		return Response{}, fmt.Errorf("decode provider response: %w", err)
	}
	if err := validateResponsePresence(data); err != nil {
		return Response{}, err
	}
	if err := response.Validate(); err != nil {
		return Response{}, err
	}
	return response, nil
}

// DecodeStreamFrame decodes exactly one strict JSON Lines frame.
func DecodeStreamFrame(data []byte) (StreamFrame, error) {
	var frame StreamFrame
	if err := decodeStrict(data, &frame); err != nil {
		return StreamFrame{}, fmt.Errorf("decode provider stream frame: %w", err)
	}
	if err := validateStreamFramePresence(data); err != nil {
		return StreamFrame{}, err
	}
	if err := frame.Validate(); err != nil {
		return StreamFrame{}, err
	}
	return frame, nil
}

// Validate checks one Provider CLI request without granting Cluster authority.
func (r Request) Validate() error {
	if err := r.Version.validate(); err != nil {
		return err
	}
	if err := validateIdentifier("request_id", r.RequestID, true); err != nil {
		return err
	}
	if err := validateIdentifier("adapter_id", r.AdapterID, true); err != nil {
		return err
	}
	if !isFunction(r.Function) {
		return fmt.Errorf("unsupported provider function %q", r.Function)
	}
	if r.DeadlineAtMS < 1 {
		return errors.New("deadline_at_ms must be positive")
	}
	if err := r.Budget.validate(); err != nil {
		return err
	}
	if len(r.Payload) == 0 {
		return errors.New("payload is required")
	}
	if !json.Valid(r.Payload) {
		return errors.New("payload must be valid JSON")
	}
	if bytes.Equal(bytes.TrimSpace(r.Payload), []byte("null")) {
		return errors.New("payload must not be null")
	}

	switch r.Function {
	case FunctionExecute:
		return r.validateExecute()
	case FunctionQuery:
		return r.validateQuery()
	case FunctionInspect, FunctionReadOutput, FunctionFollowOutput:
		return r.validateTargetedRead()
	case FunctionQueryCommand:
		return r.validateQueryCommand()
	case FunctionDescribe, FunctionDiscover, FunctionWatch:
		return r.validateUntargetedRead()
	default:
		return fmt.Errorf("unsupported provider function %q", r.Function)
	}
}

func (r Request) validateExecute() error {
	if err := validateIdentifier("invocation_id", r.InvocationID, true); err != nil {
		return err
	}
	if r.Target == nil {
		return errors.New("execute target is required")
	}
	if r.Operation == nil {
		return errors.New("execute operation is required")
	}
	if err := r.Operation.validate("operation"); err != nil {
		return err
	}
	if err := r.Target.validate(OperationNeedsLiveGeneration(r.Operation.Name)); err != nil {
		return err
	}
	if r.Query != nil {
		return errors.New("execute request must not contain query")
	}
	switch r.Operation.Name {
	case protocol.OperationAgentStart:
		if _, err := DecodeAgentStartPayload(r.Payload); err != nil {
			return err
		}
	case protocol.OperationAgentModelSelect:
		if _, err := DecodeModelSelectPayload(r.Payload); err != nil {
			return err
		}
	}
	return nil
}

// nonLiveAuthorityOperations is the frozen Go source for operations whose
// authority comes from an exact non-live record check instead of process
// generation evidence. Schema tests require its set to match the wire contract.
var nonLiveAuthorityOperations = [...]string{
	protocol.OperationAgentResume,
	protocol.OperationAgentDriveStop,
	protocol.OperationWorkspaceClean,
}

// OperationNeedsLiveGeneration reports whether an operation requires live
// generation evidence. Unknown operations require generation so new mutations
// remain fail-closed until their authority rule is frozen explicitly.
func OperationNeedsLiveGeneration(operation string) bool {
	for _, exception := range nonLiveAuthorityOperations {
		if operation == exception {
			return false
		}
	}
	return true
}

func (r Request) validateQuery() error {
	if r.Query == nil {
		return errors.New("query contract is required")
	}
	if err := r.Query.validate("query"); err != nil {
		return err
	}
	if !IsStandardQuery(r.Query.Name, r.Query.Version) {
		return fmt.Errorf("unregistered standard query %q version %q", r.Query.Name, r.Query.Version)
	}
	if r.Operation != nil {
		return errors.New("query request must not contain operation")
	}
	if r.InvocationID != "" {
		return errors.New("read-only query must not contain invocation_id")
	}
	if r.Target != nil {
		return r.Target.validate(false)
	}
	return nil
}

func (r Request) validateTargetedRead() error {
	if err := r.validateNoContracts(); err != nil {
		return err
	}
	if r.InvocationID != "" {
		return fmt.Errorf("%s request must not contain invocation_id", r.Function)
	}
	if r.Target == nil {
		return fmt.Errorf("%s target is required", r.Function)
	}
	return r.Target.validate(false)
}

func (r Request) validateQueryCommand() error {
	if err := r.validateNoContracts(); err != nil {
		return err
	}
	if err := validateIdentifier("invocation_id", r.InvocationID, true); err != nil {
		return err
	}
	if r.Target != nil {
		return r.Target.validate(false)
	}
	return nil
}

func (r Request) validateUntargetedRead() error {
	if err := r.validateNoContracts(); err != nil {
		return err
	}
	if r.InvocationID != "" {
		return fmt.Errorf("%s request must not contain invocation_id", r.Function)
	}
	if r.Target != nil {
		return fmt.Errorf("%s request must not contain target", r.Function)
	}
	return nil
}

func (r Request) validateNoContracts() error {
	if r.Operation != nil || r.Query != nil {
		return fmt.Errorf("%s request must not contain operation or query", r.Function)
	}
	return nil
}

// Validate checks one correlated Provider CLI response.
func (r Response) Validate() error {
	if err := r.Version.validate(); err != nil {
		return err
	}
	if err := validateIdentifier("request_id", r.RequestID, true); err != nil {
		return err
	}
	if r.OK {
		if r.Error != nil {
			return errors.New("successful response must not contain error")
		}
		if responsePayloadCount(r) != 1 {
			return errors.New("successful response must contain exactly one result document")
		}
		return r.validateSuccessPayload()
	}
	if r.Error == nil {
		return errors.New("failed response requires error")
	}
	if responsePayloadCount(r) != 0 {
		return errors.New("failed response must not contain a result document")
	}
	return r.Error.validate()
}

func (r Response) validateSuccessPayload() error {
	if r.Descriptor != nil {
		return r.Descriptor.validate()
	}
	if r.Discovery != nil {
		return r.Discovery.validate()
	}
	if r.Inspection != nil {
		return r.Inspection.validate()
	}
	if r.Result != nil {
		return r.Result.validate()
	}
	if len(r.QueryResult) > 0 {
		if !json.Valid(r.QueryResult) {
			return errors.New("query_result must be valid JSON")
		}
		if bytes.Equal(bytes.TrimSpace(r.QueryResult), []byte("null")) {
			return errors.New("query_result must not be null")
		}
	}
	if r.Output != nil {
		return r.Output.validate()
	}
	return nil
}

func responsePayloadCount(response Response) int {
	count := 0
	if response.Descriptor != nil {
		count++
	}
	if response.Discovery != nil {
		count++
	}
	if response.Inspection != nil {
		count++
	}
	if response.Result != nil {
		count++
	}
	if len(response.QueryResult) > 0 {
		count++
	}
	if response.Output != nil {
		count++
	}
	return count
}

// Validate checks one Provider CLI stream frame before lifecycle validation.
func (f StreamFrame) Validate() error {
	if err := f.Version.validate(); err != nil {
		return err
	}
	if err := validateIdentifier("request_id", f.RequestID, true); err != nil {
		return err
	}
	if f.Sequence < 1 {
		return errors.New("stream sequence must be positive")
	}
	switch f.Type {
	case FrameStarted:
		if len(f.Record) > 0 || f.Error != nil || f.ObservedAtMS != 0 || f.Truncated {
			return errors.New("started frame must not contain record data or error")
		}
	case FrameRecord:
		if len(f.Record) == 0 || !json.Valid(f.Record) {
			return errors.New("record frame requires a valid JSON record")
		}
		if bytes.Equal(bytes.TrimSpace(f.Record), []byte("null")) {
			return errors.New("record frame must not contain null")
		}
		if f.ObservedAtMS < 1 {
			return errors.New("record frame observed_at_ms must be positive")
		}
		if f.Error != nil {
			return errors.New("record frame must not contain error")
		}
	case FrameEnd:
		if len(f.Record) > 0 || f.ObservedAtMS != 0 || f.Truncated {
			return errors.New("end frame must not contain record data")
		}
		if f.Error != nil {
			return f.Error.validate()
		}
	default:
		return fmt.Errorf("invalid stream frame type %q", f.Type)
	}
	return nil
}

func (v Version) validate() error {
	if v.Protocol != ProtocolName {
		return fmt.Errorf("invalid provider protocol %q", v.Protocol)
	}
	if v.Major != ProtocolMajor {
		return fmt.Errorf("incompatible provider protocol major %d", v.Major)
	}
	if v.Minor < 0 || v.Minor > ProtocolMinor {
		return fmt.Errorf("unsupported provider protocol minor %d", v.Minor)
	}
	return nil
}

func (r ProtocolRange) validate() error {
	if r.Protocol != ProtocolName {
		return fmt.Errorf("invalid descriptor protocol %q", r.Protocol)
	}
	if r.Major < 1 {
		return errors.New("descriptor protocol major must be positive")
	}
	if r.Minimum < 0 || r.Maximum < r.Minimum {
		return errors.New("descriptor minor range is invalid")
	}
	return nil
}

func (b Budget) validate() error {
	if b.MaxStdoutBytes < 1 || b.MaxStderrBytes < 1 || b.MaxRecords < 1 {
		return errors.New("provider budget values must be positive")
	}
	return nil
}

func (t Target) validate(requireGeneration bool) error {
	if !isResourceKind(t.ResourceKind) {
		return fmt.Errorf("invalid resource_kind %q", t.ResourceKind)
	}
	if err := validateProviderResourceKey("provider_resource_key", t.ProviderResourceKey, true); err != nil {
		return err
	}
	return validateIdentifier("expected_generation", t.ExpectedGeneration, requireGeneration)
}

func (n NamedContract) validate(label string) error {
	if err := validateIdentifier(label+" name", n.Name, true); err != nil {
		return err
	}
	if err := validateIdentifier(label+" version", n.Version, true); err != nil {
		return err
	}
	// The capability metadata is optional, because an operation or a query
	// declares none. When a provider does declare it, it must be well formed:
	// an unknown target kind or safety class would be advertised verbatim and
	// the Endpoint would publish a capability nobody can interpret.
	for _, kind := range n.TargetKinds {
		if !isResourceKind(kind) {
			return fmt.Errorf("%s %q declares invalid target kind %q", label, n.Name, kind)
		}
	}
	if n.SafetyClass != "" {
		if err := protocol.ValidateSafetyClass(n.SafetyClass); err != nil {
			return fmt.Errorf("%s %q: %w", label, n.Name, err)
		}
	}
	if n.PayloadSchema != "" && !json.Valid([]byte(n.PayloadSchema)) {
		return fmt.Errorf("%s %q payload schema must be valid JSON", label, n.Name)
	}
	return validateIdentifier(label+" required permission", n.RequiredPermission, false)
}

func (o ProviderObservation) validate() error {
	if err := validateProviderResourceKey("provider_resource_key", o.ProviderResourceKey, true); err != nil {
		return err
	}
	if err := validateIdentifier("provider_generation", o.ProviderGeneration, false); err != nil {
		return err
	}
	if !isResourceKind(o.ResourceKind) {
		return fmt.Errorf("invalid resource_kind %q", o.ResourceKind)
	}
	if err := validateIdentifier("observation state", o.State, true); err != nil {
		return err
	}
	if err := validateIdentifier("state_reason", o.StateReason, false); err != nil {
		return err
	}
	if o.ObservedAtMS < 1 {
		return errors.New("observation observed_at_ms must be positive")
	}
	if len(o.Attributes) > 0 {
		if !json.Valid(o.Attributes) {
			return errors.New("observation attributes must be valid JSON")
		}
		if bytes.Equal(bytes.TrimSpace(o.Attributes), []byte("null")) {
			return errors.New("observation attributes must not be null")
		}
	}
	return nil
}

func (d DiscoveryResult) validate() error {
	if d.Observations == nil {
		return errors.New("discovery observations are required")
	}
	for _, observation := range d.Observations {
		if err := observation.validate(); err != nil {
			return err
		}
	}
	return validateIdentifier("discovery checkpoint", d.Checkpoint, false)
}

func (i InspectionResult) validate() error {
	if i.Live && !i.Found {
		return errors.New("live inspection result must also be found")
	}
	if i.Found && i.Observation == nil {
		return errors.New("found inspection result requires observation")
	}
	if !i.Found && i.Observation != nil {
		return errors.New("missing inspection result must not contain observation")
	}
	if i.Observation != nil {
		return i.Observation.validate()
	}
	return nil
}

func (s OutputSnapshot) validate() error {
	if s.ObservedAtMS < 1 {
		return errors.New("output observed_at_ms must be positive")
	}
	if !utf8.ValidString(s.Content) {
		return errors.New("output content must be valid UTF-8")
	}
	if s.Truncated && s.Complete {
		return errors.New("truncated output must not be complete")
	}
	return nil
}

func (d Descriptor) validate() error {
	if err := validateIdentifier("provider_type", d.ProviderType, true); err != nil {
		return err
	}
	if err := validateIdentifier("provider_version", d.ProviderVersion, true); err != nil {
		return err
	}
	if err := validateIdentifier("descriptor_revision", d.DescriptorRevision, true); err != nil {
		return err
	}
	if err := d.ProtocolRange.validate(); err != nil {
		return err
	}
	if len(d.Functions) == 0 {
		return errors.New("descriptor functions are required")
	}
	seenFunctions := make(map[string]struct{}, len(d.Functions))
	for _, function := range d.Functions {
		if !isFunction(function) {
			return fmt.Errorf("descriptor advertises unsupported function %q", function)
		}
		if _, exists := seenFunctions[function]; exists {
			return fmt.Errorf("descriptor repeats function %q", function)
		}
		seenFunctions[function] = struct{}{}
	}
	if _, exists := seenFunctions[FunctionDescribe]; !exists {
		return errors.New("descriptor must advertise describe")
	}
	if err := validateNamedContracts("operation", d.Operations, false); err != nil {
		return err
	}
	if err := validateNamedContracts("query", d.Queries, true); err != nil {
		return err
	}
	if err := validateNamedContracts("control action", d.ControlActions, false); err != nil {
		return err
	}
	if err := d.Limits.validate(); err != nil {
		return err
	}
	if d.Concurrency.Total < 1 || d.Concurrency.Discovery < 1 ||
		d.Concurrency.Mutation < 1 || d.Concurrency.Follow < 1 {
		return errors.New("descriptor concurrency values must be positive")
	}
	if d.Concurrency.Discovery > d.Concurrency.Total ||
		d.Concurrency.Mutation > d.Concurrency.Total ||
		d.Concurrency.Follow > d.Concurrency.Total {
		return errors.New("descriptor class concurrency exceeds total")
	}
	return nil
}

func validateNamedContracts(label string, contracts []NamedContract, requireStandardQuery bool) error {
	seen := make(map[string]struct{}, len(contracts))
	for _, contract := range contracts {
		if err := contract.validate(label); err != nil {
			return err
		}
		key := contract.Name + "\x00" + contract.Version
		if _, exists := seen[key]; exists {
			return fmt.Errorf("descriptor repeats %s %q version %q", label, contract.Name, contract.Version)
		}
		seen[key] = struct{}{}
		if requireStandardQuery && !IsStandardQuery(contract.Name, contract.Version) {
			return fmt.Errorf("descriptor advertises unregistered query %q version %q", contract.Name, contract.Version)
		}
	}
	return nil
}

func (r OperationResult) validate() error {
	if err := validateIdentifier("provider_request_ref", r.ProviderRequestRef, false); err != nil {
		return err
	}
	if !isDeliveryBoundary(r.DeliveryBoundary) {
		return fmt.Errorf("invalid delivery_boundary %q", r.DeliveryBoundary)
	}
	if !isEffectCertainty(r.EffectCertainty) {
		return fmt.Errorf("invalid effect_certainty %q", r.EffectCertainty)
	}
	if err := validateIdentifier("provider_outcome", r.ProviderOutcome, true); err != nil {
		return err
	}
	if len(r.ProviderResponse) > MaxProviderResponseBytes {
		return fmt.Errorf("provider_response exceeds %d bytes", MaxProviderResponseBytes)
	}
	if r.StartedAtMS < 0 || r.FinishedAtMS < 0 {
		return errors.New("operation result timestamps must be positive when present")
	}
	if r.FinishedAtMS > 0 && r.StartedAtMS > r.FinishedAtMS {
		return errors.New("operation result finishes before it starts")
	}
	return nil
}

func (e ProviderError) validate() error {
	if err := validateIdentifier("error code", e.Code, true); err != nil {
		return err
	}
	if e.Message == "" {
		return errors.New("error message is required")
	}
	if !utf8.ValidString(e.Message) {
		return errors.New("error message must be valid UTF-8")
	}
	if len(e.Message) > MaxErrorMessageBytes {
		return fmt.Errorf("error message exceeds %d bytes", MaxErrorMessageBytes)
	}
	if !isEffectCertainty(e.EffectCertainty) {
		return fmt.Errorf("invalid effect_certainty %q", e.EffectCertainty)
	}
	return nil
}

func validateIdentifier(name, value string, required bool) error {
	if value == "" {
		if required {
			return fmt.Errorf("%s is required", name)
		}
		return nil
	}
	if !utf8.ValidString(value) {
		return fmt.Errorf("%s must be valid UTF-8", name)
	}
	if strings.TrimSpace(value) != value {
		return fmt.Errorf("%s must not have leading or trailing whitespace", name)
	}
	if len(value) > MaxIdentifierBytes {
		return fmt.Errorf("%s exceeds %d bytes", name, MaxIdentifierBytes)
	}
	return nil
}

// validateProviderResourceKey rejects a Cluster resource ID where a
// provider-private key belongs.
//
// The contract states that Cluster resource IDs never cross into provider
// authority, and the Endpoint alone maps a provider key to a Cluster ID. A
// provider that received a Cluster ID would be addressing a resource by an
// identity it cannot resolve, so the value must be refused at the seam rather
// than forwarded and failing later as an unexplained not-found.
func validateProviderResourceKey(name, value string, required bool) error {
	if err := validateIdentifier(name, value, required); err != nil {
		return err
	}
	if protocol.IsClusterResourceID(value) {
		return fmt.Errorf("%s must be a provider-private key, not a Cluster resource ID %q", name, value)
	}
	return nil
}

func decodeStrict(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("extra JSON document")
		}
		return err
	}
	return nil
}

func isFunction(value string) bool {
	switch value {
	case FunctionDescribe, FunctionDiscover, FunctionInspect, FunctionExecute, FunctionQuery,
		FunctionQueryCommand, FunctionReadOutput, FunctionFollowOutput, FunctionWatch:
		return true
	default:
		return false
	}
}

func isResourceKind(value string) bool {
	return protocol.IsResourceKind(value)
}

func isDeliveryBoundary(value string) bool {
	switch value {
	case DeliveryNotStarted, DeliverySubmitted, DeliverySignalSent, DeliveryPipeWritten:
		return true
	default:
		return false
	}
}

func isEffectCertainty(value string) bool {
	switch value {
	case EffectNotApplied, EffectAcknowledged, EffectUnknown:
		return true
	default:
		return false
	}
}
