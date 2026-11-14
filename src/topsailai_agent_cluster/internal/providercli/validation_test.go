package providercli

import (
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func validVersion() Version {
	return Version{Protocol: ProtocolName, Major: ProtocolMajor, Minor: ProtocolMinor}
}

func validBudget() Budget {
	return Budget{MaxStdoutBytes: 1024, MaxStderrBytes: 1024, MaxRecords: 10}
}

func validRequest(function string) Request {
	return Request{
		Version:      validVersion(),
		RequestID:    "request-1",
		Function:     function,
		AdapterID:    "adapter-1",
		DeadlineAtMS: 1000,
		Budget:       validBudget(),
		Payload:      json.RawMessage(`{}`),
	}
}

func validObservation() ProviderObservation {
	return ProviderObservation{
		ProviderResourceKey: "provider-session-1",
		ProviderGeneration:  "generation-1",
		ResourceKind:        ResourceSession,
		State:               "running",
		ObservedAtMS:        1000,
		Attributes:          json.RawMessage(`{"display_name":"session"}`),
	}
}

func validDescriptor() Descriptor {
	return Descriptor{
		ProviderType:       "fixture",
		ProviderVersion:    "1.0.0",
		DescriptorRevision: "revision-1",
		ProtocolRange: ProtocolRange{
			Protocol: ProtocolName,
			Major:    ProtocolMajor,
			Minimum:  0,
			Maximum:  0,
		},
		Functions:   []string{FunctionDescribe, FunctionDiscover, FunctionExecute, FunctionQuery},
		Operations:  []NamedContract{{Name: "message.send", Version: "v1"}},
		Queries:     []NamedContract{{Name: QueryModelCatalog, Version: "v1"}},
		Limits:      validBudget(),
		Concurrency: ConcurrencyLimits{Total: 4, Discovery: 1, Mutation: 2, Follow: 1},
	}
}

// TestDescriptorValidatesControlActionMetadata proves a provider cannot publish
// a control action the Endpoint cannot interpret.
//
// The metadata is optional, because an operation or a query declares none. When a
// provider does declare it, an unknown target kind or safety class would be
// advertised verbatim, so the descriptor is rejected at decode time instead of
// reaching an operator as a capability nobody can act on.
func TestDescriptorValidatesControlActionMetadata(t *testing.T) {
	t.Run("accepts declared metadata", func(t *testing.T) {
		descriptor := validDescriptor()
		descriptor.ControlActions = []NamedContract{{
			Name:               "ctl.heartbeat",
			Version:            "v1",
			TargetKinds:        []string{ResourceSession},
			PayloadSchema:      `{"type":"object"}`,
			SafetyClass:        protocol.SafetyClassMutating,
			RequiredPermission: "control",
		}}
		if err := descriptor.validate(); err != nil {
			t.Fatalf("validate descriptor: %v", err)
		}
	})

	t.Run("rejects an unknown target kind", func(t *testing.T) {
		descriptor := validDescriptor()
		descriptor.ControlActions = []NamedContract{{Name: "ctl.heartbeat", Version: "v1", TargetKinds: []string{"galaxy"}}}
		if err := descriptor.validate(); err == nil {
			t.Fatal("validate descriptor accepted an unknown target kind")
		}
	})

	t.Run("rejects an unknown safety class", func(t *testing.T) {
		descriptor := validDescriptor()
		descriptor.ControlActions = []NamedContract{{Name: "ctl.heartbeat", Version: "v1", SafetyClass: "harmless"}}
		if err := descriptor.validate(); err == nil {
			t.Fatal("validate descriptor accepted an unknown safety class")
		}
	})

	t.Run("rejects a payload schema that is not JSON", func(t *testing.T) {
		descriptor := validDescriptor()
		descriptor.ControlActions = []NamedContract{{Name: "ctl.heartbeat", Version: "v1", PayloadSchema: "not json"}}
		if err := descriptor.validate(); err == nil {
			t.Fatal("validate descriptor accepted a payload schema that is not JSON")
		}
	})
}

func TestDecodeRequestStrictContract(t *testing.T) {
	request := validRequest(FunctionDescribe)
	encoded, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := DecodeRequest(encoded); err != nil {
		t.Fatalf("valid request rejected: %v", err)
	}

	unknown := strings.TrimSuffix(string(encoded), "}") + `,"command_id":"cluster-owned"}`
	if _, err := DecodeRequest([]byte(unknown)); err == nil || !strings.Contains(err.Error(), "unknown field") {
		t.Fatalf("Cluster authority field was not rejected: %v", err)
	}
	if _, err := DecodeRequest(append(encoded, []byte("\n{}")...)); err == nil || !strings.Contains(err.Error(), "extra JSON document") {
		t.Fatalf("extra request document was not rejected: %v", err)
	}
}

func TestDecodeRequiresFieldsWithZeroValues(t *testing.T) {
	tests := []struct {
		name   string
		decode func([]byte) error
		doc    string
		match  string
	}{
		{
			name: "request payload",
			decode: func(data []byte) error {
				_, err := DecodeRequest(data)
				return err
			},
			doc:   `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"request-1","function":"describe","adapter_id":"adapter-1","deadline_at_ms":1000,"budget":{"max_stdout_bytes":1,"max_stderr_bytes":1,"max_records":1}}`,
			match: "payload",
		},
		{
			name: "read request forbids present empty invocation ID",
			decode: func(data []byte) error {
				_, err := DecodeRequest(data)
				return err
			},
			doc:   `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"request-1","function":"describe","adapter_id":"adapter-1","invocation_id":"","deadline_at_ms":1000,"budget":{"max_stdout_bytes":1,"max_stderr_bytes":1,"max_records":1},"payload":{}}`,
			match: "invocation_id",
		},
		{
			name: "response ok",
			decode: func(data []byte) error {
				_, err := DecodeResponse(data)
				return err
			},
			doc:   `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"request-1","error":{"code":"failed","message":"failed","retryable":false,"effect_certainty":"not_applied"}}`,
			match: "ok",
		},
		{
			name: "descriptor minimum minor",
			decode: func(data []byte) error {
				_, err := DecodeResponse(data)
				return err
			},
			doc:   `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"request-1","ok":true,"descriptor":{"provider_type":"fixture","provider_version":"1","descriptor_revision":"r1","protocol_range":{"protocol":"agent-cluster-adapter","major":1,"maximum_minor":0},"functions":["describe"],"operations":[],"queries":[],"control_actions":[],"limits":{"max_stdout_bytes":1,"max_stderr_bytes":1,"max_records":1},"concurrency":{"total":1,"discovery":1,"mutation":1,"follow":1}}}`,
			match: "minimum_minor",
		},
		{
			name: "inspection live",
			decode: func(data []byte) error {
				_, err := DecodeResponse(data)
				return err
			},
			doc:   `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"request-1","ok":true,"inspection":{"found":false}}`,
			match: "live",
		},
		{
			name: "operation truncation evidence",
			decode: func(data []byte) error {
				_, err := DecodeResponse(data)
				return err
			},
			doc:   `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"request-1","ok":true,"result":{"delivery_boundary":"submitted","effect_certainty":"acknowledged","provider_outcome":"submitted"}}`,
			match: "provider_response_truncated",
		},
		{
			name: "operation present timestamp is positive",
			decode: func(data []byte) error {
				_, err := DecodeResponse(data)
				return err
			},
			doc:   `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"request-1","ok":true,"result":{"delivery_boundary":"submitted","effect_certainty":"acknowledged","provider_outcome":"submitted","provider_response_truncated":false,"started_at_ms":0}}`,
			match: "started_at_ms",
		},
		{
			name: "error retryable",
			decode: func(data []byte) error {
				_, err := DecodeResponse(data)
				return err
			},
			doc:   `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"request-1","ok":false,"error":{"code":"failed","message":"failed","effect_certainty":"not_applied"}}`,
			match: "retryable",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if err := test.decode([]byte(test.doc)); err == nil || !strings.Contains(err.Error(), test.match) {
				t.Fatalf("got error %v, want match %q", err, test.match)
			}
		})
	}
}

