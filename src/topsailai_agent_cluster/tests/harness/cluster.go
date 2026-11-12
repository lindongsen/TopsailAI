package harness

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"testing"
	"time"
)

// endpointTokenHeader is the header that carries the Endpoint token.
//
// It is declared here rather than imported from the Server or the client because
// both of those packages are production code and the harness must not depend on
// an unexported constant. The value is the wire contract, so it is stated once
// and the two production declarations must agree with it.
const endpointTokenHeader = "X-Endpoint-Token"

// ClusterOptions controls the real Server, Endpoint, and fixture process wiring.
type ClusterOptions struct {
	// Environment is applied to the Server process only. The Endpoint is a
	// separate process with its own configuration, so a value that must reach
	// the Endpoint belongs in EndpointEnvironment instead; setting it here would
	// be silently ignored and a scenario would assert against the default while
	// appearing to prove the configured value.
	Environment map[string]string
	// EndpointEnvironment is applied to the Endpoint process, which is where
	// Endpoint-local configuration such as the access policy directory lives.
	EndpointEnvironment map[string]string
	// CLIEnvironment is applied to every CLI process the harness starts, so a
	// scenario can configure the client side of a contract. The Endpoint token
	// map belongs here: it is the CLI's own configuration, and the Server must
	// never hold it.
	CLIEnvironment map[string]string
	DelayMS        int
	Faults         FaultInjection
	// ChannelDirection selects which side dials. An empty value keeps the
	// default endpoint-initiated direction, so existing scenarios are unchanged.
	ChannelDirection string
	// SharedCertificate makes the Endpoint present the Server certificate, so the
	// certificate no longer proves which Endpoint is connecting.
	SharedCertificate bool
	// ProviderType selects the adapter implementation. An empty value keeps the
	// generic "fixture" adapter, so existing scenarios are unchanged. Selecting
	// "topsailai" wires the real TopsailAI adapter, which is the only adapter that
	// implements streaming output follow; the generic fixture adapter answers a
	// follow with "unsupported" because it cannot stream.
	ProviderType string
}

// FaultInjection contains test-only process-composition controls shared by integration and BDD tests.
// These values are translated to AGENT_CLUSTER_TEST_* variables only when starting test processes.
type FaultInjection struct {
	DelayMS                     int
	DropAck                     bool
	DispatchDelayMS             int
	ReceiptDelayMS              int
	CrashAfterInvocationStarted bool
	CrashBeforeInvocation       bool
	ProviderFailAfterN          int
	ProviderAlwaysFail          bool
	CollectionDelayMS           int
	ProviderFailAdapterID       string
	TwoAdapters                 bool
	NoSessions                  bool
	OutputUnsupported           bool
	OutputSize                  int
	ProviderInvocationLog       string
	HoldPhase                   string
	HoldDir                     string
	UnsupportedCapability       string
	// AdvertisedCapabilities replaces the generic fixture adapter's default
	// capability list. The default list is a production value asserted by
	// internal/adapter/command_test.go, so a scenario that needs an operation the
	// default omits, such as context.inject, declares the list here instead of
	// changing what every deployment advertises.
	AdvertisedCapabilities []string
	// MessagesBody and MessagesCount configure the fixture's conversation
	// content. They are emitted by appendFaultEnvironment, which is the only
	// seam that reaches the Endpoint and therefore the fixture child: the
	// Endpoint does not receive ClusterOptions.Environment, so a body set there
	// would be silently ignored and a scenario would assert against the default
	// body while appearing to prove the configured one.
	MessagesBody  string
	MessagesCount int
	// CapabilityRevision overrides the descriptor revision the fixture adapter
	// advertises. An empty value keeps the harness default, so existing
	// scenarios are unchanged. A scenario that submits agent.start must use the
	// same value as its profile revision, because the Endpoint compares them
	// before the policy hook runs.
	CapabilityRevision string
	// CapabilityVersions overrides the advertised version of named capabilities.
	// The default is "v1", which is correct for every operation whose payload
	// schema version is also "v1". command.exec and agent.model.select carry a
	// payload schema version of "1", so a scenario that drives one declares it
	// here instead of changing what every deployment advertises.
	CapabilityVersions map[string]string
	// FixtureMode selects the fixture discovery document. An empty value keeps
	// "one", so existing scenarios are unchanged. "mixed" publishes one live and
	// one stopped session, which is what a resume scenario needs: resume
	// authorizes on the absence of a live target, so a live-only inventory
	// rejects the command with target_still_active before the policy hook runs.
	FixtureMode string
	// CommandAllowlist makes the Endpoint accept the given argv prefixes for
	// command.exec. An empty value leaves the allowlist unconfigured, so
	// command.exec fails closed with a configuration error rather than reaching
	// the policy hook's positive path.
	CommandAllowlist [][]string
	// ControlActions makes the Endpoint advertise the given ctl. actions. An
	// empty value leaves the catalog unconfigured, so no ctl. action is
	// advertised and every ctl. operation is refused as unsupported before the
	// policy hook runs.
	ControlActions []ControlAction
}

