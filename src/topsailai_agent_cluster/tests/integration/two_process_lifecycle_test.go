//go:build integration

package integration_test

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestTwoProcessLifecycle(t *testing.T) {
	root := t.TempDir()
	certs := makeIntegrationCerts(t, root)
	serverBin := filepath.Join(root, "server")
	endpointBin := filepath.Join(root, "endpoint")
	fixture := filepath.Join(root, "fixture")
	build(t, serverBin, "./src/main/agent-cluster-server")
	build(t, endpointBin, "./src/main/agent-cluster-endpoint")
	build(t, fixture, "./tests/fixtures/provider")
	api, channel := free(t), free(t)
	db := filepath.Join(root, "server.db")
	endpointDB := filepath.Join(root, "endpoint.db")
	serverCmd := exec.Command(serverBin)
	serverCmd.Dir = moduleRoot(t)
	serverCmd.Env = append(os.Environ(), "AGENT_CLUSTER_SERVER_API_LISTEN_ADDR=127.0.0.1:"+api, "AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR=127.0.0.1:"+channel, "AGENT_CLUSTER_DATABASE_PATH="+db, "AGENT_CLUSTER_SERVER_AUTH_TOKEN=secret", "AGENT_CLUSTER_TLS_CA_FILE="+certs.ca, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.serverCert, "AGENT_CLUSTER_TLS_KEY_FILE="+certs.serverKey, "AGENT_CLUSTER_LOG_OUTPUT=stderr")
	serverCmd.Stdout, serverCmd.Stderr = os.Stdout, os.Stderr
	if err := serverCmd.Start(); err != nil {
		t.Fatal(err)
	}
	serverPID := serverCmd.Process.Pid
	defer terminate(t, serverCmd)
	waitHTTP(t, "http://127.0.0.1:"+api+"/healthz", "", 200, 15*time.Second)
	endpointCmd := exec.Command(endpointBin)
	endpointCmd.Dir = moduleRoot(t)
	endpointCmd.Env = append(os.Environ(), "AGENT_CLUSTER_CHANNEL_ADDRESS=wss://127.0.0.1:"+channel, "AGENT_CLUSTER_ENDPOINT_ID=endpoint-1", "AGENT_CLUSTER_DATABASE_PATH="+endpointDB, "AGENT_CLUSTER_TLS_CA_FILE="+certs.ca, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.clientCert, "AGENT_CLUSTER_TLS_KEY_FILE="+certs.clientKey, "AGENT_CLUSTER_ADAPTERS="+fmt.Sprintf(`[{"adapter_id":"fixture-main","provider_type":"fixture","command":%q,"args":["--mode","one"],"timeout_ms":5000}]`, fixture), "AGENT_CLUSTER_LOG_OUTPUT=stderr")
	endpointCmd.Stdout, endpointCmd.Stderr = os.Stdout, os.Stderr
	if err := endpointCmd.Start(); err != nil {
		t.Fatal(err)
	}
	endpointPID := endpointCmd.Process.Pid
	defer terminate(t, endpointCmd)
	waitInventory(t, "http://127.0.0.1:"+api+"/api/v1/endpoints/endpoint-1/session-state", "secret", 20*time.Second)
	if err := syscall.Kill(serverPID, syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Kill(endpointPID, syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	waitExit(t, serverCmd, 30*time.Second)
	waitExit(t, endpointCmd, 30*time.Second)
	assertGone(t, serverPID)
	assertGone(t, endpointPID)
}

type certFiles struct {
	ca, serverCert, serverKey string
	clientCert, clientKey     string
	clientCert2, clientKey2   string
}

func build(t *testing.T, out, dir string) {
	t.Helper()
	cmd := exec.Command("go", "build", "-tags=testhooks", "-o", out, dir)
	cmd.Dir = moduleRoot(t)
	if b, e := cmd.CombinedOutput(); e != nil {
		t.Fatalf("build %s: %v\n%s", dir, e, b)
	}
}
func moduleRoot(t *testing.T) string {
	t.Helper()
	wd, e := os.Getwd()
	if e != nil {
		t.Fatal(e)
	}
	return filepath.Clean(filepath.Join(wd, "..", ".."))
}
func free(t *testing.T) string {
	t.Helper()
	l, e := net.Listen("tcp", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	p := l.Addr().(*net.TCPAddr).Port
	l.Close()
	return fmt.Sprint(p)
}
func waitHTTP(t *testing.T, url, token string, want int, limit time.Duration) {
	t.Helper()
	end := time.Now().Add(limit)
	for time.Now().Before(end) {
		req, _ := http.NewRequest(http.MethodGet, url, nil)
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		r, e := http.DefaultClient.Do(req)
		if e == nil {
			r.Body.Close()
			if r.StatusCode == want {
				return
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("HTTP %s did not return %d", url, want)
}
func waitInventory(t *testing.T, url, token string, limit time.Duration) {
	t.Helper()
	type adapter struct {
		AdapterID string `json:"adapter_id"`
	}
	type payload struct {
		Adapters []adapter `json:"adapters"`
	}
	type envelopeType struct {
		Data payload `json:"data"`
	}
	end := time.Now().Add(limit)
	for time.Now().Before(end) {
		req, _ := http.NewRequest(http.MethodGet, url, nil)
		req.Header.Set("Authorization", "Bearer "+token)
		resp, err := http.DefaultClient.Do(req)
		if err == nil {
			body, readErr := io.ReadAll(resp.Body)
			resp.Body.Close()
			var envelope envelopeType
			if readErr == nil && resp.StatusCode == http.StatusOK && json.Unmarshal(body, &envelope) == nil && len(envelope.Data.Adapters) > 0 && envelope.Data.Adapters[0].AdapterID == "fixture-main" {
				return
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatal("inventory was not reported")
}
func waitExit(t *testing.T, cmd *exec.Cmd, limit time.Duration) {
	t.Helper()
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		if err != nil {
			t.Logf("process exited with %v", err)
		}
	case <-time.After(limit):
		t.Fatal("process did not exit")
	}
}
func terminate(t *testing.T, cmd *exec.Cmd) {
	t.Helper()
	if cmd.Process == nil {
		return
	}
	if err := syscall.Kill(cmd.Process.Pid, syscall.SIGTERM); err == nil {
		waitExit(t, cmd, 30*time.Second)
	}
}
func assertGone(t *testing.T, pid int) {
	t.Helper()
	if err := syscall.Kill(pid, 0); err == nil || !strings.Contains(err.Error(), "no such process") {
		t.Fatalf("pid %d still exists: %v", pid, err)
	}
}
func makeIntegrationCerts(t *testing.T, dir string) certFiles {
	t.Helper()
	ck := key(t)
	ct := template("ca", true)
	cd, _ := x509.CreateCertificate(rand.Reader, ct, ct, &ck.PublicKey, ck)
	cap, _ := writeCert(t, dir, "ca", cd, ck)
	sk := key(t)
	st := template("agent-cluster-server", false)
	st.DNSNames = []string{"localhost", "agent-cluster-server"}
	sd, _ := x509.CreateCertificate(rand.Reader, st, ct, &sk.PublicKey, ck)
	scp, skp := writeCert(t, dir, "server", sd, sk)
	ek := key(t)
	et := template("endpoint-1", false)
	ed, _ := x509.CreateCertificate(rand.Reader, et, ct, &ek.PublicKey, ck)
	ecp, ekp := writeCert(t, dir, "client", ed, ek)
	ek2 := key(t)
	et2 := template("endpoint-2", false)
	ed2, _ := x509.CreateCertificate(rand.Reader, et2, ct, &ek2.PublicKey, ck)
	ecp2, ekp2 := writeCert(t, dir, "client-2", ed2, ek2)
	return certFiles{ca: cap, serverCert: scp, serverKey: skp, clientCert: ecp, clientKey: ekp, clientCert2: ecp2, clientKey2: ekp2}
}
func key(t *testing.T) *ecdsa.PrivateKey {
	t.Helper()
	k, e := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if e != nil {
		t.Fatal(e)
	}
	return k
}
func template(name string, ca bool) *x509.Certificate {
	return &x509.Certificate{SerialNumber: big.NewInt(time.Now().UnixNano()), Subject: pkix.Name{CommonName: name}, NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(time.Hour), IsCA: ca, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign}
}
func writeCert(t *testing.T, dir, name string, der []byte, k *ecdsa.PrivateKey) (string, string) {
	t.Helper()
	cp, kp := filepath.Join(dir, name+".pem"), filepath.Join(dir, name+"-key.pem")
	f, e := os.Create(cp)
	if e != nil {
		t.Fatal(e)
	}
	pem.Encode(f, &pem.Block{Type: "CERTIFICATE", Bytes: der})
	f.Close()
	kd, e := x509.MarshalECPrivateKey(k)
	if e != nil {
		t.Fatal(e)
	}
	f, e = os.Create(kp)
	if e != nil {
		t.Fatal(e)
	}
	pem.Encode(f, &pem.Block{Type: "EC PRIVATE KEY", Bytes: kd})
	f.Close()
	return cp, kp
}
