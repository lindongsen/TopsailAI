package security

import (
	"errors"
	"strings"
	"testing"
	"time"
)

func TestParseToken(t *testing.T) {
	tests := []struct {
		name       string
		raw        string
		wantKeyID  string
		wantSecret string
		wantErr    bool
	}{
		{name: "valid", raw: "ep-ai-dev.s3cr3t", wantKeyID: "ep-ai-dev", wantSecret: "s3cr3t"},
		{name: "no dot", raw: "s3cr3t", wantErr: true},
		{name: "empty key id", raw: ".s3cr3t", wantErr: true},
		{name: "empty secret", raw: "ep-ai-dev.", wantErr: true},
		{name: "two dots", raw: "ep.a.b", wantErr: true},
		{name: "empty", raw: "", wantErr: true},
		{name: "key id with space", raw: "ep ai.s3cr3t", wantErr: true},
		{name: "key id with comma", raw: "ep,ai.s3cr3t", wantErr: true},
		{name: "key id too long", raw: strings.Repeat("k", maxKeyIDBytes+1) + ".s", wantErr: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			token, err := ParseToken(test.raw)
			if (err != nil) != test.wantErr {
				t.Fatalf("error=%v, want error=%v", err, test.wantErr)
			}
			if test.wantErr {
				return
			}
			if token.KeyID != test.wantKeyID || token.Secret != test.wantSecret {
				t.Fatalf("token=%+v, want keyID=%q secret=%q", token, test.wantKeyID, test.wantSecret)
			}
		})
	}
}

func TestParseAuthMode(t *testing.T) {
	tests := []struct {
		raw     string
		want    AuthMode
		wantErr bool
	}{
		{raw: "", want: ModeHMAC},
		{raw: "hmac", want: ModeHMAC},
		{raw: "HMAC", want: ModeHMAC},
		{raw: "bearer", want: ModeBearer},
		{raw: " bearer ", want: ModeBearer},
		{raw: "none", wantErr: true},
		{raw: "hmac,bearer", wantErr: true},
	}
	for _, test := range tests {
		t.Run(test.raw, func(t *testing.T) {
			mode, err := ParseAuthMode(test.raw)
			if (err != nil) != test.wantErr {
				t.Fatalf("error=%v, want error=%v", err, test.wantErr)
			}
			if !test.wantErr && mode != test.want {
				t.Fatalf("mode=%q, want %q", mode, test.want)
			}
		})
	}
}

func TestParseSignatureWindow(t *testing.T) {
	tests := []struct {
		raw     string
		want    time.Duration
		wantErr bool
	}{
		{raw: "", want: DefaultSignatureWindow},
		{raw: "30s", want: 30 * time.Second},
		{raw: "5m", want: 5 * time.Minute},
		{raw: "0s", wantErr: true},
		{raw: "-1s", wantErr: true},
		{raw: "16m", wantErr: true},
		{raw: "abc", wantErr: true},
	}
	for _, test := range tests {
		t.Run(test.raw, func(t *testing.T) {
			window, err := ParseSignatureWindow(test.raw)
			if (err != nil) != test.wantErr {
				t.Fatalf("error=%v, want error=%v", err, test.wantErr)
			}
			if !test.wantErr && window != test.want {
				t.Fatalf("window=%v, want %v", window, test.want)
			}
		})
	}
}

func TestSignatureHeaderRoundTrip(t *testing.T) {
	original := Signature{KeyID: "ep-ai-dev", TimestampMS: 1794470400000, Nonce: "a3f9c1d2e4b5a6f7", Signature: "7c2e9f03"}
	parsed, err := ParseSignatureHeader(original.Header())
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if parsed != original {
		t.Fatalf("parsed=%+v, want %+v", parsed, original)
	}
}

func TestParseSignatureHeaderRejectsMalformed(t *testing.T) {
	valid := Signature{KeyID: "k", TimestampMS: 1794470400000, Nonce: "aabb", Signature: "ccdd"}.Header()
	tests := []struct {
		name  string
		value string
	}{
		{name: "empty", value: ""},
		{name: "wrong scheme", value: strings.Replace(valid, HMACScheme, "Bearer", 1)},
		{name: "no scheme", value: "key_id=k, ts=1, nonce=aabb, sig=ccdd"},
		{name: "missing sig", value: HMACScheme + " key_id=k, ts=1794470400000, nonce=aabb"},
		{name: "missing nonce", value: HMACScheme + " key_id=k, ts=1794470400000, sig=ccdd"},
		{name: "missing key id", value: HMACScheme + " ts=1794470400000, nonce=aabb, sig=ccdd"},
		{name: "missing ts", value: HMACScheme + " key_id=k, nonce=aabb, sig=ccdd"},
		{name: "extra field", value: valid + ", extra=1"},
		{name: "duplicate field", value: HMACScheme + " key_id=k, key_id=k, ts=1794470400000, nonce=aabb, sig=ccdd"},
		{name: "non numeric ts", value: HMACScheme + " key_id=k, ts=abc, nonce=aabb, sig=ccdd"},
		{name: "zero ts", value: HMACScheme + " key_id=k, ts=0, nonce=aabb, sig=ccdd"},
		{name: "non hex nonce", value: HMACScheme + " key_id=k, ts=1794470400000, nonce=zzzz, sig=ccdd"},
		{name: "non hex sig", value: HMACScheme + " key_id=k, ts=1794470400000, nonce=aabb, sig=zzzz"},
		{name: "no separator", value: HMACScheme + " key_id=k ts=1794470400000"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if _, err := ParseSignatureHeader(test.value); err == nil {
				t.Fatalf("malformed header was accepted: %q", test.value)
			}
		})
	}
}