// ControlAction describes one ctl. action the harness writes into the
// Endpoint-local catalog.
//
// The catalog is the only source of ctl. actions, so a scenario that proves the
// positive authorization path needs a real entry: advertising an action the
// catalog does not define would end as unsupported, which proves nothing about
// authorization.
type ControlAction struct {
	// Name is the action name after the ctl. prefix.
	Name string
	// Permission is the operator scope required to invoke the action.
	Permission string
	// Command is the provider argv template.
	Command []string
}

// advertisedCapabilityRevision returns the descriptor revision the fixture
// adapter advertises.
//
// The revision is a declared value rather than a constant because agent.start
// compares the requested profile revision against it. A scenario that submits a
// start must therefore know the value, and a fixed constant would force every
// such scenario to hardcode it.
func advertisedCapabilityRevision(faults FaultInjection) string {
	if faults.CapabilityRevision != "" {
		return faults.CapabilityRevision
	}
	return "v1"
}

// advertisedCapabilityVersion returns the advertised version of one capability.
//
// The default is "v1" because that is the version of every operation whose
// payload schema version is also "v1". The two operations that carry a payload
// schema version of "1" are declared explicitly, so a scenario that drives one
// does not have to restate the whole list.
func advertisedCapabilityVersion(faults FaultInjection, name string) string {
	if version, ok := faults.CapabilityVersions[name]; ok {
		return version
	}
	return "v1"
}

// serverReadinessWait bounds how long StartCluster waits for the Server health
// endpoint. The Server must open its database, load certificates and start the
// channel listener before it answers, and under full-parallel package load the
// machine is busy with several other clusters at once. A short fixed budget
// expired before readiness and produced a flaky failure that was not a logic
// defect. The budget is generous because the poll returns as soon as the Server
// answers, so a healthy run is not slowed down.
const serverReadinessWait = 60 * time.Second

// waitServerReady waits for the Server health endpoint within the given budget.
// The budget is a parameter rather than a package-level switch so a caller can
// bound a diagnostic wait without mutating process-wide state.
func waitServerReady(cluster *Cluster, budget time.Duration) error {
	if err := WaitHTTPE(cluster.URL("/healthz"), "", http.StatusOK, budget); err != nil {
		return fmt.Errorf("wait for server readiness: %w", err)
	}
	return nil
}

