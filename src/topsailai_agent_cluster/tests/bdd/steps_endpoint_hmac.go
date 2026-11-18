package bdd

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	"topsailai_agent_cluster/tests/harness"
)

// The HMAC scenarios drive the real HTTP boundary directly instead of the CLI.
//
// The CLI applies one authentication mode to both credentials, so a CLI-driven
// HMAC scenario would also force the Server into HMAC mode. That would prove the
// two hops share a mode, which is the opposite of the property this suite must
// establish: the Server authenticates the operator with its own credential and
// forwards an Endpoint proof it cannot verify and must never be able to mint.
//
// Signing the proof here keeps the two trust boundaries independent. The Server
// receives only the public key ID, timestamp, nonce, signature and request digest,
// so a passing scenario is also evidence that the Server never needs the Endpoint
// secret.
const (
	hmacKeyID     = "ops"
	hmacSecret    = "s3cret"
	hmacPairToken = hmacKeyID + "." + hmacSecret
	hmacWrongPair = hmacKeyID + ".wrong-secret"
)

var (
	hmacPolicyDir     string
	hmacEndpointLog   string
	hmacLastStatus    int
	hmacLastBody      []byte
	hmacLastProof     security.EndpointCredential
	hmacLastResource  string
	hmacLastRequestID string
)

