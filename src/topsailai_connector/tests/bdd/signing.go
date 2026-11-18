//go:build bdd

package bdd

import (
	"testing"
	"time"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// bddNodeCredential is the credential the scenario Node accepts.
//
// The secret is long enough to pass ValidateCredentialSecret, because a fixture
// with a short secret would be refused when the set is built and the scenario
// would fail for a reason unrelated to what it checks.
var bddNodeCredential = security.Credential{
	KeyID:  "bdd-node",
	Secret: security.Secret("bdd-node-secret-0123456789abcdef"),
}

// bddUnknownCredential is a credential the Node does not hold. It is used to prove
// that a proof signed by a key the Node never issued is refused, which is the
// property that stops a compromised Server from minting one.
var bddUnknownCredential = security.Credential{
	KeyID:  "bdd-other",
	Secret: security.Secret("bdd-other-secret-0123456789abcdef"),
}

// bddCredentialSet builds the set the scenario Node holds.
func bddCredentialSet(t *testing.T) *security.CredentialSet {
	t.Helper()
	set, err := security.NewCredentialSet([]security.Credential{bddNodeCredential})
	if err != nil {
		t.Fatalf("NewCredentialSet() = %v, want nil", err)
	}
	return set
}

// signRequest fills the Node proof on a request.
//
// The proof signs the logical operation, which is what the Node rebuilds from the
// request it receives. A scenario that wants to prove the Node refuses a tampered
// field signs first and changes the field afterwards, which is why this helper
// returns the request rather than a finished value.
//
// ageMS shifts the timestamp into the past, so a scenario can present a proof that
// is correctly signed but no longer fresh. A negative value is not used: a proof
// from the future is refused by the same window check, and one direction is enough
// to prove the check runs.
func signRequest(t *testing.T, request protocol.Request, credential security.Credential, ageMS int64) protocol.Request {
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
	timestamp := time.Now().UnixMilli() - ageMS
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