// StartCluster starts an isolated real Server and Endpoint connected over mTLS.
func StartCluster(t testing.TB, options ClusterOptions) (*Cluster, error) {
	t.Helper()
	root := t.TempDir()
	certs, err := CertificatesE(root)
	if err != nil {
		return nil, fmt.Errorf("create certificates: %w", err)
	}
	serverBin, endpointBin, fixtureBin := filepath.Join(root, "server"), filepath.Join(root, "endpoint"), filepath.Join(root, "fixture")
	if err := Build(serverBin, "./src/main/agent-cluster-server"); err != nil {
		return nil, err
	}
	if err := Build(endpointBin, "./src/main/agent-cluster-endpoint"); err != nil {
		return nil, err
	}
	if err := Build(fixtureBin, "./tests/fixtures/provider"); err != nil {
		return nil, err
	}
	// The TopsailAI adapter resolves topsailai_session_info as a sibling of the
	// configured executable and never through PATH, so both entry points are built
	// into one provider directory when that adapter is selected.
	providerDir := filepath.Join(root, "provider")
	if options.ProviderType == "topsailai" {
		if err := os.MkdirAll(providerDir, 0o755); err != nil {
			return nil, fmt.Errorf("create provider directory: %w", err)
		}
		if err := Build(filepath.Join(providerDir, "topsailai"), "./tests/fixtures/topsailai_fixture"); err != nil {
			return nil, err
		}
		if err := Build(filepath.Join(providerDir, "topsailai_session_info"), "./tests/fixtures/topsailai_session_info_fixture"); err != nil {
			return nil, err
		}
	}
	apiPort, err := FreePortE()
	if err != nil {
		return nil, fmt.Errorf("allocate API port: %w", err)
	}
	channelPort, err := FreePortE()
	if err != nil {
		return nil, fmt.Errorf("allocate channel port: %w", err)
	}
	cluster := &Cluster{Root: root, API: apiPort, Channel: channelPort, ServerDB: filepath.Join(root, "server.db"), EndpointDB: filepath.Join(root, "endpoint.db"), Record: filepath.Join(root, "records.jsonl"), Certs: certs}
	// The Endpoint only listens when the Server dials, so its channel port is
	// allocated on demand and stays empty for the default direction.
	endpointChannelPort := ""
	if options.ChannelDirection == "server-initiated" || options.ChannelDirection == "bidirectional" {
		endpointChannelPort, err = FreePortE()
		if err != nil {
			return nil, fmt.Errorf("allocate endpoint channel port: %w", err)
		}
		cluster.EndpointChannel = endpointChannelPort
	}
	serverEnv := []string{"AGENT_CLUSTER_API_LISTEN_ADDR=127.0.0.1:" + cluster.API, "AGENT_CLUSTER_CHANNEL_LISTEN_ADDR=127.0.0.1:" + cluster.Channel, "AGENT_CLUSTER_DATABASE_PATH=" + cluster.ServerDB, "AGENT_CLUSTER_AUTH_TOKEN=secret", "AGENT_CLUSTER_TLS_CA_FILE=" + certs.CA, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE=" + certs.ServerCert, "AGENT_CLUSTER_TLS_KEY_FILE=" + certs.ServerKey}
	if options.ChannelDirection != "" {
		serverEnv = append(serverEnv, "AGENT_CLUSTER_CHANNEL_DIRECTION="+options.ChannelDirection)
	}
	if endpointChannelPort != "" {
		serverEnv = append(serverEnv, "AGENT_CLUSTER_ENDPOINT_DIAL_ADDRESSES=endpoint-1=wss://127.0.0.1:"+endpointChannelPort)
	}
	if options.SharedCertificate {
		serverEnv = append(serverEnv, "AGENT_CLUSTER_TLS_SHARED_CERTIFICATE=true")
	}
	serverEnv = appendFaultEnvironment(serverEnv, options.Faults)
	serverEnv = append(serverEnv, sortedEnvironment(options.Environment)...)
	cluster.Server, err = StartProcessE(serverBin, serverEnv)
	if err != nil {
		return nil, err
	}
	t.Cleanup(func() {
		if err := StopProcessE(cluster.Endpoint); err != nil {
			t.Logf("stop endpoint: %v", err)
		}
		if err := StopProcessE(cluster.Server); err != nil {
			t.Logf("stop server: %v", err)
		}
	})
	if err := waitServerReady(cluster, serverReadinessWait); err != nil {
		return nil, err
	}
	mode := "one"
	if options.Faults.NoSessions {
		mode = "empty"
	}
	// A scenario that needs a second, non-live session selects the mixed
	// document. It is a separate mode rather than an extra row in "one" because
	// every existing scenario resolves the first session as its default target,
	// and widening "one" would change what those scenarios observe.
	if options.Faults.FixtureMode != "" {
		mode = options.Faults.FixtureMode
	}
	discoveryCount := filepath.Join(root, "discovery-count")
	adapterArgs := []map[string]any{{"adapter_id": "fixture-main", "provider_type": "fixture", "command": fixtureBin, "args": []string{"--mode", mode, "--record-file", cluster.Record, "--discovery-count-file", discoveryCount, "--delay-ms", fmt.Sprint(options.DelayMS), "--output-size", fmt.Sprint(options.Faults.OutputSize)}, "timeout_ms": 5000}}
	// The TopsailAI adapter is the only adapter that can stream output, so a
	// follow scenario selects it explicitly. Its fixture answers discovery from a
	// workspace document and streams plain text records on the follow path.
	if options.ProviderType == "topsailai" {
		adapterArgs = []map[string]any{{"adapter_id": "topsailai-main", "provider_type": "topsailai", "command": filepath.Join(providerDir, "topsailai"), "args": []string{}, "timeout_ms": 5000}}
	}
	if options.Faults.TwoAdapters {
		adapterArgs = []map[string]any{{"adapter_id": "adapter-a", "provider_type": "fixture", "command": fixtureBin, "args": []string{"--mode", "one", "--record-file", cluster.Record, "--discovery-count-file", discoveryCount + "-a"}, "timeout_ms": 5000}, {"adapter_id": "adapter-b", "provider_type": "fixture", "command": fixtureBin, "args": []string{"--mode", "one", "--always-fail", "--record-file", cluster.Record, "--discovery-count-file", discoveryCount + "-b"}, "timeout_ms": 5000}}
	}
	if options.Faults.ProviderAlwaysFail && !options.Faults.TwoAdapters {
		adapterArgs[0]["args"].([]string)[1] = "fail"
	}
	// The generic fixture adapter's default capability list omits operations such
	// as context.inject, so a scenario that drives one declares the list it needs.
	// The default is a production value, so it is replaced here rather than
	// widened for every deployment.
	//
	// The descriptor revision is declared alongside the list because agent.start
	// compares the requested profile revision against it before the policy hook
	// runs. A descriptor without a revision therefore rejects every start with
	// profile_revision_mismatch, which would make a start scenario pass while
	// proving nothing about authorization.
	if len(options.Faults.AdvertisedCapabilities) > 0 {
		declared := make([]map[string]string, 0, len(options.Faults.AdvertisedCapabilities))
		for _, name := range options.Faults.AdvertisedCapabilities {
			declared = append(declared, map[string]string{"name": name, "version": advertisedCapabilityVersion(options.Faults, name)})
		}
		adapterArgs[0]["capabilities"] = map[string]any{"revision": advertisedCapabilityRevision(options.Faults), "capabilities": declared}
	}
	if options.Faults.UnsupportedCapability != "" {
		capabilities := []map[string]string{{"name": "message.send", "version": "v1"}, {"name": "execution.interrupt", "version": "v1"}, {"name": "agent.stop", "version": "v1"}}
		revision := advertisedCapabilityRevision(options.Faults)
		if declared, ok := adapterArgs[0]["capabilities"].(map[string]any); ok {
			capabilities = declared["capabilities"].([]map[string]string)
			if value, ok := declared["revision"].(string); ok {
				revision = value
			}
		}
		filtered := capabilities[:0]
		for _, capability := range capabilities {
			if capability["name"] != options.Faults.UnsupportedCapability {
				filtered = append(filtered, capability)
			}
		}
		adapterArgs[0]["capabilities"] = map[string]any{"revision": revision, "capabilities": filtered}
	}
	for i := range adapterArgs {
		if options.Faults.ProviderFailAdapterID == adapterArgs[i]["adapter_id"] {
			adapterArgs[i]["args"] = append(adapterArgs[i]["args"].([]string), "--fail-execution")
		}
	}
	adapterJSON, err := marshalAdapterConfigurationFn(adapterArgs)
	if err != nil {
		return nil, fmt.Errorf("marshal adapter configuration: %w", err)
	}
	args := "AGENT_CLUSTER_ADAPTERS=" + string(adapterJSON)
	// With one shared certificate the Endpoint presents the Server certificate as
	// its own client certificate, so the certificate no longer proves which
	// Endpoint is connecting.
	endpointCert, endpointKey := certs.ClientCert, certs.ClientKey
	if options.SharedCertificate {
		endpointCert, endpointKey = certs.ServerCert, certs.ServerKey
	}
	endpointEnv := []string{"AGENT_CLUSTER_CHANNEL_ADDRESS=wss://127.0.0.1:" + cluster.Channel, "AGENT_CLUSTER_ENDPOINT_ID=endpoint-1", "AGENT_CLUSTER_DATABASE_PATH=" + cluster.EndpointDB, "AGENT_CLUSTER_TLS_CA_FILE=" + certs.CA, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE=" + endpointCert, "AGENT_CLUSTER_TLS_KEY_FILE=" + endpointKey, args}
	if options.ChannelDirection != "" {
		endpointEnv = append(endpointEnv, "AGENT_CLUSTER_CHANNEL_DIRECTION="+options.ChannelDirection)
	}
	if endpointChannelPort != "" {
		endpointEnv = append(endpointEnv, "AGENT_CLUSTER_ENDPOINT_CHANNEL_LISTEN_ADDR=127.0.0.1:"+endpointChannelPort)
	}
	if options.SharedCertificate {
		endpointEnv = append(endpointEnv, "AGENT_CLUSTER_TLS_SHARED_CERTIFICATE=true")
	}
	endpointEnv = appendFaultEnvironment(endpointEnv, options.Faults)
	// The command allowlist and the control action catalog are Endpoint-local
	// administrative configuration, so they are written into the scenario
	// directory and exported to the Endpoint process only. A scenario that
	// proves the positive authorization path for command.exec or ctl. needs them:
	// without the allowlist command.exec fails closed with a configuration error,
	// and without the catalog no ctl. action is advertised at all, so both would
	// end before the policy hook and prove nothing about authorization.
	if len(options.Faults.CommandAllowlist) > 0 {
		allowlistPath, writeErr := writeCommandAllowlist(root, options.Faults.CommandAllowlist)
		if writeErr != nil {
			return nil, writeErr
		}
		endpointEnv = append(endpointEnv, "AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE="+allowlistPath)
	}
	if len(options.Faults.ControlActions) > 0 {
		catalogPath, writeErr := writeControlActionCatalog(root, options.Faults.ControlActions)
		if writeErr != nil {
			return nil, writeErr
		}
		endpointEnv = append(endpointEnv, "AGENT_CLUSTER_CONTROL_ACTION_FILE="+catalogPath)
	}
	endpointEnv = append(endpointEnv, sortedEnvironment(options.EndpointEnvironment)...)
	cluster.EndpointPath = endpointBin
	cluster.EndpointEnv = append([]string(nil), endpointEnv...)
	cluster.CLIEnv = sortedEnvironment(options.CLIEnvironment)
	cluster.Endpoint, err = StartProcessE(endpointBin, endpointEnv)
	if err != nil {
		return nil, err
	}
	if err := WaitInventoryForE(cluster.URL("/api/v1/endpoints/endpoint-1/session-state"), "secret", inventoryAdapterID(options), 20*time.Second); err != nil {
		return nil, err
	}
	return cluster, nil
}

// sortedEnvironment renders a configuration map as environment entries in a
// stable order.
//
// The order is sorted rather than map order so a failing scenario reproduces the
// same command line every run; an unstable order makes a diff of two runs look
// like a configuration change.
func sortedEnvironment(values map[string]string) []string {
	if len(values) == 0 {
		return nil
	}
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	entries := make([]string, 0, len(keys))
	for _, key := range keys {
		entries = append(entries, key+"="+values[key])
	}
	return entries
}

// writeCommandAllowlist writes the Endpoint-local command.exec allowlist and
// returns its path.
//
// Each entry is one argv prefix, one line per entry, which is the document shape
// the Endpoint parses. The file is written rather than the entries being passed
// inline because the allowlist is a file-only configuration surface: the Endpoint
// reads a path and reloads that file on SIGHUP.
func writeCommandAllowlist(root string, entries [][]string) (string, error) {
	lines := make([]string, 0, len(entries))
	for _, entry := range entries {
		if len(entry) == 0 {
			return "", fmt.Errorf("command allowlist entry must not be empty")
		}
		lines = append(lines, strings.Join(entry, " "))
	}
	path := filepath.Join(root, "command-allowlist.conf")
	if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
		return "", fmt.Errorf("write command allowlist: %w", err)
	}
	return path, nil
}

// writeControlActionCatalog writes the Endpoint-local ctl. action catalog and
// returns its path.
//
// The catalog is the only source of ctl. actions, so a scenario that proves the
// positive authorization path needs a real entry here. The document is JSON with
// one object per action, matching the shape the Endpoint validates at load time.
func writeControlActionCatalog(root string, actions []ControlAction) (string, error) {
	type entry struct {
		Name       string   `json:"name"`
		Permission string   `json:"permission"`
		Command    []string `json:"command"`
	}
	document := struct {
		Actions []entry `json:"actions"`
	}{Actions: make([]entry, 0, len(actions))}
	for _, action := range actions {
		if action.Name == "" || action.Permission == "" || len(action.Command) == 0 {
			return "", fmt.Errorf("control action %q requires a name, a permission and a command", action.Name)
		}
		document.Actions = append(document.Actions, entry{Name: action.Name, Permission: action.Permission, Command: action.Command})
	}
	data, err := json.Marshal(document)
	if err != nil {
		return "", fmt.Errorf("marshal control action catalog: %w", err)
	}
	path := filepath.Join(root, "control-actions.json")
	if err := os.WriteFile(path, data, 0o600); err != nil {
		return "", fmt.Errorf("write control action catalog: %w", err)
	}
	return path, nil
}

// inventoryAdapterID returns the adapter ID the inventory wait should expect.
// The default fixture configuration publishes "fixture-main", while a scenario
// that selects another provider type publishes its own adapter ID.
func inventoryAdapterID(options ClusterOptions) string {
	if options.ProviderType == "topsailai" {
		return "topsailai-main"
	}
	return ""
}

var marshalAdapterConfigurationFn = json.Marshal

// WaitForBeforeInvocationCrash waits for the process-composition crash marker.
func (c *Cluster) WaitForBeforeInvocationCrashE(limit time.Duration) error {
	marker := c.EndpointDB + ".crash-before-invocation"
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(marker); err == nil {
			return nil
		}
		time.Sleep(25 * time.Millisecond)
	}
	return fmt.Errorf("wait for crash marker before deadline: %s", marker)
}

