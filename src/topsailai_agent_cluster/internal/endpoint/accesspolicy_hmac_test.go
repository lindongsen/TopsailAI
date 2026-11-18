package endpoint

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// signedReadFrame builds one read request frame carrying a signed credential for
// the supplied operation.
//
// The digest is a fixed value rather than a real request digest, because the
// Endpoint never recomputes it: it verifies the signature over the digest the
// Server forwarded. A test therefore only has to use the same value on both sides.
func signedReadFrame(t *testing.T, kind, operation, endpointID, keyID, secret, digest string) channel.Frame {
	t.Helper()
	nonce := security.NewNonce()
	if nonce == "" {
		t.Fatalf("no nonce available")
	}
	timestampMS := time.Now().UnixMilli()
	credential := security.EndpointCredential{
		KeyID:       keyID,
		TimestampMS: timestampMS,
		Nonce:       nonce,
		Signature:   security.Sign(secret, security.CanonicalFrameRequest(operation, endpointID, digest, timestampMS, nonce)),
	}
	frame := channel.Frame{Type: kind, ProtocolVersion: channel.ProtocolVersion, RequestID: "req-hmac", EndpointCredential: &credential, EndpointRequestDigest: digest}
	switch kind {
	case channel.FrameOutputRequest:
		frame.OutputRequest = &protocol.OutputSnapshotRequest{ResourceID: "r1", ProviderGeneration: "g1"}
	case channel.FrameHistoryRequest:
		frame.HistoryQuery = &protocol.HistoryQuery{Limit: 10}
	case channel.FrameMessagesRequest:
		frame.MessagesQuery = &protocol.MessagesQuery{ProviderSessionID: "s1"}
	case channel.FrameModelCatalogRequest:
		frame.ModelCatalogQuery = &protocol.ModelCatalogQuery{Target: protocol.CommandTarget{Kind: "session", ResourceID: "r1", ProviderGeneration: "g1"}}
	}
	return frame
}

// hmacService builds a Service in HMAC mode over a policy declaring one signed
// caller.
func hmacService(t *testing.T, policyContent string) (*Service, *serviceChannel, *countingExecutor) {
	t.Helper()
	dir := t.TempDir()
	writePolicyFile(t, dir, "signed.conf", policyContent)
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load policy: %v", err)
	}
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	transport := newServiceChannel()
	executor := &countingExecutor{}
	service, err := NewService(ServiceDeps{
		Collector:    &serviceCollector{},
		Channel:      transport,
		Storage:      store,
		Executor:     executor,
		AccessPolicy: loaded.Policy,
		EndpointID:   "endpoint-1",
		AuthMode:     string(security.ModeHMAC),
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}
	return service, transport, executor
}

// TestHMACSignatureGrantsDeclaredOperation verifies the positive path: a correctly
// signed credential for a declared key identifier reaches the adapter.
func TestHMACSignatureGrantsDeclaredOperation(t *testing.T) {
	service, transport, executor := hmacService(t, "key-id ops\ntoken ops.s3cret\npermissions output.read\n")
	frame := signedReadFrame(t, channel.FrameOutputRequest, protocol.OperationOutputRead, "endpoint-1", "ops", "s3cret", "digest-1")
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 1 {
		t.Fatalf("adapter calls = %d, want 1", executor.outputCalls)
	}
	if got := lastFrameOfType(t, transport, channel.FrameOutputResponse).OutputResponse.ErrorCode; got != "" {
		t.Fatalf("a granted signed read must not report %q", got)
	}
}