// registerEndpointHMACSteps registers the signed-credential scenarios.
func registerEndpointHMACSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster whose Endpoint requires a signed credential$`, startHMACProbeCluster)
	ctx.Step(`^a real cluster whose Endpoint requires a signed credential but grants no output read$`, startHMACProbeClusterWithoutGrant)
	ctx.Step(`^the caller presents a valid Endpoint signature$`, useHMACValidProof)
	ctx.Step(`^the caller presents an Endpoint signature with the wrong secret$`, useHMACWrongSecret)
	ctx.Step(`^the caller presents no Endpoint signature$`, useHMACUnsigned)
	ctx.Step(`^the caller replays the previous Endpoint signature$`, useHMACReplay)
	ctx.Step(`^the caller reads session output with the signed credential$`, runHMACProbe)
	ctx.Step(`^the signed read reaches the provider$`, assertHMACReachedProvider)
	ctx.Step(`^the signed read is refused for its credential$`, assertHMACCredentialRefused)
	ctx.Step(`^the signed read is refused by policy$`, assertHMACPolicyRefused)
	ctx.Step(`^the Server never received the Endpoint secret$`, assertServerNeverSawEndpointSecret)
}

// startHMACProbeCluster starts a cluster whose Endpoint requires a signature while
// the Server keeps its own bearer credential. The two modes are deliberately
// different: they are independent trust boundaries, and a scenario that forced one
// shared mode could not prove that.
func startHMACProbeCluster() error {
	return startHMACCluster("permissions output.read")
}

// startHMACProbeClusterWithoutGrant starts the same cluster with a policy that
// verifies the credential but grants nothing, so a scenario can prove that a
// verified caller without a grant is refused by policy rather than by signature.
func startHMACProbeClusterWithoutGrant() error {
	return startHMACCluster("permissions command.exec")
}

func startHMACCluster(rule string) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	// The HMAC state is package-level, so it must be cleared per scenario. A
	// scenario that never sets a proof would otherwise inherit the previous
	// scenario's proof and could pass for the wrong reason.
	hmacLastProof = security.EndpointCredential{}
	hmacLastStatus = 0
	hmacLastBody = nil
	hmacLastResource = ""
	hmacLastRequestID = ""
	dir, err := newHMACPolicyDirectory(rule)
	if err != nil {
		return err
	}
	hmacPolicyDir = dir
	hmacEndpointLog = activeTest.TempDir() + "/endpoint-hmac.log"
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		EndpointEnvironment: map[string]string{
			"AGENT_CLUSTER_LOG_OUTPUT":                 "file",
			"AGENT_CLUSTER_LOG_PATH":                   hmacEndpointLog,
			"AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR": dir,
			"AGENT_CLUSTER_ENDPOINT_AUTH_MODE":         "hmac",
		},
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	activeScenario.realCluster = cluster
	return nil
}

// newHMACPolicyDirectory writes one policy file that declares the key ID and the
// full pair credential. HMAC verification needs the secret itself, because a
// SHA-256 digest cannot verify an HMAC; the digest form stays bearer-only.
func newHMACPolicyDirectory(rule string) (string, error) {
	dir := activeTest.TempDir() + "/endpoint-hmac-policy"
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", fmt.Errorf("create HMAC policy directory: %w", err)
	}
	content := "key-id " + hmacKeyID + "\ntoken " + hmacPairToken + "\n" + rule + "\n"
	if err := os.WriteFile(dir+"/hmac.conf", []byte(content), 0o600); err != nil {
		return "", fmt.Errorf("write HMAC policy rule: %w", err)
	}
	return dir, nil
}

func useHMACValidProof() error {
	return signHMACProof(hmacPairToken)
}

func useHMACWrongSecret() error {
	return signHMACProof(hmacWrongPair)
}

// useHMACUnsigned sends no signature at all. The target is still resolved, because
// the request must address a real resource: an unsigned request that also named a
// missing resource would be refused for the target rather than for the credential,
// and the scenario would prove nothing about the credential.
func useHMACUnsigned() error {
	hmacLastProof = security.EndpointCredential{}
	resourceID, err := tuiResourceID()
	if err != nil {
		return fmt.Errorf("resolve unsigned read target: %w", err)
	}
	hmacLastResource = resourceID
	return nil
}

// useHMACReplay re-sends the exact proof that was already accepted, so the nonce
// cache must reject it. A replay scenario that only checked that a proof existed
// would pass even with replay protection removed, which is not coverage.
func useHMACReplay() error {
	if hmacLastProof.Nonce == "" {
		return fmt.Errorf("no previous signature to replay")
	}
	return runHMACProbe()
}

// signHMACProof builds one Endpoint proof for the output read request.
//
// The resource ID is resolved from the real inventory before signing, because the
// digest covers the request URI and the URI carries the resource ID. Signing a
// constant and then requesting a different ID would fail verification for a reason
// that has nothing to do with the credential under test.
func signHMACProof(pair string) error {
	parsed, err := security.ParseToken(pair)
	if err != nil {
		return fmt.Errorf("parse Endpoint credential: %w", err)
	}
	resourceID, err := tuiResourceID()
	if err != nil {
		return fmt.Errorf("resolve signed read target: %w", err)
	}
	hmacLastResource = resourceID
	nonce := security.NewNonce()
	if nonce == "" {
		return fmt.Errorf("no nonce available")
	}
	timestampMS := time.Now().UnixMilli()
	digest := security.EndpointRequestDigest(http.MethodGet, hmacRequestURI(resourceID), nil)
	hmacLastProof = security.EndpointCredential{
		KeyID:       parsed.KeyID,
		TimestampMS: timestampMS,
		Nonce:       nonce,
		Signature:   security.Sign(parsed.Secret, security.CanonicalFrameRequest(protocol.OperationOutputRead, scopedEndpointID, digest, timestampMS, nonce)),
	}
	return nil
}

// hmacRequestURI is the exact request target the Server receives, so the digest
// covers the same bytes on both sides.
func hmacRequestURI(resourceID string) string {
	return "/api/v1/output?endpoint_id=" + scopedEndpointID +
		"&resource_id=" + resourceID +
		"&provider_generation=&max_bytes=0&max_lines=0"
}

// runHMACProbe sends one authenticated request: the Server credential stays a
// bearer token, and the Endpoint credential travels as a signature.
func runHMACProbe() error {
	cluster := activeScenario.realCluster
	if cluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	if hmacLastResource == "" {
		return fmt.Errorf("no signed read target was resolved")
	}
	before, err := cluster.ProviderInvocationsE()
	if err != nil {
		return err
	}
	policyProbeBefore = countPolicyProbeInvocations(before)

	req, err := http.NewRequest(http.MethodGet, cluster.URL(hmacRequestURI(hmacLastResource)), nil)
	if err != nil {
		return fmt.Errorf("create signed request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer secret")
	if hmacLastProof.Nonce != "" {
		req.Header.Set(security.EndpointAuthHeader, hmacLastProof.Header())
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return fmt.Errorf("send signed request: %w", err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("read signed response: %w", err)
	}
	hmacLastStatus = resp.StatusCode
	hmacLastBody = body
	hmacLastRequestID = resp.Header.Get("X-Request-ID")
	activeScenario.lastBody = body
	activeScenario.lastStatus = resp.StatusCode
	return nil
}

func assertHMACReachedProvider() error {
	if hmacLastStatus != http.StatusOK {
		return fmt.Errorf("signed read failed: status=%d body=%s", hmacLastStatus, hmacLastBody)
	}
	if !strings.Contains(string(hmacLastBody), "provider output marker") {
		return fmt.Errorf("signed read returned no provider output: %s", hmacLastBody)
	}
	count, err := policyProbeInvocationCount()
	if err != nil {
		return err
	}
	if count != policyProbeBefore+1 {
		return fmt.Errorf("provider output invocation count=%d, want %d", count, policyProbeBefore+1)
	}
	return nil
}

func assertHMACCredentialRefused() error {
	if code := hmacRefusalCode(hmacLastBody); code != protocol.CredentialRejected {
		return fmt.Errorf("refusal code=%q, want %q: status=%d body=%s", code, protocol.CredentialRejected, hmacLastStatus, hmacLastBody)
	}
	if strings.Contains(string(hmacLastBody), protocol.PolicyDenied) {
		return fmt.Errorf("credential refusal was mislabeled as %q: status=%d body=%s", protocol.PolicyDenied, hmacLastStatus, hmacLastBody)
	}
	if hmacLastStatus != http.StatusUnauthorized {
		return fmt.Errorf("credential refusal status=%d, want %d", hmacLastStatus, http.StatusUnauthorized)
	}
	count, err := policyProbeInvocationCount()
	if err != nil {
		return err
	}
	if count != policyProbeBefore {
		return fmt.Errorf("credential-refused read reached provider: before=%d after=%d", policyProbeBefore, count)
	}
	return nil
}

func assertHMACPolicyRefused() error {
	if code := hmacRefusalCode(hmacLastBody); code != protocol.PolicyDenied {
		return fmt.Errorf("refusal code=%q, want %q: status=%d body=%s", code, protocol.PolicyDenied, hmacLastStatus, hmacLastBody)
	}
	if strings.Contains(string(hmacLastBody), protocol.CredentialRejected) {
		return fmt.Errorf("policy refusal was mislabeled as %q: status=%d body=%s", protocol.CredentialRejected, hmacLastStatus, hmacLastBody)
	}
	if hmacLastStatus != http.StatusForbidden {
		return fmt.Errorf("policy refusal status=%d, want %d", hmacLastStatus, http.StatusForbidden)
	}
	count, err := policyProbeInvocationCount()
	if err != nil {
		return err
	}
	if count != policyProbeBefore {
		return fmt.Errorf("policy-refused read reached provider: before=%d after=%d", policyProbeBefore, count)
	}
	return nil
}

// assertServerNeverSawEndpointSecret proves the trust boundary from the Server's
// own evidence. The Server database and its response must contain no part of the
// Endpoint pair credential, because a Server that could read the secret could mint
// a valid proof for any Endpoint.
func assertServerNeverSawEndpointSecret() error {
	cluster := activeScenario.realCluster
	if cluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	if bytes.Contains(hmacLastBody, []byte(hmacSecret)) {
		return fmt.Errorf("Server response contains the Endpoint secret: %s", hmacLastBody)
	}
	if bytes.Contains(hmacLastBody, []byte(hmacPairToken)) {
		return fmt.Errorf("Server response contains the Endpoint pair credential: %s", hmacLastBody)
	}
	data, err := os.ReadFile(cluster.ServerDB)
	if err != nil {
		return fmt.Errorf("read Server database: %w", err)
	}
	if bytes.Contains(data, []byte(hmacSecret)) {
		return fmt.Errorf("Server database contains the Endpoint secret")
	}
	if bytes.Contains(data, []byte(hmacPairToken)) {
		return fmt.Errorf("Server database contains the Endpoint pair credential")
	}
	return nil
}

// hmacRefusalCode decodes the envelope code so a scenario asserts the refusal
// class itself rather than a substring of the message. A success envelope carries
// a numeric code, so an empty result means "not a refusal".
func hmacRefusalCode(body []byte) string {
	var envelope struct {
		Code any `json:"code"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		return ""
	}
	code, _ := envelope.Code.(string)
	return code
}