// WaitForBeforeInvocationCrash preserves the legacy testing.TB API.
func (c *Cluster) WaitForBeforeInvocationCrash(t testing.TB, limit time.Duration) {
	t.Helper()
	if err := c.WaitForBeforeInvocationCrashE(limit); err != nil {
		t.Fatal(err)
	}
}

// RestartEndpointE stops and starts the owned Endpoint with its original configuration.
func (c *Cluster) RestartEndpointE() error {
	if err := stopProcessForRestartE(c.Endpoint); err != nil {
		return fmt.Errorf("stop endpoint: %w", err)
	}
	endpoint, err := StartProcessE(c.EndpointPath, c.EndpointEnv)
	if err != nil {
		return fmt.Errorf("start endpoint: %w", err)
	}
	c.Endpoint = endpoint
	if err := WaitInventoryE(c.URL("/api/v1/endpoints/endpoint-1/session-state"), "secret", 20*time.Second); err != nil {
		return fmt.Errorf("wait for endpoint inventory: %w", err)
	}
	return nil
}

// stopProcessForRestartE terminates the endpoint and accepts its expected non-zero exit status.
func stopProcessForRestartE(cmd *exec.Cmd) error {
	if cmd == nil || cmd.Process == nil || cmd.ProcessState != nil {
		return fmt.Errorf("endpoint process is not running")
	}
	pid := cmd.Process.Pid
	if err := syscall.Kill(pid, syscall.SIGTERM); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("signal process %d: %w", pid, err)
	}
	if err := cmd.Wait(); err != nil && !expectedEndpointExit(err) {
		return fmt.Errorf("wait for endpoint process %d: %w", pid, err)
	}
	return nil
}