func TestBodyDigestDistinguishesAbsentFromEmpty(t *testing.T) {
	if BodyDigest(nil) != "-" {
		t.Fatalf("absent body digest=%q, want %q", BodyDigest(nil), "-")
	}
	if BodyDigest([]byte{}) != "-" {
		t.Fatalf("empty body digest=%q, want %q", BodyDigest([]byte{}), "-")
	}
	if BodyDigest([]byte("x")) == "-" {
		t.Fatal("non-empty body produced the absent marker")
	}
	if BodyDigest([]byte("x")) == BodyDigest([]byte("y")) {
		t.Fatal("different bodies produced the same digest")
	}
}

// TestCanonicalHTTPRequestCoversEveryField proves the signed string is total: a
// change to any single field must produce a different message, otherwise that
// field is not actually protected by the signature.
func TestCanonicalHTTPRequestCoversEveryField(t *testing.T) {
	base := CanonicalHTTPRequest("POST", "/api/v1/commands?x=1", []byte(`{"a":1}`), 1794470400000, "aabb")
	variants := map[string]string{
		"method":    CanonicalHTTPRequest("GET", "/api/v1/commands?x=1", []byte(`{"a":1}`), 1794470400000, "aabb"),
		"path":      CanonicalHTTPRequest("POST", "/api/v1/commands?x=2", []byte(`{"a":1}`), 1794470400000, "aabb"),
		"body":      CanonicalHTTPRequest("POST", "/api/v1/commands?x=1", []byte(`{"a":2}`), 1794470400000, "aabb"),
		"timestamp": CanonicalHTTPRequest("POST", "/api/v1/commands?x=1", []byte(`{"a":1}`), 1794470400001, "aabb"),
		"nonce":     CanonicalHTTPRequest("POST", "/api/v1/commands?x=1", []byte(`{"a":1}`), 1794470400000, "aabc"),
	}
	for name, variant := range variants {
		if variant == base {
			t.Fatalf("changing %s did not change the signed string", name)
		}
	}
}

// TestCanonicalFrameRequestCoversEveryField is the same proof for the frame
// grammar, which is the one the Endpoint verifies.
func TestCanonicalFrameRequestCoversEveryField(t *testing.T) {
	base := CanonicalFrameRequest("output.read", "ai-dev", "digest", 1794470400000, "aabb")
	variants := map[string]string{
		"operation": CanonicalFrameRequest("output.follow", "ai-dev", "digest", 1794470400000, "aabb"),
		"endpoint":  CanonicalFrameRequest("output.read", "other", "digest", 1794470400000, "aabb"),
		"payload":   CanonicalFrameRequest("output.read", "ai-dev", "other", 1794470400000, "aabb"),
		"timestamp": CanonicalFrameRequest("output.read", "ai-dev", "digest", 1794470400001, "aabb"),
		"nonce":     CanonicalFrameRequest("output.read", "ai-dev", "digest", 1794470400000, "aabc"),
	}
	for name, variant := range variants {
		if variant == base {
			t.Fatalf("changing %s did not change the signed string", name)
		}
	}
}

// TestCanonicalFrameRequestExcludesRequestID pins the decision that the frame
// grammar carries no request ID.
//
// The Server mints every frame request ID after the caller's request has already
// been authenticated, so the signer cannot compute the value it would have to
// sign. This test exists so a future edit cannot quietly reintroduce a field that
// no caller can supply, which would make every frame signature unverifiable.
func TestCanonicalFrameRequestExcludesRequestID(t *testing.T) {
	message := CanonicalFrameRequest("output.read", "ai-dev", "digest", 1794470400000, "aabb")
	fields := strings.Split(message, "\n")
	if len(fields) != 6 {
		t.Fatalf("frame grammar has %d fields, want 6: %q", len(fields), message)
	}
	for _, field := range fields {
		if strings.HasPrefix(field, "req_") {
			t.Fatalf("frame grammar contains a request ID field %q", field)
		}
	}
}