func TestRequestValidation(t *testing.T) {
	t.Run("execute requires identity target operation and operation-sensitive generation", func(t *testing.T) {
		request := validRequest(FunctionExecute)
		if err := request.Validate(); err == nil || !strings.Contains(err.Error(), "invocation_id") {
			t.Fatalf("missing invocation ID accepted: %v", err)
		}
		request.InvocationID = "invocation-1"
		request.Target = &Target{ResourceKind: ResourceSession, ProviderResourceKey: "provider-session-1"}
		request.Operation = &NamedContract{Name: "message.send", Version: "v1"}
		if err := request.Validate(); err == nil || !strings.Contains(err.Error(), "expected_generation") {
			t.Fatalf("live mutation without expected generation accepted: %v", err)
		}
		request.Target.ExpectedGeneration = "generation-1"
		if err := request.Validate(); err != nil {
			t.Fatalf("valid live execute request rejected: %v", err)
		}
	})

	t.Run("non-live authority operations may omit generation", func(t *testing.T) {
		for _, operation := range []string{
			protocol.OperationAgentResume,
			protocol.OperationAgentDriveStop,
			protocol.OperationWorkspaceClean,
		} {
			t.Run(operation, func(t *testing.T) {
				request := validRequest(FunctionExecute)
				request.InvocationID = "invocation-1"
				request.Target = &Target{ResourceKind: ResourceSession, ProviderResourceKey: "provider-session-1"}
				request.Operation = &NamedContract{Name: operation, Version: "v1"}
				if err := request.Validate(); err != nil {
					t.Fatalf("non-live mutation without generation rejected: %v", err)
				}
				request.Target.ExpectedGeneration = "generation-1"
				if err := request.Validate(); err != nil {
					t.Fatalf("non-live mutation with generation rejected: %v", err)
				}
			})
		}
	})

	t.Run("unknown operation and agent start require generation", func(t *testing.T) {
		for _, operation := range []string{"future.mutation", protocol.OperationAgentStart} {
			t.Run(operation, func(t *testing.T) {
				request := validRequest(FunctionExecute)
				request.InvocationID = "invocation-1"
				request.Target = &Target{ResourceKind: ResourceSession, ProviderResourceKey: "provider-session-1"}
				request.Operation = &NamedContract{Name: operation, Version: "v1"}
				if err := request.Validate(); err == nil || !strings.Contains(err.Error(), "expected_generation") {
					t.Fatalf("generation-required operation accepted without generation: %v", err)
				}
			})
		}
	})

	t.Run("query registry is closed", func(t *testing.T) {
		request := validRequest(FunctionQuery)
		request.Query = &NamedContract{Name: "provider.private.files", Version: "v1"}
		if err := request.Validate(); err == nil || !strings.Contains(err.Error(), "unregistered") {
			t.Fatalf("private query accepted: %v", err)
		}
		request.Query = &NamedContract{Name: QueryModelCatalog, Version: "v1"}
		if err := request.Validate(); err != nil {
			t.Fatalf("registered query rejected: %v", err)
		}
	})

	t.Run("invalid version payload deadline and identifier fail", func(t *testing.T) {
		cases := []Request{
			func() Request { r := validRequest(FunctionDescribe); r.Major = 2; return r }(),
			func() Request { r := validRequest(FunctionDescribe); r.Payload = json.RawMessage(`null`); return r }(),
			func() Request { r := validRequest(FunctionDescribe); r.DeadlineAtMS = 0; return r }(),
			func() Request {
				r := validRequest(FunctionDescribe)
				r.RequestID = strings.Repeat("x", MaxIdentifierBytes+1)
				return r
			}(),
		}
		for index, request := range cases {
			if err := request.Validate(); err == nil {
				t.Fatalf("invalid request %d accepted", index)
			}
		}
	})
}