// expectedEndpointExit reports the exit status produced by a deliberate endpoint stop.
func expectedEndpointExit(err error) bool {
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		return false
	}
	code := exitErr.ExitCode()
	return code == 98 || code == -1
}

// RestartEndpoint preserves the legacy testing.TB API.
func (c *Cluster) RestartEndpoint(t testing.TB) {
	t.Helper()
	if err := c.RestartEndpointE(); err != nil {
		t.Fatal(err)
	}
}

// Stop stops all processes owned by the cluster exactly once.
func (c *Cluster) Stop(t testing.TB) {
	t.Helper()
	c.stopMu.Lock()
	defer c.stopMu.Unlock()
	if c.stopped {
		return
	}
	c.stopped = true
	StopProcess(t, c.Endpoint2)
	StopProcess(t, c.Endpoint)
	StopProcess(t, c.Server)
}

// URL returns a Server API URL for the cluster.
func (c *Cluster) URL(path string) string { return "http://127.0.0.1:" + c.API + path }

// RequestE performs an authenticated request against the real Server.
func (c *Cluster) RequestE(method, path string, payload any) (int, []byte, error) {
	return c.RequestWithEndpointTokenE(method, path, payload, "")
}

// RequestWithEndpointTokenE performs an authenticated request that also presents
// an Endpoint token.
//
// The Endpoint token is a second, independent credential: the Server verifies the
// Server token and forwards the Endpoint token unchanged, while the Endpoint
// verifies it and decides whether the caller may exercise the operation. A
// request without it is refused by a policy-enforcing Endpoint, so a scenario
// that proves authorization must present one. An empty token keeps the previous
// behaviour, so existing scenarios are unchanged.
func (c *Cluster) RequestWithEndpointTokenE(method, path string, payload any, endpointToken string) (int, []byte, error) {
	var body io.Reader
	if payload != nil {
		data, err := json.Marshal(payload)
		if err != nil {
			return 0, nil, fmt.Errorf("marshal request payload: %w", err)
		}
		body = bytes.NewReader(data)
	}
	req, err := http.NewRequest(method, c.URL(path), body)
	if err != nil {
		return 0, nil, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer secret")
	if endpointToken != "" {
		req.Header.Set(endpointTokenHeader, endpointToken)
	}
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, nil, fmt.Errorf("send request: %w", err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, nil, fmt.Errorf("read response: %w", err)
	}
	return resp.StatusCode, data, nil
}

// Request preserves the legacy testing.TB API.
func (c *Cluster) Request(t testing.TB, method, path string, payload any) (int, []byte) {
	t.Helper()
	status, body, err := c.RequestE(method, path, payload)
	if err != nil {
		t.Fatal(err)
	}
	return status, body
}

// WaitHTTP preserves the legacy testing.TB API.
func WaitHTTP(t testing.TB, url, token string, want int, limit time.Duration) {
	t.Helper()
	if err := WaitHTTPE(url, token, want, limit); err != nil {
		t.Fatal(err)
	}
}

// WaitInventory preserves the legacy testing.TB API.
func WaitInventory(t testing.TB, url, token string, limit time.Duration) {
	t.Helper()
	if err := WaitInventoryE(url, token, limit); err != nil {
		t.Fatal(err)
	}
}

// ProviderInvocationsE returns durable fixture invocation evidence.
func (c *Cluster) ProviderInvocationsE() ([]map[string]any, error) {
	data, err := os.ReadFile(c.Record)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("read provider invocation record: %w", err)
	}
	var result []map[string]any
	for _, line := range bytes.Split(bytes.TrimSpace(data), []byte("\n")) {
		if len(line) == 0 {
			continue
		}
		var item map[string]any
		if err := json.Unmarshal(line, &item); err != nil {
			return nil, fmt.Errorf("decode provider invocation record: %w", err)
		}
		result = append(result, item)
	}
	return result, nil
}

