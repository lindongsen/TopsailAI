package node

import (
	"testing"
	"time"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// nodeTestCredential is the credential the fixture Node accepts.
//
// The secret is long enough to pass ValidateCredentialSecret, because a fixture that
// used a short secret would be refused when the set is built and the test would fail
// for a reason unrelated to what it checks.
var nodeTestCredential = security.Credential{
	KeyID:  "test-node",
	Secret: security.Secret("node-secret-0123456789abcdefghij"),
}

// nodeTestCredentialSet builds a set holding the fixture credential.
func nodeTestCredentialSet(t *testing.T) *security.CredentialSet {
	t.Helper()
	set, err := security.NewCredentialSet([]security.Credential{nodeTestCredential})
	if err != nil {
		t.Fatalf("NewCredentialSet() = %v, want nil", err)
	}
	return set
}

// signNodeRequest fills the Node proof on a request.
//
// The proof signs the logical operation, which is what the Node rebuilds from the
// request it receives. A test that wants to prove the Node refuses a tampered field
// signs first and changes the field afterwards, which is why this helper returns the
// request rather than a finished value.
func signNodeRequest(t *testing.T, request protocol.Request, credential security.Credential) protocol.Request {
	t.Helper()
	if request.RequestID == "" {
		requestID, err := security.NewRequestID()
		if err != nil {
			t.Fatalf("NewRequestID() = %v, want nil", err)
		}
		request.RequestID = requestID
	}
	nonce, err := security.NewNonce()
	if err != nil {
		t.Fatalf("NewNonce() = %v, want nil", err)
	}
	timestamp := time.Now().UnixMilli()
	canonical := security.CanonicalNodeOperation(
		request.NodeID,
		credential.KeyID,
		string(request.Operation),
		string(request.Scope),
		request.Path,
		request.Offset,
		request.Length,
		request.RequestID,
		timestamp,
		nonce,
	)
	request.NodeAuth = security.Proof{
		Scheme:      security.SchemeNode,
		Version:     security.ProofVersion,
		KeyID:       credential.KeyID,
		TimestampMS: timestamp,
		Nonce:       nonce,
		Signature:   security.Sign(credential.Secret, canonical),
	}
	return request
}