func TestResponseValidationAndAuthorityBoundary(t *testing.T) {
	response := Response{
		Version:    validVersion(),
		RequestID:  "request-1",
		OK:         true,
		Descriptor: func() *Descriptor { value := validDescriptor(); return &value }(),
	}
	encoded, err := json.Marshal(response)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := DecodeResponse(encoded); err != nil {
		t.Fatalf("valid descriptor rejected: %v", err)
	}

	authorityFields := []string{"command_id", "journal_phase", "command_revision", "cluster_session_id"}
	for _, field := range authorityFields {
		operation := `{"protocol":"agent-cluster-adapter","major":1,"minor":0,"request_id":"request-1","ok":true,"result":{"delivery_boundary":"submitted","effect_certainty":"acknowledged","provider_outcome":"submitted","provider_response_truncated":false,"` + field + `":"forbidden"}}`
		if _, err := DecodeResponse([]byte(operation)); err == nil || !strings.Contains(err.Error(), "unknown field") {
			t.Fatalf("authority field %s was not rejected: %v", field, err)
		}
	}

	failedWithResult := Response{
		Version:   validVersion(),
		RequestID: "request-1",
		OK:        false,
		Result:    &OperationResult{DeliveryBoundary: DeliveryNotStarted, EffectCertainty: EffectNotApplied, ProviderOutcome: "rejected"},
		Error:     &ProviderError{Code: "rejected", Message: "no", EffectCertainty: EffectNotApplied},
	}
	if err := failedWithResult.Validate(); err == nil {
		t.Fatal("failed response with result document was accepted")
	}
}

func TestDiscoveryInspectionAndOutputValidation(t *testing.T) {
	discovery := DiscoveryResult{Observations: []ProviderObservation{validObservation()}, Complete: true}
	if err := discovery.validate(); err != nil {
		t.Fatalf("valid discovery rejected: %v", err)
	}
	nullAttributes := validObservation()
	nullAttributes.Attributes = json.RawMessage(`null`)
	if err := nullAttributes.validate(); err == nil || !strings.Contains(err.Error(), "must not be null") {
		t.Fatalf("null observation attributes accepted: %v", err)
	}
	if err := (DiscoveryResult{}).validate(); err == nil {
		t.Fatal("missing discovery observations accepted")
	}

	inspection := InspectionResult{Found: true, Live: false, Observation: func() *ProviderObservation { value := validObservation(); value.ProviderGeneration = ""; return &value }()}
	if err := inspection.validate(); err != nil {
		t.Fatalf("unverified found inspection rejected: %v", err)
	}
	if err := (InspectionResult{Found: false, Live: true}).validate(); err == nil {
		t.Fatal("live missing inspection accepted")
	}

	if err := (OutputSnapshot{ObservedAtMS: 1000, Content: "ok", Truncated: true, Complete: true}).validate(); err == nil {
		t.Fatal("truncated complete output accepted")
	}
}

func TestOperationResultRejectsNegativeTimestamp(t *testing.T) {
	result := OperationResult{
		DeliveryBoundary: DeliverySubmitted,
		EffectCertainty:  EffectAcknowledged,
		ProviderOutcome:  "submitted",
		StartedAtMS:      -1,
	}
	if err := result.validate(); err == nil || !strings.Contains(err.Error(), "timestamps") {
		t.Fatalf("negative operation timestamp accepted: %v", err)
	}
}