// ProviderInvocations preserves the legacy testing.TB API.
func (c *Cluster) ProviderInvocations(t testing.TB) []map[string]any {
	t.Helper()
	result, err := c.ProviderInvocationsE()
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func appendFaultEnvironment(env []string, faults FaultInjection) []string {
	if faults.HoldPhase != "" && faults.HoldDir != "" {
		env = append(env, "AGENT_CLUSTER_TEST_HOLD_PHASE="+faults.HoldPhase, "AGENT_CLUSTER_TEST_HOLD_DIR="+faults.HoldDir)
	}
	if faults.DropAck {
		env = append(env, "AGENT_CLUSTER_TEST_DROP_ACK=1")
	}
	if faults.DispatchDelayMS > 0 {
		env = append(env, fmt.Sprintf("AGENT_CLUSTER_TEST_DISPATCH_DELAY_MS=%d", faults.DispatchDelayMS))
	}
	if faults.ReceiptDelayMS > 0 {
		env = append(env, fmt.Sprintf("AGENT_CLUSTER_TEST_DELAY_RECEIPT_MS=%d", faults.ReceiptDelayMS))
	}
	if faults.CrashAfterInvocationStarted {
		env = append(env, "AGENT_CLUSTER_TEST_CRASH_AFTER_INVOCATION_STARTED=1")
	}
	if faults.CrashBeforeInvocation {
		env = append(env, "AGENT_CLUSTER_TEST_CRASH_BEFORE_INVOCATION=1")
	}
	if faults.CollectionDelayMS > 0 {
		env = append(env, fmt.Sprintf("AGENT_CLUSTER_TEST_COLLECTION_DELAY_MS=%d", faults.CollectionDelayMS))
	}
	if faults.ProviderFailAfterN > 0 {
		env = append(env, fmt.Sprintf("AGENT_CLUSTER_TEST_PROVIDER_FAIL_AFTER_N=%d", faults.ProviderFailAfterN))
	}
	if faults.ProviderAlwaysFail {
		env = append(env, "AGENT_CLUSTER_TEST_PROVIDER_FAIL_AFTER_N=0")
	}
	if faults.OutputUnsupported {
		env = append(env, "AGENT_CLUSTER_TEST_OUTPUT_UNSUPPORTED=1")
	}
	if faults.ProviderInvocationLog != "" {
		env = append(env, "AGENT_CLUSTER_TEST_PROVIDER_INVOCATION_LOG="+faults.ProviderInvocationLog)
	}
	if faults.MessagesBody != "" {
		env = append(env, "AGENT_CLUSTER_TEST_MESSAGES_BODY="+faults.MessagesBody)
	}
	if faults.MessagesCount > 0 {
		env = append(env, fmt.Sprintf("AGENT_CLUSTER_TEST_MESSAGES_COUNT=%d", faults.MessagesCount))
	}
	return env
}

// BuildTUI compiles and caches the non-interactive TUI binary for this cluster.
func (c *Cluster) BuildTUI(tb testing.TB) (string, error) {
	tb.Helper()
	c.tuiBuildMu.Lock()
	defer c.tuiBuildMu.Unlock()
	if c.TUIPath != "" {
		return c.TUIPath, nil
	}
	path := filepath.Join(c.Root, "agent-cluster-cli")
	if err := Build(path, "./src/main/agent-cluster-cli"); err != nil {
		return "", err
	}
	c.TUIPath = path
	return path, nil
}

// RunTUI executes the TUI without a TTY and returns complete output and exit status.
func (c *Cluster) RunTUI(args ...string) (stdout string, stderr string, exitCode int, err error) {
	if c.TUIPath == "" {
		return "", "", -1, fmt.Errorf("TUI binary has not been built; call BuildTUI first")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, c.TUIPath, args...)
	cmd.Dir = ModuleRootForRun()
	cmd.Env = c.cliEnvironment()
	var out, stderrBuffer bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderrBuffer
	runErr := cmd.Run()
	if ctx.Err() != nil {
		return out.String(), stderrBuffer.String(), -1, ctx.Err()
	}
	exitCode = 0
	if runErr != nil {
		exitCode = 1
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			exitCode = exitErr.ExitCode()
		}
	}
	return out.String(), stderrBuffer.String(), exitCode, runErr
}

