package security

import (
	"context"
	"crypto/x509"
	"encoding/pem"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func TestBearerAuthenticatorValidation(t *testing.T) {
	tests := []struct {
		name      string
		token     string
		header    string
		wantID    string
		wantValid bool
	}{
		{name: "valid", token: "secret", header: "Bearer secret", wantID: "operator", wantValid: true},
		{name: "missing token configuration", header: "Bearer secret"},
		{name: "missing header", token: "secret"},
		{name: "wrong scheme", token: "secret", header: "Basic secret"},
		{name: "wrong token", token: "secret", header: "Bearer other"},
		{name: "token prefix only", token: "secret", header: "Bearer "},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			req := httptest.NewRequest("GET", "/", nil)
			if test.header != "" {
				req.Header.Set("Authorization", test.header)
			}
			identity, valid := (BearerAuthenticator{Token: test.token}).Authenticate(req)
			if identity != test.wantID || valid != test.wantValid {
				t.Fatalf("identity=%q valid=%v, want %q %v", identity, valid, test.wantID, test.wantValid)
			}
		})
	}
}

func TestAuthenticatedIdentityContext(t *testing.T) {
	if identity, ok := AuthenticatedIdentity(context.Background()); ok || identity != "" {
		t.Fatalf("background context returned identity=%q ok=%v", identity, ok)
	}
	ctx := WithAuthenticatedIdentity(context.Background(), "operator")
	identity, ok := AuthenticatedIdentity(ctx)
	if !ok || identity != "operator" {
		t.Fatalf("identity=%q ok=%v", identity, ok)
	}
	ctx = WithAuthenticatedIdentity(ctx, "")
	if identity, ok := AuthenticatedIdentity(ctx); ok || identity != "" {
		t.Fatalf("empty identity returned identity=%q ok=%v", identity, ok)
	}
}

func TestNewRequestIDFormatAndUniqueness(t *testing.T) {
	first := NewRequestID()
	second := NewRequestID()
	if !strings.HasPrefix(first, "req_") || len(first) != len("req_")+32 {
		t.Fatalf("unexpected first request ID %q", first)
	}
	if first == second {
		t.Fatalf("request IDs are not unique: %q", first)
	}
}

func TestCertificateHelpers(t *testing.T) {
	material := newTLSMaterial(t)
	data, err := os.ReadFile(material.clientCert)
	if err != nil {
		t.Fatal(err)
	}
	block, _ := pem.Decode(data)
	certificate, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		t.Fatal(err)
	}
	tests := map[string]struct {
		endpointID string
		wantErr    bool
	}{
		"common name": {endpointID: "endpoint-1"},
		"dns name":    {endpointID: "endpoint-1"},
		"mismatch":    {endpointID: "other", wantErr: true},
		"empty":       {wantErr: true},
	}
	for name, test := range tests {
		t.Run(name, func(t *testing.T) {
			err := ValidateEndpointIdentity(certificate, test.endpointID)
			if (err != nil) != test.wantErr {
				t.Fatalf("ValidateEndpointIdentity error=%v, want error=%v", err, test.wantErr)
			}
		})
	}
	if err := ValidateEndpointIdentity(nil, "endpoint-1"); err == nil {
		t.Fatal("nil certificate was accepted")
	}
	if !IsCertificateRevoked(certificate, map[string]bool{certificate.SerialNumber.String(): true}) {
		t.Fatal("revoked certificate was not detected")
	}
	if IsCertificateRevoked(nil, nil) || IsCertificateRevoked(certificate, map[string]bool{}) {
		t.Fatal("unrevoked certificate was reported revoked")
	}
	fingerprint := CertificateFingerprint(certificate)
	if len(fingerprint) != 64 || fingerprint != strings.ToUpper(fingerprint) {
		t.Fatalf("unexpected fingerprint %q", fingerprint)
	}
}
