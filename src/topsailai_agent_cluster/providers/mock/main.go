package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"
)

const (
	faultEnvironment  = "AGENT_CLUSTER_MOCK_FAULT"
	helperEnvironment = "AGENT_CLUSTER_MOCK_HELPER"
	fixtureTimeMS     = int64(1700000000000)
)

// main reads one request and emits one deterministic fixture response.
func main() {
	if os.Getenv(helperEnvironment) == "1" {
		time.Sleep(30 * time.Second)
		return
	}
	requestDocument, err := io.ReadAll(io.LimitReader(os.Stdin, 1<<20))
	if err != nil {
		writeDiagnostic("read request: %v", err)
		os.Exit(2)
	}
	request, err := decodeRequest(requestDocument)
	if err != nil {
		writeDiagnostic("decode request: %v", err)
		os.Exit(2)
	}
	fault := os.Getenv(faultEnvironment)
	if fault == "timeout" {
		if err := startHelper(); err != nil {
			writeDiagnostic("start helper: %v", err)
			os.Exit(2)
		}
		time.Sleep(30 * time.Second)
		return
	}
	if fault == "empty-stdout" {
		return
	}
	if fault == "malformed-json" {
		_, _ = io.WriteString(os.Stdout, "{not-json")
		return
	}
	if fault == "oversized-stdout" {
		_, _ = io.WriteString(os.Stdout, strings.Repeat("x", int(request.Budget.MaxStdoutBytes)+1024))
		return
	}
	if fault == "helper-leak" {
		if err := startHelper(); err != nil {
			writeDiagnostic("start helper: %v", err)
			os.Exit(2)
		}
	}
	if request.Function == functionFollowOutput {
		if err := writeStream(request, fault); err != nil {
			writeDiagnostic("write stream: %v", err)
			os.Exit(2)
		}
		return
	}
	response := handleUnary(request, fault)
	if fault == "wrong-request-id" {
		response.RequestID = "wrong-request-id"
	}
	if fault == "wrong-version" {
		response.Minor++
	}
	encoded, err := json.Marshal(response)
	if err != nil {
		writeDiagnostic("encode response: %v", err)
		os.Exit(2)
	}
	if fault == "stdout-banner" {
		_, _ = io.WriteString(os.Stdout, "mock provider ready\n")
	}
	if fault == "oversized-stderr" {
		_, _ = io.WriteString(os.Stderr, strings.Repeat("e", int(request.Budget.MaxStderrBytes)+1024))
	}
	_, _ = os.Stdout.Write(encoded)
	if fault == "duplicate-response" {
		_, _ = os.Stdout.Write([]byte("\n"))
		_, _ = os.Stdout.Write(encoded)
	}
	if fault == "exit-result-conflict" {
		os.Exit(7)
	}
}

// decodeRequest enforces the strict public request envelope.
func decodeRequest(data []byte) (request, error) {
	var value request
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&value); err != nil {
		return request{}, err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return request{}, errors.New("extra JSON document")
		}
		return request{}, err
	}
	if value.Protocol != protocolName || value.Major != protocolMajor || value.Minor != protocolMinor {
		return request{}, errors.New("unsupported protocol version")
	}
	if value.RequestID == "" || value.AdapterID == "" || value.Function == "" || len(value.Payload) == 0 {
		return request{}, errors.New("required request field is empty")
	}
	return value, nil
}

// handleUnary dispatches one deterministic unary fixture.
func handleUnary(request request, fault string) response {
	base := response{version: currentVersion(), RequestID: request.RequestID, OK: true}
	switch request.Function {
	case functionDescribe:
		descriptor := mockDescriptor(fault)
		base.Descriptor = &descriptor
	case functionDiscover:
		base.Discovery = &discoveryResult{
			Observations: []providerObservation{fixtureObservation()},
			Complete:     true,
			Checkpoint:   "checkpoint-1",
		}
	case functionInspect:
		observation := fixtureObservation()
		base.Inspection = &inspectionResult{Found: true, Live: true, Observation: &observation}
	case functionExecute:
		return executeResponse(request, fault)
	case functionQuery:
		if request.Query == nil || request.Query.Name != queryModelCatalog || fault == "false-capability" {
			return failureResponse(request.RequestID, "unsupported", "query is unsupported", "not_applied")
		}
		base.QueryResult = json.RawMessage(`{"profiles":[{"provider_resource_key":"model:mock","display_name":"Mock"}]}`)
	case functionQueryCommand:
		base.Result = &operationResult{
			ProviderRequestRef:        "provider-ref-1",
			DeliveryBoundary:          "submitted",
			EffectCertainty:           "acknowledged",
			ProviderOutcome:           "reconciled",
			ProviderResponseTruncated: false,
			StartedAtMS:               fixtureTimeMS,
			FinishedAtMS:              fixtureTimeMS + 1,
		}
	case functionReadOutput:
		base.Output = &outputSnapshot{ObservedAtMS: fixtureTimeMS, Content: "mock output\n", Complete: true}
	default:
		return failureResponse(request.RequestID, "unsupported", "function is unsupported", "not_applied")
	}
	return base
}

