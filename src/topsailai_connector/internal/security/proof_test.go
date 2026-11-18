package security

import (
	"strings"
	"testing"
	"time"
)

// testSecret returns a secret long enough to be a valid HMAC key.
func testSecret(t *testing.T) Secret {
	t.Helper()
	credential, err := NewCredential()
	if err != nil {
		t.Fatalf("NewCredential() = %v", err)
	}
	return credential.Secret
}

// TestFormatProofRoundTrips checks that the header grammar the CLI writes is the grammar
// the verifier reads.
func TestFormatProofRoundTrips(t *testing.T) {
	nonce, err := NewNonce()
	if err != nil {
		t.Fatalf("NewNonce() = %v", err)
	}
	proof := Proof{
		Scheme:      SchemeClient,
		Version:     ProofVersion,
		KeyID:       "operator-dawson",
		TimestampMS: 1794470400000,
		Nonce:       nonce,
		Signature:   strings.Repeat("a", SignatureHexLength),
	}

	parsed, err := ParseProof(FormatProof(proof), SchemeClient)
	if err != nil {
		t.Fatalf("ParseProof(FormatProof(proof)) = %v", err)
	}
	if parsed != proof {
		t.Errorf("parsed proof = %+v, want %+v", parsed, proof)
	}
}

// TestParseProofRefusesMalformed checks the grammar refusals.
//
// Every case is a value a permissive parser would have accepted, which is why the
// grammar is fixed: two spellings of one proof is one spelling too many for a value that
// is compared byte for byte.
func TestParseProofRefusesMalformed(t *testing.T) {
	nonce := strings.Repeat("a", NonceHexLength)
	signature := strings.Repeat("b", SignatureHexLength)
	valid := SchemeClient + " version=1,key_id=operator,timestamp_ms=1,nonce=" + nonce + ",signature=" + signature

	cases := map[string]string{
		"empty":              "",
		"wrong scheme":       strings.Replace(valid, SchemeClient, SchemeNode, 1),
		"no space":           SchemeClient + "version=1",
		"missing field":      SchemeClient + " version=1,key_id=operator,timestamp_ms=1,nonce=" + nonce,
		"extra field":        valid + ",extra=1",
		"wrong version":      strings.Replace(valid, "version=1", "version=2", 1),
		"leading zero":       strings.Replace(valid, "timestamp_ms=1", "timestamp_ms=01", 1),
		"negative timestamp": strings.Replace(valid, "timestamp_ms=1", "timestamp_ms=-1", 1),
		"uppercase nonce":    strings.Replace(valid, nonce, strings.ToUpper(nonce), 1),
		"short nonce":        strings.Replace(valid, nonce, "abc", 1),
		"short signature":    strings.Replace(valid, signature, "abc", 1),
		"leading space":      " " + valid,
		"trailing space":     valid + " ",
		"uppercase key id":   strings.Replace(valid, "key_id=operator", "key_id=Operator", 1),
	}
	for name, value := range cases {
		if _, err := ParseProof(value, SchemeClient); err == nil {
			t.Errorf("%s: ParseProof(%q) = nil error, want a refusal", name, value)
		}
	}
}