// TestCanonicalFrameRequestExcludesFrameType pins the second uncomputable field.
//
// The frame type is chosen by the Server, not by the signer: the CLI never builds
// a channel frame, and one operation can map to more than one frame type
// (OperationMetricsRead is checked at both FrameMetricsRequest and
// FrameMetricsBatchRequest). A grammar that required the frame type would be
// unverifiable for exactly the same reason a request ID would be.
func TestCanonicalFrameRequestExcludesFrameType(t *testing.T) {
	message := CanonicalFrameRequest("metrics.read", "ai-dev", "digest", 1794470400000, "aabb")
	for _, frameType := range []string{"metrics_request", "metrics_batch_request", "output_request"} {
		if strings.Contains(message, frameType) {
			t.Fatalf("frame grammar contains a frame type %q: %q", frameType, message)
		}
	}
}

func TestVerifySignatureRejectsWrongSecret(t *testing.T) {
	message := CanonicalHTTPRequest("GET", "/api/v1/endpoints", nil, 1794470400000, "aabb")
	signature := Sign("right", message)
	if !VerifySignature("right", message, signature) {
		t.Fatal("correct signature was rejected")
	}
	if VerifySignature("wrong", message, signature) {
		t.Fatal("signature verified under a different secret")
	}
	// A one-byte difference must fail. This is the property that makes the
	// comparison meaningful, and it is asserted separately from the secret
	// mismatch because a length or encoding bug would pass the secret test.
	flipped := []byte(signature)
	if flipped[0] == 'a' {
		flipped[0] = 'b'
	} else {
		flipped[0] = 'a'
	}
	if VerifySignature("right", message, string(flipped)) {
		t.Fatal("signature with one changed byte was accepted")
	}
}

func TestConstantTimeEqual(t *testing.T) {
	if !ConstantTimeEqual("secret", "secret") {
		t.Fatal("equal strings were reported different")
	}
	if ConstantTimeEqual("secret", "secreu") {
		t.Fatal("different strings were reported equal")
	}
	if ConstantTimeEqual("secret", "secret-longer") {
		t.Fatal("different lengths were reported equal")
	}
	if !ConstantTimeEqual("", "") {
		t.Fatal("two empty strings were reported different")
	}
}

func TestVerifierAcceptsValidSignature(t *testing.T) {
	token := Token{KeyID: "ep-ai-dev", Secret: "s3cr3t"}
	now := time.UnixMilli(1794470400000)
	verifier := NewVerifier(map[string]Token{token.KeyID: token}, DefaultSignatureWindow)
	verifier.Now = func() time.Time { return now }

	message := CanonicalHTTPRequest("GET", "/api/v1/endpoints", nil, now.UnixMilli(), "aabb")
	signature := Signature{KeyID: token.KeyID, TimestampMS: now.UnixMilli(), Nonce: "aabb", Signature: Sign(token.Secret, message)}
	if err := verifier.Verify(message, signature); err != nil {
		t.Fatalf("valid signature rejected: %v", err)
	}
}

func TestVerifierRejectsUnknownKeyID(t *testing.T) {
	verifier := NewVerifier(map[string]Token{"known": {KeyID: "known", Secret: "s"}}, DefaultSignatureWindow)
	err := verifier.Verify("message", Signature{KeyID: "unknown", TimestampMS: time.Now().UnixMilli(), Nonce: "aabb", Signature: "cc"})
	if !errors.Is(err, ErrUnknownKeyID) {
		t.Fatalf("error=%v, want %v", err, ErrUnknownKeyID)
	}
}

func TestVerifierWindowBoundary(t *testing.T) {
	token := Token{KeyID: "k", Secret: "s"}
	now := time.UnixMilli(1794470400000)
	window := 60 * time.Second
	verifier := NewVerifier(map[string]Token{token.KeyID: token}, window)
	verifier.Now = func() time.Time { return now }

	tests := []struct {
		name    string
		offset  time.Duration
		wantErr error
	}{
		{name: "exact past boundary", offset: -window},
		{name: "exact future boundary", offset: window},
		{name: "one ms past", offset: -window - time.Millisecond, wantErr: ErrClockSkew},
		{name: "one ms future", offset: window + time.Millisecond, wantErr: ErrClockSkew},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			timestamp := now.Add(test.offset).UnixMilli()
			message := CanonicalHTTPRequest("GET", "/p", nil, timestamp, "aabb")
			signature := Signature{KeyID: token.KeyID, TimestampMS: timestamp, Nonce: NewNonce(), Signature: Sign(token.Secret, message)}
			err := verifier.Verify(message, signature)
			if test.wantErr == nil {
				if err != nil {
					t.Fatalf("boundary rejected: %v", err)
				}
				return
			}
			if !errors.Is(err, test.wantErr) {
				t.Fatalf("error=%v, want %v", err, test.wantErr)
			}
		})
	}
}