// TestHMACBadSignatureNeverReachesPolicy verifies the ordering the whole design
// depends on: a caller that cannot prove possession of the secret is refused before
// the grant table is consulted.
//
// The policy in this test grants the operation, so a policy-first implementation
// would admit the request. The assertion is therefore about the order, not about
// the grant: the adapter must not be called, and the refusal must be the
// credential code rather than a policy code or a success. Asserting the policy
// code here would let a collapsed implementation pass, because a caller that
// cannot prove its credential would be told to edit a policy file that is
// already correct.
func TestHMACBadSignatureNeverReachesPolicy(t *testing.T) {
	service, transport, executor := hmacService(t, "key-id ops\ntoken ops.s3cret\npermissions output.read\n")
	frame := signedReadFrame(t, channel.FrameOutputRequest, protocol.OperationOutputRead, "endpoint-1", "ops", "wrong-secret", "digest-1")
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 0 {
		t.Fatalf("adapter calls = %d, want 0: a bad signature must not reach the adapter", executor.outputCalls)
	}
	if got := lastFrameOfType(t, transport, channel.FrameOutputResponse).OutputResponse.ErrorCode; got != credentialRejectedCode {
		t.Fatalf("refusal code = %q, want %q", got, credentialRejectedCode)
	}
}

// TestHMACSignatureForAnotherOperationIsRefused verifies that the signed message
// covers the operation name.
//
// Without that coverage a credential captured for one read could be replayed for a
// different one, so an operator granted only a harmless read could exercise a
// stronger read with the same proof.
func TestHMACSignatureForAnotherOperationIsRefused(t *testing.T) {
	service, transport, executor := hmacService(t, "key-id ops\ntoken ops.s3cret\nallow-all\n")
	// Signed for history.read but presented as an output read.
	frame := signedReadFrame(t, channel.FrameOutputRequest, OperationHistoryRead, "endpoint-1", "ops", "s3cret", "digest-1")
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 0 {
		t.Fatalf("adapter calls = %d, want 0: a signature for another operation must be refused", executor.outputCalls)
	}
	if got := lastFrameOfType(t, transport, channel.FrameOutputResponse).OutputResponse.ErrorCode; got != credentialRejectedCode {
		t.Fatalf("refusal code = %q, want %q", got, credentialRejectedCode)
	}
}

// TestHMACSignatureForAnotherEndpointIsRefused verifies that the signed message
// covers the Endpoint identity, so a credential captured on one machine cannot be
// replayed against another.
func TestHMACSignatureForAnotherEndpointIsRefused(t *testing.T) {
	service, transport, executor := hmacService(t, "key-id ops\ntoken ops.s3cret\nallow-all\n")
	frame := signedReadFrame(t, channel.FrameOutputRequest, protocol.OperationOutputRead, "endpoint-2", "ops", "s3cret", "digest-1")
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 0 {
		t.Fatalf("adapter calls = %d, want 0: a signature for another endpoint must be refused", executor.outputCalls)
	}
	if got := lastFrameOfType(t, transport, channel.FrameOutputResponse).OutputResponse.ErrorCode; got != credentialRejectedCode {
		t.Fatalf("refusal code = %q, want %q", got, credentialRejectedCode)
	}
}

// TestHMACSignatureForAnotherRequestIsRefused verifies that the signed message
// covers the request digest, so a captured signature cannot be replayed against a
// different request.
func TestHMACSignatureForAnotherRequestIsRefused(t *testing.T) {
	service, transport, executor := hmacService(t, "key-id ops\ntoken ops.s3cret\nallow-all\n")
	frame := signedReadFrame(t, channel.FrameOutputRequest, protocol.OperationOutputRead, "endpoint-1", "ops", "s3cret", "digest-1")
	frame.EndpointRequestDigest = "digest-2"
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 0 {
		t.Fatalf("adapter calls = %d, want 0: a signature for another request must be refused", executor.outputCalls)
	}
	if got := lastFrameOfType(t, transport, channel.FrameOutputResponse).OutputResponse.ErrorCode; got != credentialRejectedCode {
		t.Fatalf("refusal code = %q, want %q", got, credentialRejectedCode)
	}
}