// TestProofValidateMatchesParseProof checks that a proof arriving as structured data is
// held to the same rules as one arriving as a header.
//
// The Node receives a proof the Server already parsed, so it cannot re-parse the original
// header. If Validate were looser than ParseProof, a Server could hand the Node a value
// the Node would never have accepted from a caller.
func TestProofValidateMatchesParseProof(t *testing.T) {
	nonce := strings.Repeat("a", NonceHexLength)
	signature := strings.Repeat("b", SignatureHexLength)
	valid := Proof{
		Scheme:      SchemeNode,
		Version:     ProofVersion,
		KeyID:       "operator",
		TimestampMS: 1,
		Nonce:       nonce,
		Signature:   signature,
	}
	if err := valid.Validate(SchemeNode); err != nil {
		t.Fatalf("Validate(valid proof) = %v", err)
	}

	broken := []Proof{
		{Scheme: SchemeClient, Version: ProofVersion, KeyID: "operator", TimestampMS: 1, Nonce: nonce, Signature: signature},
		{Scheme: SchemeNode, Version: 2, KeyID: "operator", TimestampMS: 1, Nonce: nonce, Signature: signature},
		{Scheme: SchemeNode, Version: ProofVersion, KeyID: "", TimestampMS: 1, Nonce: nonce, Signature: signature},
		{Scheme: SchemeNode, Version: ProofVersion, KeyID: "operator", TimestampMS: -1, Nonce: nonce, Signature: signature},
		{Scheme: SchemeNode, Version: ProofVersion, KeyID: "operator", TimestampMS: 1, Nonce: "short", Signature: signature},
		{Scheme: SchemeNode, Version: ProofVersion, KeyID: "operator", TimestampMS: 1, Nonce: nonce, Signature: "short"},
	}
	for index, proof := range broken {
		if err := proof.Validate(SchemeNode); err == nil {
			t.Errorf("case %d: Validate(%+v) = nil error, want a refusal", index, proof)
		}
	}
}

// TestSignAndVerify checks that a signature verifies with the right secret and fails with
// a different one.
func TestSignAndVerify(t *testing.T) {
	secret := testSecret(t)
	other := testSecret(t)
	canonical := CanonicalNodeOperation("node_abc", "operator", "file.read", "project", "a.txt", 0, 10, "req_1", 1794470400000, strings.Repeat("a", NonceHexLength))

	signature := Sign(secret, canonical)
	if err := VerifySignature(secret, canonical, signature); err != nil {
		t.Fatalf("VerifySignature(right secret) = %v", err)
	}
	if err := VerifySignature(other, canonical, signature); err == nil {
		t.Errorf("VerifySignature(wrong secret) = nil error, want a mismatch")
	}
}

// TestVerifySignatureRefusesChangedCanonical checks that changing any signed field
// invalidates the signature.
//
// This is the property the whole design rests on: a caller that keeps a valid proof and
// changes what it asks for must be refused.
func TestVerifySignatureRefusesChangedCanonical(t *testing.T) {
	secret := testSecret(t)
	nonce := strings.Repeat("a", NonceHexLength)
	original := CanonicalNodeOperation("node_abc", "operator", "file.read", "project", "a.txt", 0, 10, "req_1", 1794470400000, nonce)
	signature := Sign(secret, original)

	changed := []string{
		CanonicalNodeOperation("node_other", "operator", "file.read", "project", "a.txt", 0, 10, "req_1", 1794470400000, nonce),
		CanonicalNodeOperation("node_abc", "other", "file.read", "project", "a.txt", 0, 10, "req_1", 1794470400000, nonce),
		CanonicalNodeOperation("node_abc", "operator", "file.stat", "project", "a.txt", 0, 10, "req_1", 1794470400000, nonce),
		CanonicalNodeOperation("node_abc", "operator", "file.read", "tool", "a.txt", 0, 10, "req_1", 1794470400000, nonce),
		CanonicalNodeOperation("node_abc", "operator", "file.read", "project", "b.txt", 0, 10, "req_1", 1794470400000, nonce),
		CanonicalNodeOperation("node_abc", "operator", "file.read", "project", "a.txt", 1, 10, "req_1", 1794470400000, nonce),
		CanonicalNodeOperation("node_abc", "operator", "file.read", "project", "a.txt", 0, 11, "req_1", 1794470400000, nonce),
		CanonicalNodeOperation("node_abc", "operator", "file.read", "project", "a.txt", 0, 10, "req_2", 1794470400000, nonce),
		CanonicalNodeOperation("node_abc", "operator", "file.read", "project", "a.txt", 0, 10, "req_1", 1794470400001, nonce),
		CanonicalNodeOperation("node_abc", "operator", "file.read", "project", "a.txt", 0, 10, "req_1", 1794470400000, strings.Repeat("b", NonceHexLength)),
	}
	for index, canonical := range changed {
		if err := VerifySignature(secret, canonical, signature); err == nil {
			t.Errorf("case %d: VerifySignature(changed canonical) = nil error, want a mismatch", index)
		}
	}
}