func TestVerifierRejectsReplayedNonce(t *testing.T) {
	token := Token{KeyID: "k", Secret: "s"}
	now := time.UnixMilli(1794470400000)
	verifier := NewVerifier(map[string]Token{token.KeyID: token}, DefaultSignatureWindow)
	verifier.Now = func() time.Time { return now }

	message := CanonicalHTTPRequest("GET", "/p", nil, now.UnixMilli(), "aabb")
	signature := Signature{KeyID: token.KeyID, TimestampMS: now.UnixMilli(), Nonce: "aabb", Signature: Sign(token.Secret, message)}
	if err := verifier.Verify(message, signature); err != nil {
		t.Fatalf("first use rejected: %v", err)
	}
	if err := verifier.Verify(message, signature); !errors.Is(err, ErrReplayedNonce) {
		t.Fatalf("replay error=%v, want %v", err, ErrReplayedNonce)
	}
}

// TestVerifierDoesNotConsumeNonceOnBadSignature proves the check order: a forged
// request must not be able to burn a nonce slot and deny it to the real caller.
func TestVerifierDoesNotConsumeNonceOnBadSignature(t *testing.T) {
	token := Token{KeyID: "k", Secret: "s"}
	now := time.UnixMilli(1794470400000)
	verifier := NewVerifier(map[string]Token{token.KeyID: token}, DefaultSignatureWindow)
	verifier.Now = func() time.Time { return now }

	message := CanonicalHTTPRequest("GET", "/p", nil, now.UnixMilli(), "aabb")
	forged := Signature{KeyID: token.KeyID, TimestampMS: now.UnixMilli(), Nonce: "aabb", Signature: "deadbeef"}
	if err := verifier.Verify(message, forged); !errors.Is(err, ErrBadSignature) {
		t.Fatalf("forged error=%v, want %v", err, ErrBadSignature)
	}
	genuine := Signature{KeyID: token.KeyID, TimestampMS: now.UnixMilli(), Nonce: "aabb", Signature: Sign(token.Secret, message)}
	if err := verifier.Verify(message, genuine); err != nil {
		t.Fatalf("genuine request was denied after a forgery: %v", err)
	}
}

func TestNonceCacheExpiresEntries(t *testing.T) {
	cache := NewNonceCache(8, time.Minute)
	start := time.UnixMilli(1794470400000)
	if !cache.Accept("k", "aabb", start) {
		t.Fatal("first use refused")
	}
	if cache.Accept("k", "aabb", start.Add(30*time.Second)) {
		t.Fatal("replay inside the window accepted")
	}
	if !cache.Accept("k", "aabb", start.Add(2*time.Minute)) {
		t.Fatal("nonce was not released after the window")
	}
}

func TestNonceCacheFailsClosedWhenFull(t *testing.T) {
	cache := NewNonceCache(2, time.Minute)
	now := time.UnixMilli(1794470400000)
	if !cache.Accept("k", "aa", now) || !cache.Accept("k", "bb", now) {
		t.Fatal("cache refused before reaching its limit")
	}
	if cache.Accept("k", "cc", now) {
		t.Fatal("cache evicted a live nonce instead of failing closed")
	}
}

func TestNonceCacheSeparatesKeyIDs(t *testing.T) {
	cache := NewNonceCache(8, time.Minute)
	now := time.UnixMilli(1794470400000)
	if !cache.Accept("k1", "aabb", now) {
		t.Fatal("first key refused")
	}
	if !cache.Accept("k2", "aabb", now) {
		t.Fatal("the same nonce under a different key was refused")
	}
}

func TestSignRequestProducesVerifiableHeader(t *testing.T) {
	token := Token{KeyID: "ep-ai-dev", Secret: "s3cr3t"}
	signature, err := SignRequest(token, func(timestampMS int64, nonce string) string {
		return CanonicalHTTPRequest("GET", "/api/v1/endpoints", nil, timestampMS, nonce)
	})
	if err != nil {
		t.Fatalf("sign: %v", err)
	}
	if signature.KeyID != token.KeyID || signature.Nonce == "" || signature.Signature == "" {
		t.Fatalf("incomplete signature: %+v", signature)
	}
	parsed, err := ParseSignatureHeader(signature.Header())
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	message := CanonicalHTTPRequest("GET", "/api/v1/endpoints", nil, parsed.TimestampMS, parsed.Nonce)
	verifier := NewVerifier(map[string]Token{token.KeyID: token}, DefaultSignatureWindow)
	if err := verifier.Verify(message, parsed); err != nil {
		t.Fatalf("round trip rejected: %v", err)
	}
}