// RunTUIInteractive drives the interactive REPL through a pseudo-terminal.
// Interactive mode refuses a non-TTY stdin, so the scripted input is delivered
// through "script", which allocates a PTY. TERM=dumb keeps the plain line reader
// instead of the raw-mode editor, so the scripted lines are read verbatim.
// The combined terminal output is returned because the REPL writes prompts and
// results to the same terminal stream.
func (c *Cluster) RunTUIInteractive(stdin string, args ...string) (stdout string, stderr string, exitCode int, err error) {
	return c.runTUIInteractiveWithTerm(stdin, "dumb", args...)
}

// RunTUIInteractiveEditor drives the REPL through a PTY with a real TERM, so the
// raw-mode editor is active. Auto-refresh needs that editor, because TERM=dumb
// selects the plain reader and watch then refuses explicitly.
func (c *Cluster) RunTUIInteractiveEditor(stdin string, args ...string) (stdout string, stderr string, exitCode int, err error) {
	return c.runTUIInteractiveWithTerm(stdin, "xterm-256color", args...)
}

// runTUIInteractiveWithTerm runs the REPL under one terminal type.
func (c *Cluster) runTUIInteractiveWithTerm(stdin string, termType string, args ...string) (stdout string, stderr string, exitCode int, err error) {
	return c.runTUIInteractiveWithReader(strings.NewReader(stdin), termType, args...)
}

