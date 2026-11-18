package packaging_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// ctlAuthModeProbe is a stand-in role binary that records the authentication
// settings it inherited, then stays alive briefly.
//
// It records the environment rather than the argument vector because the mode is
// environment-only: neither the Server nor the Endpoint binary has an
// --auth-mode flag, so a launcher that forwarded it as a flag would be forwarding
// a value nothing reads. The probe therefore proves the value reached the child
// process under the name the binary actually reads.
//
// It sleeps after writing because the controller treats a process that exits
// during its confirmation window as a failed launch. The sleep keeps the launch
// observable without making the test depend on the controller's timing.
const ctlAuthModeProbe = `#!/bin/bash
{
    printf 'SERVER_AUTH_MODE=%s\n' "${AGENT_CLUSTER_SERVER_AUTH_MODE:-}"
    printf 'ENDPOINT_AUTH_MODE=%s\n' "${AGENT_CLUSTER_ENDPOINT_AUTH_MODE:-}"
    printf 'SERVER_SIGNATURE_WINDOW=%s\n' "${AGENT_CLUSTER_SERVER_SIGNATURE_WINDOW:-}"
    printf 'ENDPOINT_SIGNATURE_WINDOW=%s\n' "${AGENT_CLUSTER_ENDPOINT_SIGNATURE_WINDOW:-}"
} >"${PROBE_OUT}"
sleep 5
`

// newCtlAuthModeBundle builds a throwaway node bundle whose role binary is the
// probe above, so the test drives the shipped controller instead of a
// reimplementation of its argument and environment construction.
func newCtlAuthModeBundle(t *testing.T, role string, extraConfig string) (ctl, config, probeOut string) {
	t.Helper()
	dir := t.TempDir()

	ctl = filepath.Join(dir, "agent-clusterctl")
	source, err := os.ReadFile(filepath.Join("..", "..", "scripts", "agent-clusterctl"))
	if err != nil {
		t.Fatalf("read controller: %v", err)
	}
	if err := os.WriteFile(ctl, source, 0o755); err != nil {
		t.Fatalf("write controller: %v", err)
	}

	probe := filepath.Join(dir, "probe")
	if err := os.WriteFile(probe, []byte(ctlAuthModeProbe), 0o755); err != nil {
		t.Fatalf("write probe: %v", err)
	}

	// The controller resolves a role configuration below conf/<role>, so the
	// bundle has to carry that layout rather than a single flat file.
	configDir := filepath.Join(dir, "conf", role)
	if err := os.MkdirAll(configDir, 0o755); err != nil {
		t.Fatalf("create config dir: %v", err)
	}
	for _, sub := range []string{"run", "logs", "data", "certs"} {
		if err := os.MkdirAll(filepath.Join(dir, sub), 0o755); err != nil {
			t.Fatalf("create %s: %v", sub, err)
		}
	}
	// The controller refuses to launch without TLS material, so the bundle
	// carries placeholders. They are never parsed: the probe opens no listener,
	// and this test asserts environment forwarding only.
	for _, name := range []string{"ca.pem", "node.pem", "node-key.pem"} {
		if err := os.WriteFile(filepath.Join(dir, "certs", name), []byte("placeholder\n"), 0o600); err != nil {
			t.Fatalf("write %s: %v", name, err)
		}
	}

	probeOut = filepath.Join(dir, "probe.out")
	config = filepath.Join(configDir, "node.conf")

	lines := []string{
		"ROLE=" + role,
		"BINARY=" + probe,
		"PID_FILE=../../run/" + role + ".pid",
		"STDOUT_LOG=../../logs/" + role + ".stdout.log",
		"LOG_PATH=../../logs/" + role + ".log",
		"TLS_CA_FILE=../../certs/ca.pem",
		"TLS_CERTIFICATE_FILE=../../certs/node.pem",
		"TLS_KEY_FILE=../../certs/node-key.pem",
		// A non-zero window keeps the probe alive long enough for the controller
		// to confirm the launch instead of reporting an immediate exit.
		"START_CONFIRM_TENTHS=5",
	}
	if role == "endpoint" {
		lines = append(lines,
			"ENDPOINT_ID=probe-endpoint",
			"INSTANCE_ID=probe-endpoint-1",
			"CHANNEL_ADDRESS=wss://127.0.0.1:53943",
			// The controller refuses an Endpoint with no adapter document, so the
			// bundle declares one. It is never invoked: the probe opens no
			// listener, and this test asserts environment forwarding only.
			`ADAPTERS='[{"adapter_id":"probe","provider_type":"genericcli","command":"/bin/true","capabilities":{"capabilities":[]}}]'`,
		)
	}
	body := strings.Join(lines, "\n") + "\n" + extraConfig
	if err := os.WriteFile(config, []byte(body), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}
	return ctl, config, probeOut
}