// TestHMACReplayOfTheSameRequestIsRefused verifies that a correctly signed request
// cannot be replayed inside the signature window.
//
// The nonce cache is the only thing that stops this, because the signature itself
// stays valid until the timestamp leaves the window.
func TestHMACReplayOfTheSameRequestIsRefused(t *testing.T) {
	service, transport, executor := hmacService(t, "key-id ops\ntoken ops.s3cret\nallow-all\n")
	frame := signedReadFrame(t, channel.FrameOutputRequest, protocol.OperationOutputRead, "endpoint-1", "ops", "s3cret", "digest-1")
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 1 {
		t.Fatalf("first adapter calls = %d, want 1", executor.outputCalls)
	}
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 1 {
		t.Fatalf("adapter calls after replay = %d, want 1: a replayed nonce must be refused", executor.outputCalls)
	}
	if got := lastFrameOfType(t, transport, channel.FrameOutputResponse).OutputResponse.ErrorCode; got != credentialRejectedCode {
		t.Fatalf("replay refusal code = %q, want %q", got, credentialRejectedCode)
	}
}

// TestHMACVerifiedKeyIDWithoutGrantIsRefusedByPolicy verifies the other half of the
// ordering: a caller that proves possession of a secret the policy does not grant
// is refused by the policy, not by authentication.
//
// The two refusals carry different codes, so this test is the one that proves the
// split is not a blanket rename: the key identifier is declared, so verification
// succeeds, and only the permission is missing, so the refusal must be the policy
// code. A test that asserted the credential code here would pass on an
// implementation that refused everything as an authentication failure.
func TestHMACVerifiedKeyIDWithoutGrantIsRefusedByPolicy(t *testing.T) {
	service, transport, executor := hmacService(t, "key-id ops\ntoken ops.s3cret\npermissions history.read\n")
	frame := signedReadFrame(t, channel.FrameOutputRequest, protocol.OperationOutputRead, "endpoint-1", "ops", "s3cret", "digest-1")
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 0 {
		t.Fatalf("adapter calls = %d, want 0", executor.outputCalls)
	}
	if got := lastFrameOfType(t, transport, channel.FrameOutputResponse).OutputResponse.ErrorCode; got != policyDeniedCode {
		t.Fatalf("refusal code = %q, want %q", got, policyDeniedCode)
	}
}

// TestHMACModeRefusesBearerCredential verifies that HMAC mode never falls back to
// the weaker syntax.
//
// A fallback would let any caller downgrade the Endpoint by sending the secret in
// the clear, which is the exact exposure HMAC mode exists to remove.
func TestHMACModeRefusesBearerCredential(t *testing.T) {
	service, transport, executor := hmacService(t, "token ops.s3cret\nallow-all\n")
	frame := channel.Frame{Type: channel.FrameOutputRequest, ProtocolVersion: channel.ProtocolVersion, RequestID: "req-bearer", EndpointCredential: &security.EndpointCredential{Token: "ops.s3cret"}, OutputRequest: &protocol.OutputSnapshotRequest{ResourceID: "r1", ProviderGeneration: "g1"}}
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 0 {
		t.Fatalf("adapter calls = %d, want 0: a bearer credential must be refused in hmac mode", executor.outputCalls)
	}
	if got := lastFrameOfType(t, transport, channel.FrameOutputResponse).OutputResponse.ErrorCode; got != credentialRejectedCode {
		t.Fatalf("refusal code = %q, want %q", got, credentialRejectedCode)
	}
}

// TestBearerModeRefusesSignedCredential verifies the symmetric rule: bearer mode
// refuses a signed credential rather than comparing a proof against a secret.
func TestBearerModeRefusesSignedCredential(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "legacy.conf", "token plain-secret\nallow-all\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load policy: %v", err)
	}
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	transport := newServiceChannel()
	executor := &countingExecutor{}
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, Executor: executor, AccessPolicy: loaded.Policy, EndpointID: "endpoint-1", AuthMode: string(security.ModeBearer)})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}
	frame := signedReadFrame(t, channel.FrameOutputRequest, protocol.OperationOutputRead, "endpoint-1", "ops", "s3cret", "digest-1")
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 0 {
		t.Fatalf("adapter calls = %d, want 0: a signed credential must be refused in bearer mode", executor.outputCalls)
	}
	if got := lastFrameOfType(t, transport, channel.FrameOutputResponse).OutputResponse.ErrorCode; got != credentialRejectedCode {
		t.Fatalf("refusal code = %q, want %q", got, credentialRejectedCode)
	}
}

