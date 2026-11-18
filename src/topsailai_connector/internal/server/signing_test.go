package server

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"topsailai_connector/internal/security"
)

// testClientCredential is the client credential the fixture Server accepts.
//
// The secret is long enough to pass ValidateCredentialSecret, because a fixture that
// used a short secret would be refused at configuration time and the test would fail
// for a reason unrelated to what it checks.
var testClientCredential = security.Credential{
	KeyID:  "operator",
	Secret: security.Secret("client-secret-0123456789abcdefghij"),
}

// testNodeCredential is the credential the fixture Node would accept.
//
// The Server never verifies a Node proof, so the fixture only needs a well formed
// proof. It is signed anyway, so a test that inspects the forwarded value sees the
// shape a real CLI produces rather than a placeholder.
var testNodeCredential = security.Credential{
	KeyID:  "node-operator",
	Secret: security.Secret("node-secret-0123456789abcdefghij"),
}

// testCredentialSet builds a set holding the fixture client credential.
func testCredentialSet(t *testing.T) *security.CredentialSet {
	t.Helper()
	set, err := security.NewCredentialSet([]security.Credential{testClientCredential})
	if err != nil {
		t.Fatalf("NewCredentialSet() = %v", err)
	}
	return set
}

// nodeProofFor builds a well formed Node proof header for one request.
//
// The proof signs the logical operation, which is what the Node rebuilds from the
// forwarded request. The Server only parses it, so a test that wants to prove the
// Server refuses a malformed envelope can replace the returned value.
func nodeProofFor(t *testing.T, nodeID, requestID, body string) string {
	t.Helper()
	nonce, err := security.NewNonce()
	if err != nil {
		t.Fatalf("NewNonce() = %v", err)
	}
	timestamp := time.Now().UnixMilli()
	canonical := security.CanonicalNodeOperation(
		nodeID,
		testNodeCredential.KeyID,
		"file.read",
		"project",
		"a.txt",
		0,
		0,
		requestID,
		timestamp,
		nonce,
	)
	return security.FormatProof(security.Proof{
		Scheme:      security.SchemeNode,
		Version:     security.ProofVersion,
		KeyID:       testNodeCredential.KeyID,
		TimestampMS: timestamp,
		Nonce:       nonce,
		Signature:   security.Sign(testNodeCredential.Secret, canonical),
	})
}

// signedRequest builds a POST carrying a valid client proof and a well formed Node
// proof.
//
// The client proof binds the method, the request target, the raw body digest, the
// exact Node proof header digest, the request id, the timestamp and the nonce, so the
// helper must build the header before it signs. A test that changes any of those
// values afterwards is testing the binding, which is why the helper returns the
// request rather than a finished recorder.
func signedRequest(t *testing.T, nodeID, body string) *http.Request {
	t.Helper()
	requestID, err := security.NewRequestID()
	if err != nil {
		t.Fatalf("NewRequestID() = %v", err)
	}
	return signedRequestWithID(t, nodeID, body, requestID)
}

// signedRequestWithID builds a signed POST with a caller supplied request id.
func signedRequestWithID(t *testing.T, nodeID, body, requestID string) *http.Request {
	t.Helper()
	request := httptest.NewRequest(http.MethodPost, OperationPathPrefix+nodeID+OperationPathSuffix, strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(security.RequestIDHeader, requestID)

	nodeProof := nodeProofFor(t, nodeID, requestID, body)
	request.Header.Set(security.NodeAuthHeader, nodeProof)

	nonce, err := security.NewNonce()
	if err != nil {
		t.Fatalf("NewNonce() = %v", err)
	}
	timestamp := time.Now().UnixMilli()
	canonical := security.CanonicalClientRequest(
		request.Method,
		request.URL.RequestURI(),
		security.BodyDigest([]byte(body), body != ""),
		security.BytesDigest([]byte(nodeProof)),
		requestID,
		timestamp,
		nonce,
	)
	request.Header.Set(security.ClientAuthHeader, security.FormatProof(security.Proof{
		Scheme:      security.SchemeClient,
		Version:     security.ProofVersion,
		KeyID:       testClientCredential.KeyID,
		TimestampMS: timestamp,
		Nonce:       nonce,
		Signature:   security.Sign(testClientCredential.Secret, canonical),
	}))
	return request
}

// signedRequestWithNodeProofHeader builds a signed POST whose Node proof header is an
// arbitrary value.
//
// The client proof binds the exact Node proof header bytes, so a test that wants to
// prove the Server refuses a malformed or substituted Node proof must sign over that
// value. Signing over a different value would make the client proof fail first, and the
// test would then be measuring the client check instead of the Node check.
func signedRequestWithNodeProofHeader(t *testing.T, nodeID, body, nodeProofHeader string) *http.Request {
	t.Helper()
	requestID, err := security.NewRequestID()
	if err != nil {
		t.Fatalf("NewRequestID() = %v", err)
	}
	request := httptest.NewRequest(http.MethodPost, OperationPathPrefix+nodeID+OperationPathSuffix, strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(security.RequestIDHeader, requestID)
	request.Header.Set(security.NodeAuthHeader, nodeProofHeader)

	nonce, err := security.NewNonce()
	if err != nil {
		t.Fatalf("NewNonce() = %v", err)
	}
	timestamp := time.Now().UnixMilli()
	canonical := security.CanonicalClientRequest(
		request.Method,
		request.URL.RequestURI(),
		security.BodyDigest([]byte(body), body != ""),
		security.BytesDigest([]byte(nodeProofHeader)),
		requestID,
		timestamp,
		nonce,
	)
	request.Header.Set(security.ClientAuthHeader, security.FormatProof(security.Proof{
		Scheme:      security.SchemeClient,
		Version:     security.ProofVersion,
		KeyID:       testClientCredential.KeyID,
		TimestampMS: timestamp,
		Nonce:       nonce,
		Signature:   security.Sign(testClientCredential.Secret, canonical),
	}))
	return request
}