// runCtlAuthModeProbe starts the node through the controller and returns the
// settings the probe observed.
//
// The probe is started in the background by the controller, so the output file is
// polled with a bounded deadline rather than read once. Reading it once would
// race the child's own startup and report a missing file for a launch that
// succeeded.
func runCtlAuthModeProbe(t *testing.T, ctl, config, probeOut string) map[string]string {
	t.Helper()
	dir := filepath.Dir(ctl)

	cmd := exec.Command(ctl, "-c", config, "start")
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "PROBE_OUT="+probeOut)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("controller start failed: %v\n%s", err, out)
	}

	// The probe outlives the controller, so the test owns its cleanup.
	t.Cleanup(func() {
		raw, err := os.ReadFile(filepath.Join(dir, "run", "probe.pid"))
		if err != nil {
			return
		}
		pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
		if err != nil || pid <= 0 {
			return
		}
		if proc, err := os.FindProcess(pid); err == nil {
			_ = proc.Kill()
		}
	})

	deadline := time.Now().Add(5 * time.Second)
	for {
		raw, err := os.ReadFile(probeOut)
		if err == nil {
			observed := map[string]string{}
			for _, line := range strings.Split(strings.TrimSpace(string(raw)), "\n") {
				key, value, ok := strings.Cut(line, "=")
				if ok {
					observed[key] = value
				}
			}
			return observed
		}
		if time.Now().After(deadline) {
			t.Fatalf("probe did not run within the deadline: %v", err)
		}
		time.Sleep(20 * time.Millisecond)
	}
}

// TestCtlForwardsServerAuthMode proves the Server role receives the configured
// authentication mode under the name its binary reads.
//
// The defect this guards is silent in the direction that matters: node.conf
// spells the setting AUTH_MODE, the sourcing exports it under that name, and the
// binary reads AGENT_CLUSTER_SERVER_AUTH_MODE. Without the mapping the Server
// starts in its default mode while the configuration says otherwise, and only
// the startup log names the mode actually in force.
func TestCtlForwardsServerAuthMode(t *testing.T) {
	ctl, config, probeOut := newCtlAuthModeBundle(t, "server", "AUTH_MODE=bearer\nSIGNATURE_WINDOW=90s\n")

	observed := runCtlAuthModeProbe(t, ctl, config, probeOut)

	if got := observed["SERVER_AUTH_MODE"]; got != "bearer" {
		t.Fatalf("AGENT_CLUSTER_SERVER_AUTH_MODE=%q want %q", got, "bearer")
	}
	if got := observed["SERVER_SIGNATURE_WINDOW"]; got != "90s" {
		t.Fatalf("AGENT_CLUSTER_SERVER_SIGNATURE_WINDOW=%q want %q", got, "90s")
	}
	// The Endpoint names must stay empty for a Server, because a Server never
	// verifies the endpoint-token. A launcher that exported both would make one
	// process carry a setting that belongs to the other role.
	if got := observed["ENDPOINT_AUTH_MODE"]; got != "" {
		t.Fatalf("AGENT_CLUSTER_ENDPOINT_AUTH_MODE=%q want empty for the server role", got)
	}
}

// TestCtlForwardsEndpointAuthMode proves the Endpoint role receives the same
// settings under its own names.
func TestCtlForwardsEndpointAuthMode(t *testing.T) {
	ctl, config, probeOut := newCtlAuthModeBundle(t, "endpoint", "AUTH_MODE=hmac\nSIGNATURE_WINDOW=2m\n")

	observed := runCtlAuthModeProbe(t, ctl, config, probeOut)

	if got := observed["ENDPOINT_AUTH_MODE"]; got != "hmac" {
		t.Fatalf("AGENT_CLUSTER_ENDPOINT_AUTH_MODE=%q want %q", got, "hmac")
	}
	if got := observed["ENDPOINT_SIGNATURE_WINDOW"]; got != "2m" {
		t.Fatalf("AGENT_CLUSTER_ENDPOINT_SIGNATURE_WINDOW=%q want %q", got, "2m")
	}
	if got := observed["SERVER_AUTH_MODE"]; got != "" {
		t.Fatalf("AGENT_CLUSTER_SERVER_AUTH_MODE=%q want empty for the endpoint role", got)
	}
}

// TestCtlOmitsAuthModeWhenUnset proves an unset value stays unset.
//
// The binary owns the default, so the launcher must not invent one. Exporting an
// empty string would be worse than omitting the variable: the binary treats an
// empty value as "not configured" today, but a future validation that rejected
// an empty value would then fail a node whose configuration never mentioned the
// setting at all.
func TestCtlOmitsAuthModeWhenUnset(t *testing.T) {
	ctl, config, probeOut := newCtlAuthModeBundle(t, "server", "")

	observed := runCtlAuthModeProbe(t, ctl, config, probeOut)

	if got := observed["SERVER_AUTH_MODE"]; got != "" {
		t.Fatalf("AGENT_CLUSTER_SERVER_AUTH_MODE=%q want empty when AUTH_MODE is unset", got)
	}
	if got := observed["SERVER_SIGNATURE_WINDOW"]; got != "" {
		t.Fatalf("AGENT_CLUSTER_SERVER_SIGNATURE_WINDOW=%q want empty when SIGNATURE_WINDOW is unset", got)
	}
}