// TestHMACRefusalNamesTheCredentialForm verifies that the refusal message names the
// credential form rather than the caller's grants.
//
// The operator's next action differs: a wrong form means the caller must be
// reconfigured to sign, while a missing grant means the policy must be edited.
// Reporting one message for both sends every investigation to the same place.
func TestHMACRefusalNamesTheCredentialForm(t *testing.T) {
	service, _, _ := hmacService(t, "key-id ops\ntoken ops.s3cret\nallow-all\n")
	frame := channel.Frame{Type: channel.FrameOutputRequest, ProtocolVersion: channel.ProtocolVersion, RequestID: "req-none", OutputRequest: &protocol.OutputSnapshotRequest{ResourceID: "r1", ProviderGeneration: "g1"}}
	_, _, err := VerifyEndpointCredential(credentialOf(frame), service.authMode, service.verifier(), service.endpointID, protocol.OperationOutputRead, frame.EndpointRequestDigest)
	if err == nil {
		t.Fatalf("an absent credential must be refused in hmac mode")
	}
	if !strings.Contains(err.Error(), "signed") {
		t.Fatalf("refusal %q must name the credential form", err.Error())
	}
}

// TestRefusalCodeSeparatesCredentialFromPolicy proves the classifier answers the
// two classes with two codes.
//
// It is a unit test of the classifier rather than of a handler because the
// classifier is the single place the class is decided: the read path, the command
// path and the Endpoint entry point all ask it. A test that only exercised one
// handler would leave the other two free to disagree.
func TestRefusalCodeSeparatesCredentialFromPolicy(t *testing.T) {
	credential := CredentialRefusal(errors.New("signature does not match"))
	if got := RefusalCode(credential); got != credentialRejectedCode {
		t.Fatalf("credential refusal code = %q, want %q", got, credentialRejectedCode)
	}
	policy := errors.New("operation is not granted")
	if got := RefusalCode(policy); got != policyDeniedCode {
		t.Fatalf("policy refusal code = %q, want %q", got, policyDeniedCode)
	}
	if got := RefusalCode(nil); got != policyDeniedCode {
		t.Fatalf("nil refusal code = %q, want %q", got, policyDeniedCode)
	}
}

// TestCredentialRefusalPreservesTheCause proves the wrapper carries the class
// without discarding the reason.
//
// The specific reason is what tells the operator whether to reconfigure the
// caller, rotate a secret or correct a clock, so a wrapper that replaced it with a
// generic message would make the split useless in practice.
func TestCredentialRefusalPreservesTheCause(t *testing.T) {
	cause := errors.New("signature timestamp is outside the accepted window")
	wrapped := CredentialRefusal(cause)
	if !errors.Is(wrapped, cause) {
		t.Fatalf("wrapped refusal does not unwrap to its cause")
	}
	if wrapped.Error() != cause.Error() {
		t.Fatalf("wrapped message = %q, want %q", wrapped.Error(), cause.Error())
	}
	if CredentialRefusal(nil) != nil {
		t.Fatalf("wrapping nil must stay nil so a caller can wrap unconditionally")
	}
}