// executeResponse revalidates generation inside the mutation path.
func executeResponse(request request, fault string) response {
	if request.Target == nil || request.Target.ExpectedGeneration != "generation-1" || fault == "generation-race" {
		return failureResponse(request.RequestID, "generation_mismatch", "provider generation changed", "not_applied")
	}
	if request.Operation == nil || request.Operation.Name != "message.send" || request.Operation.Version != "v1" {
		return failureResponse(request.RequestID, "unsupported", "operation is unsupported", "not_applied")
	}
	return response{
		version:   currentVersion(),
		RequestID: request.RequestID,
		OK:        true,
		Result: &operationResult{
			ProviderRequestRef:        "provider-ref-1",
			DeliveryBoundary:          "pipe_written",
			EffectCertainty:           "acknowledged",
			ProviderOutcome:           "submitted",
			ProviderResponse:          `{"ok":true}`,
			ProviderResponseTruncated: false,
			StartedAtMS:               fixtureTimeMS,
			FinishedAtMS:              fixtureTimeMS + 1,
		},
	}
}

// mockDescriptor returns the deterministic Provider CLI surface.
func mockDescriptor(fault string) descriptor {
	queries := []namedContract{{Name: queryModelCatalog, Version: "v1"}}
	return descriptor{
		ProviderType:       "mock",
		ProviderVersion:    "1.0.0",
		DescriptorRevision: "mock-v1",
		ProtocolRange: protocolRange{
			Protocol: protocolName,
			Major:    protocolMajor,
			Minimum:  protocolMinor,
			Maximum:  protocolMinor,
		},
		Functions: []string{
			functionDescribe,
			functionDiscover,
			functionInspect,
			functionExecute,
			functionQuery,
			functionQueryCommand,
			functionReadOutput,
			functionFollowOutput,
		},
		Operations:     []namedContract{{Name: "message.send", Version: "v1"}},
		Queries:        queries,
		ControlActions: []namedContract{},
		Limits: budget{
			MaxStdoutBytes: 1 << 20,
			MaxStderrBytes: 64 << 10,
			MaxRecords:     128,
		},
		Concurrency: concurrencyLimits{Total: 4, Discovery: 2, Mutation: 1, Follow: 2},
	}
}

// fixtureObservation returns the stable cross-process discovery identity.
func fixtureObservation() providerObservation {
	return providerObservation{
		ProviderResourceKey: "session:stable",
		ProviderGeneration:  "generation-1",
		ResourceKind:        resourceSession,
		State:               "running",
		ObservedAtMS:        fixtureTimeMS,
		Attributes:          json.RawMessage(`{"display_name":"Mock Session"}`),
	}
}

// failureResponse builds one standard Provider CLI rejection.
func failureResponse(requestID, code, message, certainty string) response {
	return response{
		version:   currentVersion(),
		RequestID: requestID,
		OK:        false,
		Error: &providerError{
			Code:            code,
			Message:         message,
			Retryable:       false,
			EffectCertainty: certainty,
		},
	}
}

// writeStream emits deterministic JSONL frames and selected lifecycle faults.
func writeStream(request request, fault string) error {
	streamRequestID := request.RequestID
	if fault == "stream-correlation" {
		streamRequestID = "wrong-request-id"
	}
	frames := []streamFrame{
		{version: currentVersion(), RequestID: streamRequestID, Type: "started", Sequence: 1},
		{
			version:      currentVersion(),
			RequestID:    streamRequestID,
			Type:         "record",
			Sequence:     2,
			ObservedAtMS: fixtureTimeMS,
			Record:       json.RawMessage(`{"text":"mock output"}`),
		},
	}
	if fault == "record-overflow" {
		for sequence := int64(3); sequence <= 20; sequence++ {
			frames = append(frames, streamFrame{
				version: currentVersion(), RequestID: streamRequestID, Type: "record", Sequence: sequence,
				ObservedAtMS: fixtureTimeMS + sequence, Record: json.RawMessage(`{"text":"overflow"}`),
			})
		}
		frames = append(frames, streamFrame{version: currentVersion(), RequestID: streamRequestID, Type: "end", Sequence: 21})
	} else if fault != "missing-terminal" {
		frames = append(frames, streamFrame{version: currentVersion(), RequestID: streamRequestID, Type: "end", Sequence: 3})
	}
	if fault == "duplicate-terminal" {
		frames = append(frames, streamFrame{version: currentVersion(), RequestID: request.RequestID, Type: "end", Sequence: 4})
	}
	if fault == "post-terminal-record" {
		frames = append(frames, streamFrame{
			version:      currentVersion(),
			RequestID:    request.RequestID,
			Type:         "record",
			Sequence:     4,
			ObservedAtMS: fixtureTimeMS + 1,
			Record:       json.RawMessage(`{"text":"late"}`),
		})
	}
	encoder := json.NewEncoder(os.Stdout)
	for _, frame := range frames {
		if err := encoder.Encode(frame); err != nil {
			return err
		}
	}
	return nil
}

// startHelper creates a same-group child for exact cleanup verification.
func startHelper() error {
	command := exec.Command(os.Args[0])
	command.Env = append(os.Environ(), helperEnvironment+"=1", faultEnvironment+"=")
	command.Stdin = nil
	command.Stdout = nil
	command.Stderr = nil
	if err := command.Start(); err != nil {
		return err
	}
	writeDiagnostic("helper_pid=%d", command.Process.Pid)
	return nil
}

// writeDiagnostic writes local fixture evidence to stderr.
func writeDiagnostic(format string, values ...any) {
	_, _ = fmt.Fprintf(os.Stderr, format+"\n", values...)
}
