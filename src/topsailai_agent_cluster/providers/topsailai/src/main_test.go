package main

import (
	"bytes"
	"context"
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

// validRequest returns one minimal frozen Provider CLI request.
func validRequest(function string) request {
	return request{
		version:      currentVersion(),
		RequestID:    "request-1",
		Function:     function,
		AdapterID:    "topsailai-primary",
		DeadlineAtMS: 1_700_000_030_000,
		Budget: budget{
			MaxStdoutBytes: 1 << 20,
			MaxStderrBytes: 64 << 10,
			MaxRecords:     100,
		},
		Payload: json.RawMessage(`{}`),
	}
}

// encodeRequest serializes one test request.
func encodeRequest(t *testing.T, request request) []byte {
	t.Helper()
	document, err := json.Marshal(request)
	if err != nil {
		t.Fatalf("marshal request: %v", err)
	}
	return document
}

// TestServeDescribe verifies the truthful Unit 5A descriptor.
func TestServeDescribe(t *testing.T) {
	var output bytes.Buffer
	if err := serve(bytes.NewReader(encodeRequest(t, validRequest(functionDescribe))), &output); err != nil {
		t.Fatalf("serve describe: %v", err)
	}
	var response response
	if err := json.Unmarshal(output.Bytes(), &response); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if !response.OK || response.Descriptor == nil {
		t.Fatalf("response = %+v", response)
	}
	wantFunctions := []string{functionDescribe, functionDiscover, functionInspect, functionResolve, functionExecute, functionQuery, functionReadOutput, functionFollowOutput}
	if got := response.Descriptor.Functions; !reflect.DeepEqual(got, wantFunctions) {
		t.Fatalf("functions = %v want %v", got, wantFunctions)
	}
	if len(response.Descriptor.Operations) != 12 || len(response.Descriptor.Queries) != 8 || len(response.Descriptor.ControlActions) != 0 {
		t.Fatalf("descriptor contracts: %+v", response.Descriptor)
	}
}

// TestServeRejectsUnknownField verifies strict request framing.
func TestServeRejectsUnknownField(t *testing.T) {
	document := strings.TrimSuffix(string(encodeRequest(t, validRequest(functionDescribe))), "}") + `,"executable":"evil"}`
	var output bytes.Buffer
	err := serve(strings.NewReader(document), &output)
	if err == nil || !strings.Contains(err.Error(), "unknown field") {
		t.Fatalf("error = %v", err)
	}
	if output.Len() != 0 {
		t.Fatalf("unexpected output = %q", output.String())
	}
}

// TestServeRejectsExtraDocument verifies exactly-one-document input.
func TestServeRejectsExtraDocument(t *testing.T) {
	document := append(encodeRequest(t, validRequest(functionDescribe)), []byte(` {}`)...)
	var output bytes.Buffer
	err := serve(bytes.NewReader(document), &output)
	if err == nil || !strings.Contains(err.Error(), "extra JSON document") {
		t.Fatalf("error = %v", err)
	}
}

// TestDispatchRejectsUnimplementedFunction verifies fail-closed dispatch.
//
// The function must be one this executable genuinely does not serve. execute is
// implemented now, so using it here would assert the opposite of the truth.
func TestDispatchRejectsUnimplementedFunction(t *testing.T) {
	response := newProvider(stubCommandRunner{}, controlCatalog{}, supportedPlatform, "", "").dispatch(context.Background(), validRequest(functionWatch))
	if response.OK || response.Error == nil {
		t.Fatalf("response = %+v", response)
	}
	if response.Error.Code != "unsupported" || response.Error.EffectCertainty != effectNotApplied {
		t.Fatalf("error = %+v", response.Error)
	}
}

type stubCommandRunner struct{}

func (stubCommandRunner) Run(context.Context, []string, []byte) ([]byte, []byte, error) {
	return nil, nil, nil
}