// TestBadSignatureIsRefusedAsACredentialNotAPolicy proves the read path reports
// the credential class on the wire.
//
// The policy in this test grants the operation, so an implementation that
// consulted the policy first would admit the request. The assertion is therefore
// about both the order and the class: the adapter must not be called, and the
// code must name the credential.
func TestBadSignatureIsRefusedAsACredentialNotAPolicy(t *testing.T) {
	service, transport, executor := hmacService(t, "key-id ops\ntoken ops.s3cret\nallow-all\n")
	frame := signedReadFrame(t, channel.FrameOutputRequest, protocol.OperationOutputRead, "endpoint-1", "ops", "wrong-secret", "digest-1")
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 0 {
		t.Fatalf("adapter calls = %d, want 0", executor.outputCalls)
	}
	if got := lastFrameOfType(t, transport, channel.FrameOutputResponse).OutputResponse.ErrorCode; got != credentialRejectedCode {
		t.Fatalf("refusal code = %q, want %q", got, credentialRejectedCode)
	}
}

// TestVerifiedButUngrantedIsRefusedAsAPolicy proves the other direction on the
// wire: a proven credential without the grant is a policy refusal.
//
// Without this case the split could be implemented as "always credential", which
// would send every operator with a correct credential to rotate a secret that is
// already right.
func TestVerifiedButUngrantedIsRefusedAsAPolicy(t *testing.T) {
	service, transport, executor := hmacService(t, "key-id ops\ntoken ops.s3cret\npermissions history.read\n")
	frame := signedReadFrame(t, channel.FrameOutputRequest, protocol.OperationOutputRead, "endpoint-1", "ops", "s3cret", "digest-1")
	service.outputFrame(context.Background(), frame)
	if executor.outputCalls != 0 {
		t.Fatalf("adapter calls = %d, want 0", executor.outputCalls)
	}
	if got := lastFrameOfType(t, transport, channel.FrameOutputResponse).OutputResponse.ErrorCode; got != policyDeniedCode {
		t.Fatalf("refusal code = %q, want %q", got, policyDeniedCode)
	}
}

// TestCredentialRefusalIsLoggedAsACredential proves the log line names the class.
//
// The code tells the caller, and the log tells the operator reading the Endpoint
// log. A log that said "access policy refused" for an authentication failure would
// send the investigation to a policy file that is already correct, which is the
// same misdirection the code split removes.
func TestCredentialRefusalIsLoggedAsACredential(t *testing.T) {
	service, _, _ := hmacService(t, "key-id ops\ntoken ops.s3cret\nallow-all\n")
	var logged bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logged, &slog.HandlerOptions{Level: slog.LevelDebug}))
	frame := signedReadFrame(t, channel.FrameOutputRequest, protocol.OperationOutputRead, "endpoint-1", "ops", "wrong-secret", "digest-1")
	service.outputFrame(context.Background(), frame)
	line := logged.String()
	if !strings.Contains(line, "endpoint rejected the caller credential") {
		t.Fatalf("log line %q must name the credential refusal", line)
	}
	if strings.Contains(line, "access policy refused") {
		t.Fatalf("log line %q must not describe an authentication failure as a policy decision", line)
	}
	if strings.Contains(line, "wrong-secret") {
		t.Fatalf("log line %q must not record the presented secret", line)
	}
}

// TestPolicyRefusalIsStillLoggedAsAPolicy proves the existing wording survives for
// a genuine policy refusal, so the split did not rename the other class.
func TestPolicyRefusalIsStillLoggedAsAPolicy(t *testing.T) {
	service, _, _ := hmacService(t, "key-id ops\ntoken ops.s3cret\npermissions history.read\n")
	var logged bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logged, &slog.HandlerOptions{Level: slog.LevelDebug}))
	frame := signedReadFrame(t, channel.FrameOutputRequest, protocol.OperationOutputRead, "endpoint-1", "ops", "s3cret", "digest-1")
	service.outputFrame(context.Background(), frame)
	line := logged.String()
	if !strings.Contains(line, "endpoint access policy refused operation") {
		t.Fatalf("log line %q must keep the policy wording", line)
	}
	if strings.Contains(line, "rejected the caller credential") {
		t.Fatalf("log line %q must not describe a policy decision as a credential failure", line)
	}
}