// TestCanonicalInputsAreDomainSeparated checks that a proof built for one boundary cannot
// be replayed into the other.
func TestCanonicalInputsAreDomainSeparated(t *testing.T) {
	client := CanonicalClientRequest("POST", "/v1/nodes/node_abc/operations", "-", "-", "req_1", 1, "nonce")
	node := CanonicalNodeOperation("node_abc", "operator", "file.read", "project", "a.txt", 0, 0, "req_1", 1, "nonce")
	if strings.HasPrefix(node, SchemeClient) {
		t.Errorf("node canonical input starts with the client scheme")
	}
	if strings.HasPrefix(client, SchemeNode) {
		t.Errorf("client canonical input starts with the node scheme")
	}
}

// TestBodyDigestDistinguishesAbsentFromEmpty checks that "no body" and "a present
// zero-byte body" are different signed values.
//
// Collapsing them would let one proof be replayed against the other.
func TestBodyDigestDistinguishesAbsentFromEmpty(t *testing.T) {
	if BodyDigest(nil, false) == BodyDigest(nil, true) {
		t.Errorf("absent body and empty body share a digest")
	}
	if BodyDigest([]byte("a"), true) == BodyDigest([]byte("b"), true) {
		t.Errorf("two different bodies share a digest")
	}
}

// TestTimestampWithinWindow checks the window boundary in both directions.
func TestTimestampWithinWindow(t *testing.T) {
	const window = int64(60000)
	const now = int64(1794470400000)

	cases := []struct {
		name    string
		proofMS int64
		want    bool
	}{
		{"exact now", now, true},
		{"inside past", now - 30000, true},
		{"inside future", now + 30000, true},
		{"exact edge past", now - window, true},
		{"exact edge future", now + window, true},
		{"outside past", now - window - 1, false},
		{"outside future", now + window + 1, false},
	}
	for _, testCase := range cases {
		if got := TimestampWithinWindow(now, testCase.proofMS, window); got != testCase.want {
			t.Errorf("%s: TimestampWithinWindow = %t, want %t", testCase.name, got, testCase.want)
		}
	}
}

// TestTimestampWithinWindowRefusesNonPositiveWindow checks that a zero window is a
// configuration failure rather than "accept everything".
func TestTimestampWithinWindowRefusesNonPositiveWindow(t *testing.T) {
	if TimestampWithinWindow(1000, 1000, 0) {
		t.Errorf("TimestampWithinWindow with a zero window = true, want false")
	}
	if TimestampWithinWindow(1000, 1000, -1) {
		t.Errorf("TimestampWithinWindow with a negative window = true, want false")
	}
}

// TestNewNonceIsUniqueAndWellFormed checks the nonce shape and that two nonces differ.
func TestNewNonceIsUniqueAndWellFormed(t *testing.T) {
	first, err := NewNonce()
	if err != nil {
		t.Fatalf("NewNonce() = %v", err)
	}
	second, err := NewNonce()
	if err != nil {
		t.Fatalf("NewNonce() = %v", err)
	}
	if len(first) != NonceHexLength {
		t.Errorf("nonce length = %d, want %d", len(first), NonceHexLength)
	}
	if first == second {
		t.Errorf("two generated nonces are identical")
	}
	if err := validateLowerHex(first, NonceHexLength, "nonce"); err != nil {
		t.Errorf("generated nonce is not lowercase hex: %v", err)
	}
}

// TestReplayCacheAdmitsOnce checks that a nonce is admitted once and refused afterwards.
func TestReplayCacheAdmitsOnce(t *testing.T) {
	cache, err := NewReplayCache(time.Minute, 16)
	if err != nil {
		t.Fatalf("NewReplayCache() = %v", err)
	}

	if err := cache.Admit("operator", "nonce-a"); err != nil {
		t.Fatalf("first Admit() = %v", err)
	}
	if err := cache.Admit("operator", "nonce-a"); err != ErrReplayDetected {
		t.Errorf("second Admit() = %v, want ErrReplayDetected", err)
	}
}