// runTUIInteractiveWithReader runs the REPL under one terminal type with an
// arbitrary input reader, so a caller can pace the scripted input instead of
// delivering it in one burst.
func (c *Cluster) runTUIInteractiveWithReader(stdin io.Reader, termType string, args ...string) (stdout string, stderr string, exitCode int, err error) {
	if c.TUIPath == "" {
		return "", "", -1, fmt.Errorf("TUI binary has not been built; call BuildTUI first")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	// The command string is passed to a shell, so the binary path is quoted.
	command := "'" + c.TUIPath + "' -i"
	for _, argument := range args {
		command += " '" + argument + "'"
	}
	cmd := exec.CommandContext(ctx, "script", "-qec", command, "/dev/null")
	cmd.Dir = ModuleRootForRun()
	cmd.Env = append(c.cliEnvironment(), "TERM="+termType)
	cmd.Stdin = stdin
	var out, stderrBuffer bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderrBuffer
	runErr := cmd.Run()
	if ctx.Err() != nil {
		return out.String(), stderrBuffer.String(), -1, ctx.Err()
	}
	exitCode = 0
	if runErr != nil {
		exitCode = 1
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			exitCode = exitErr.ExitCode()
		}
	}
	return out.String(), stderrBuffer.String(), exitCode, runErr
}

// cliEnvironment returns the environment for one CLI process: the connection
// settings every scenario needs, plus the scenario's own client configuration.
//
// The client configuration is appended last so a scenario can override a default
// rather than being silently shadowed by it.
func (c *Cluster) cliEnvironment() []string {
	env := append(os.Environ(),
		"AGENT_CLUSTER_SERVER_URL="+c.URL(""),
		"AGENT_CLUSTER_TOKEN=secret",
		"AGENT_CLUSTER_TLS_CA_FILE="+c.Certs.CA,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+c.Certs.ClientCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+c.Certs.ClientKey,
	)
	return append(env, c.CLIEnv...)
}

// ModuleRootForRun returns the repository root from the harness package working directory.
func ModuleRootForRun() string {
	wd, err := os.Getwd()
	if err != nil {
		return wd
	}
	return filepath.Clean(filepath.Join(wd, "..", ".."))
}
