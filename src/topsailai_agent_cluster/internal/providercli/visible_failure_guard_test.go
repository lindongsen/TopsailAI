package providercli

import (
	"strings"
	"testing"
)

// responseDocument builds one response document around a result object, using the
// protocol constants rather than literals so a protocol change fails here.
func responseDocument(t *testing.T, result string) []byte {
	t.Helper()
	return []byte(`{"protocol":"` + ProtocolName + `","major":1,"minor":0,"request_id":"request-1","ok":true,"result":` + result + `}`)
}

// operationResult builds one operation result object from the named fields.
func operationResult(boundary, certainty, outcome string, exitConfirmed bool) string {
	exit := "false"
	if exitConfirmed {
		exit = "true"
	}
	return `{"delivery_boundary":"` + boundary + `","effect_certainty":"` + certainty +
		`","provider_outcome":"` + outcome + `","provider_response_truncated":false,"exit_confirmed":` + exit + `}`
}

// TestExitConfirmationRequiresAStartedProcess proves a provider cannot confirm an
// exit at a boundary where no process was started, while every boundary that does
// start a process still accepts the confirmation.
func TestExitConfirmationRequiresAStartedProcess(t *testing.T) {
	rejected := []struct {
		name     string
		boundary string
	}{
		{"not_started", DeliveryNotStarted},
	}
	for _, c := range rejected {
		document := responseDocument(t, operationResult(c.boundary, EffectNotApplied, "failed", true))
		_, err := DecodeResponse(document)
		if err == nil {
			t.Fatalf("confirmed exit at %s is accepted, so a provider can confirm an exit it never signalled", c.name)
		}
		if !strings.Contains(err.Error(), c.boundary) {
			t.Fatalf("confirmed exit at %s is rejected without naming the boundary: %v", c.name, err)
		}
	}

	accepted := []struct {
		name      string
		boundary  string
		certainty string
	}{
		{"submitted", DeliverySubmitted, EffectNotApplied},
		{"signal_sent", DeliverySignalSent, EffectAcknowledged},
		{"pipe_written", DeliveryPipeWritten, EffectAcknowledged},
	}
	for _, c := range accepted {
		document := responseDocument(t, operationResult(c.boundary, c.certainty, "ok", true))
		if _, err := DecodeResponse(document); err != nil {
			t.Fatalf("confirmed exit at %s is rejected even though a process was started: %v", c.name, err)
		}
	}

	unconfirmed := []struct {
		name      string
		boundary  string
		certainty string
	}{
		{"not_started", DeliveryNotStarted, EffectNotApplied},
		{"signal_sent", DeliverySignalSent, EffectAcknowledged},
	}
	for _, c := range unconfirmed {
		document := responseDocument(t, operationResult(c.boundary, c.certainty, "ok", false))
		if _, err := DecodeResponse(document); err != nil {
			t.Fatalf("unconfirmed exit at %s is rejected: %v", c.name, err)
		}
	}
}

// TestExtraStandardOutputIsRejected proves a response document followed by any
// further content is rejected rather than silently truncated to the first value.
func TestExtraStandardOutputIsRejected(t *testing.T) {
	baseline := responseDocument(t, operationResult(DeliverySubmitted, EffectNotApplied, "ok", false))
	if _, err := DecodeResponse(baseline); err != nil {
		t.Fatalf("baseline response is rejected, so this guard cannot prove anything: %v", err)
	}
	cases := []struct {
		name string
		doc  []byte
	}{
		{"trailing json document", append(append([]byte(nil), baseline...), []byte(`{"extra":1}`)...)},
		{"trailing text", append(append([]byte(nil), baseline...), []byte("garbage")...)},
		{"leading text", append([]byte("garbage"), baseline...)},
		{"two responses", append(append([]byte(nil), baseline...), baseline...)},
	}
	for _, c := range cases {
		if _, err := DecodeResponse(c.doc); err == nil {
			t.Fatalf("%s is accepted, so extra provider output is silently ignored", c.name)
		}
	}
}

// TestMalformedJSONIsRejected proves a malformed document fails visibly instead of
// decoding into an empty response that a caller could mistake for a result.
func TestMalformedJSONIsRejected(t *testing.T) {
	cases := []struct {
		name string
		doc  []byte
	}{
		{"truncated document", []byte(`{"protocol":"` + ProtocolName + `","major":1,"minor":0,"request_id":"request-1","ok":tr`)},
		{"empty output", []byte(``)},
		{"null document", []byte(`null`)},
		{"array document", []byte(`[]`)},
		{"unterminated string", []byte(`{"protocol":"` + ProtocolName + `","major":1,"minor":0,"request_id":"request-1","ok":true,"result":{"delivery_boundary":"submitted","effect_certainty":"not_applied","provider_outcome":"ok","provider_response_truncated":false,"provider_response":"unterminated}`)},
	}
	for _, c := range cases {
		response, err := DecodeResponse(c.doc)
		if err == nil {
			t.Fatalf("%s is accepted as %+v, so a malformed document can look like a result", c.name, response)
		}
	}
}

// TestMismatchedRequestIDIsRejected proves a response carrying another request's
// identifier is rejected instead of being accepted as this request's answer.
func TestMismatchedRequestIDIsRejected(t *testing.T) {
	request := Request{
		Version:   Version{Protocol: ProtocolName, Major: ProtocolMajor, Minor: ProtocolMinor},
		RequestID: "request-1",
		Function:  FunctionDescribe,
	}
	matched := Response{
		Version:   request.Version,
		RequestID: request.RequestID,
		OK:        true,
	}
	if err := ValidateResponseCorrelation(request, matched); err != nil {
		t.Fatalf("matching response is rejected, so this guard cannot prove anything: %v", err)
	}
	for _, other := range []string{"request-2", "request-10", "REQUEST-1"} {
		mismatched := matched
		mismatched.RequestID = other
		err := ValidateResponseCorrelation(request, mismatched)
		if err == nil {
			t.Fatalf("response carrying request_id %q is accepted for request %q", other, request.RequestID)
		}
		if !strings.Contains(err.Error(), other) {
			t.Fatalf("mismatched request_id %q is rejected without naming it: %v", other, err)
		}
	}
}

// TestStreamRequestIDMismatchIsRejected proves a stream frame carrying another
// request's identifier is rejected by the stream lifecycle validator.
func TestStreamRequestIDMismatchIsRejected(t *testing.T) {
	validator, err := NewStreamValidator("request-1")
	if err != nil {
		t.Fatalf("create stream validator: %v", err)
	}
	correlated := StreamFrame{
		Version:   Version{Protocol: ProtocolName, Major: ProtocolMajor, Minor: ProtocolMinor},
		RequestID: "request-1",
		Type:      FrameStarted,
		Sequence:  1,
	}
	if err := validator.Accept(correlated); err != nil {
		t.Fatalf("correlated started frame is rejected, so this guard cannot prove anything: %v", err)
	}
	other, err := NewStreamValidator("request-1")
	if err != nil {
		t.Fatalf("create stream validator: %v", err)
	}
	mismatched := correlated
	mismatched.RequestID = "request-2"
	err = other.Accept(mismatched)
	if err == nil {
		t.Fatal("a started frame carrying a different request_id is accepted")
	}
	if !strings.Contains(err.Error(), "request-2") {
		t.Fatalf("mismatched stream request_id is rejected without naming it: %v", err)
	}
}