// TestReplayCacheSeparatesKeyIDs checks that two credentials using the same nonce do not
// collide, because the nonce is scoped to the credential that signed it.
func TestReplayCacheSeparatesKeyIDs(t *testing.T) {
	cache, err := NewReplayCache(time.Minute, 16)
	if err != nil {
		t.Fatalf("NewReplayCache() = %v", err)
	}

	if err := cache.Admit("first", "shared-nonce"); err != nil {
		t.Fatalf("Admit(first) = %v", err)
	}
	if err := cache.Admit("second", "shared-nonce"); err != nil {
		t.Errorf("Admit(second) = %v, want nil", err)
	}
}

// TestReplayCacheExpires checks that a nonce stops being recorded once the window passes.
func TestReplayCacheExpires(t *testing.T) {
	cache, err := NewReplayCache(time.Second, 16)
	if err != nil {
		t.Fatalf("NewReplayCache() = %v", err)
	}

	now := time.Now()
	cache.now = func() time.Time { return now }
	if err := cache.Admit("operator", "nonce-a"); err != nil {
		t.Fatalf("Admit() = %v", err)
	}

	cache.now = func() time.Time { return now.Add(2 * time.Second) }
	if err := cache.Admit("operator", "nonce-a"); err != nil {
		t.Errorf("Admit() after the window = %v, want nil", err)
	}
}

// TestReplayCacheFailsClosedWhenFull checks that a full cache refuses rather than evicting
// a live nonce.
//
// Evicting a live nonce would reopen replay for the proof it belonged to, so a full cache
// must refuse instead of silently weakening the check it exists to provide.
func TestReplayCacheFailsClosedWhenFull(t *testing.T) {
	cache, err := NewReplayCache(time.Minute, 2)
	if err != nil {
		t.Fatalf("NewReplayCache() = %v", err)
	}

	if err := cache.Admit("operator", "nonce-a"); err != nil {
		t.Fatalf("Admit(a) = %v", err)
	}
	if err := cache.Admit("operator", "nonce-b"); err != nil {
		t.Fatalf("Admit(b) = %v", err)
	}
	if err := cache.Admit("operator", "nonce-c"); err != ErrReplayCacheFull {
		t.Errorf("Admit(c) = %v, want ErrReplayCacheFull", err)
	}
}

// TestNewReplayCacheRefusesUnusableConfiguration checks that a window or capacity the
// operator cannot state is refused rather than defaulted.
func TestNewReplayCacheRefusesUnusableConfiguration(t *testing.T) {
	if _, err := NewReplayCache(0, 16); err == nil {
		t.Errorf("NewReplayCache(zero window) = nil error, want a refusal")
	}
	if _, err := NewReplayCache(-time.Second, 16); err == nil {
		t.Errorf("NewReplayCache(negative window) = nil error, want a refusal")
	}
	if _, err := NewReplayCache(MaxReplayWindow+time.Second, 16); err == nil {
		t.Errorf("NewReplayCache(window over the maximum) = nil error, want a refusal")
	}
	if _, err := NewReplayCache(time.Minute, 0); err == nil {
		t.Errorf("NewReplayCache(zero capacity) = nil error, want a refusal")
	}
}

// TestReplayCacheConcurrentAdmitAdmitsOnce checks that two concurrent copies of one proof
// cannot both be admitted.
//
// The check-and-insert is one operation under one lock, which is the property a
// concurrent attacker would otherwise exploit.
func TestReplayCacheConcurrentAdmitAdmitsOnce(t *testing.T) {
	cache, err := NewReplayCache(time.Minute, 16)
	if err != nil {
		t.Fatalf("NewReplayCache() = %v", err)
	}

	const attempts = 32
	results := make(chan error, attempts)
	start := make(chan struct{})
	for index := 0; index < attempts; index++ {
		go func() {
			<-start
			results <- cache.Admit("operator", "shared-nonce")
		}()
	}
	close(start)

	admitted := 0
	for index := 0; index < attempts; index++ {
		if err := <-results; err == nil {
			admitted++
		}
	}
	if admitted != 1 {
		t.Errorf("admitted %d copies of one nonce, want exactly 1", admitted)
	}
}
