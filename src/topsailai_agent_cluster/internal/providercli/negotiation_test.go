package providercli

import (
	"strings"
	"testing"
)

func TestNegotiateVersion(t *testing.T) {
	compatible := ProtocolRange{
		Protocol: ProtocolName,
		Major:    ProtocolMajor,
		Minimum:  0,
		Maximum:  ProtocolMinor + 1,
	}
	version, err := NegotiateVersion(compatible)
	if err != nil {
		t.Fatalf("compatible range rejected: %v", err)
	}
	if version != validVersion() {
		t.Fatalf("version = %#v, want %#v", version, validVersion())
	}

	incompatibleMajor := compatible
	incompatibleMajor.Major++
	if _, err := NegotiateVersion(incompatibleMajor); err == nil || !strings.Contains(err.Error(), "incompatible") {
		t.Fatalf("incompatible major accepted: %v", err)
	}

	futureOnly := compatible
	futureOnly.Minimum = ProtocolMinor + 1
	if _, err := NegotiateVersion(futureOnly); err == nil || !strings.Contains(err.Error(), "no common") {
		t.Fatalf("future-only minor range accepted: %v", err)
	}
}

func TestValidateResponseCorrelation(t *testing.T) {
	request := validRequest(FunctionDescribe)
	response := Response{Version: request.Version, RequestID: request.RequestID}
	if err := ValidateResponseCorrelation(request, response); err != nil {
		t.Fatalf("correlated response rejected: %v", err)
	}

	response.RequestID = "request-2"
	if err := ValidateResponseCorrelation(request, response); err == nil || !strings.Contains(err.Error(), "request_id") {
		t.Fatalf("mismatched request ID accepted: %v", err)
	}
	response.RequestID = request.RequestID
	response.Minor++
	if err := ValidateResponseCorrelation(request, response); err == nil || !strings.Contains(err.Error(), "version") {
		t.Fatalf("mismatched version accepted: %v", err)
	}
}
