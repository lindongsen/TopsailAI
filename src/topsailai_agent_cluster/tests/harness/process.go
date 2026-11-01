// Package harness provides isolated real-process test resources for integration and BDD tests.
package harness

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"fmt"
	"math/big"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"
)

// CertFiles contains the CA and endpoint/server certificate paths for one scenario.
type CertFiles struct {
	CA, ServerCert, ServerKey string
	ClientCert, ClientKey     string
	ClientCert2, ClientKey2   string
}

// Cluster contains process paths and isolated persistent state for a scenario.
type Cluster struct {
	Root, API, Channel          string
	ServerDB, EndpointDB        string
	Server, Endpoint, Endpoint2 *exec.Cmd
	Record, Record2             string
	EndpointPath                string
	EndpointEnv                 []string
	Certs                       CertFiles
	TUIPath                     string
	tuiBuildMu                  sync.Mutex
	stopMu                      sync.Mutex
	stopped                     bool
}

// ModuleRoot returns the repository root for tests launched from a package directory.
func ModuleRoot(t testing.TB) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	return filepath.Clean(filepath.Join(wd, "..", ".."))
}

// FreePort reserves and releases a loopback port for a child-process listener.
func FreePort(t testing.TB) string {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	if err := listener.Close(); err != nil {
		t.Fatal(err)
	}
	return fmt.Sprint(port)
}

// Build compiles one repository command into the scenario directory.
func Build(output, packagePath string) error {
	cmd := exec.Command("go", "build", "-tags=testhooks", "-o", output, packagePath)
	cmd.Dir = ModuleRootForBuild()
	outputBytes, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("build %s: %w\n%s", packagePath, err, outputBytes)
	}
	return nil
}

// ModuleRootForBuild returns the repository root without coupling build failures to a test.
func ModuleRootForBuild() string {
	wd, err := os.Getwd()
	if err != nil {
		return wd
	}
	return filepath.Clean(filepath.Join(wd, "..", ".."))
}

// Certificates creates a private CA and server/client certificates under dir.
func Certificates(t testing.TB, dir string) CertFiles {
	t.Helper()
	caKey := key(t)
	caTemplate := template("ca", true)
	caDER, err := x509.CreateCertificate(rand.Reader, caTemplate, caTemplate, &caKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	ca, _ := writeCert(t, dir, "ca", caDER, caKey)
	serverKey := key(t)
	serverTemplate := template("agent-cluster-server", false)
	serverTemplate.DNSNames = []string{"localhost", "agent-cluster-server"}
	serverDER, err := x509.CreateCertificate(rand.Reader, serverTemplate, caTemplate, &serverKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	serverCert, serverKeyPath := writeCert(t, dir, "server", serverDER, serverKey)
	clientKey := key(t)
	clientTemplate := template("endpoint-1", false)
	clientDER, err := x509.CreateCertificate(rand.Reader, clientTemplate, caTemplate, &clientKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	clientCert, clientKeyPath := writeCert(t, dir, "client", clientDER, clientKey)
	clientKey2 := key(t)
	clientTemplate2 := template("endpoint-2", false)
	clientDER2, err := x509.CreateCertificate(rand.Reader, clientTemplate2, caTemplate, &clientKey2.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	clientCert2, clientKeyPath2 := writeCert(t, dir, "client-2", clientDER2, clientKey2)
	return CertFiles{CA: ca, ServerCert: serverCert, ServerKey: serverKeyPath, ClientCert: clientCert, ClientKey: clientKeyPath, ClientCert2: clientCert2, ClientKey2: clientKeyPath2}
}

// StartProcess starts a child process with the repository as its working directory.
func StartProcess(t testing.TB, path string, env []string) *exec.Cmd {
	t.Helper()
	cmd := exec.Command(path)
	cmd.Dir = ModuleRoot(t)
	cmd.Env = mergeEnvironment(env)
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	return cmd
}

// mergeEnvironment applies overrides once so inherited configuration cannot shadow scenario ports.
func mergeEnvironment(overrides []string) []string {
	values := make(map[string]string)
	order := make([]string, 0)
	for _, entry := range append(os.Environ(), overrides...) {
		key, _, ok := strings.Cut(entry, "=")
		if !ok {
			continue
		}
		if _, exists := values[key]; !exists {
			order = append(order, key)
		}
		values[key] = entry
	}
	result := make([]string, 0, len(order))
	for _, key := range order {
		result = append(result, values[key])
	}
	return result
}

// StopProcess sends SIGTERM to one owned child and waits for its exit.
func StopProcess(t testing.TB, cmd *exec.Cmd) {
	t.Helper()
	if cmd == nil || cmd.Process == nil {
		return
	}
	if cmd.ProcessState != nil {
		return
	}
	if err := syscall.Kill(cmd.Process.Pid, syscall.SIGTERM); err != nil {
		if os.IsNotExist(err) {
			return
		}
		t.Logf("stop process: %v", err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case <-done:
	case <-time.After(30 * time.Second):
		t.Fatalf("process %d did not stop", cmd.Process.Pid)
	}
}

func key(t testing.TB) *ecdsa.PrivateKey {
	t.Helper()
	value, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	return value
}
func template(name string, ca bool) *x509.Certificate {
	return &x509.Certificate{SerialNumber: newSerial(), Subject: pkix.Name{CommonName: name}, NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(time.Hour), IsCA: ca, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign}
}
func newSerial() *big.Int { return new(big.Int).SetInt64(time.Now().UnixNano()) }
func writeCert(t testing.TB, dir, name string, der []byte, key *ecdsa.PrivateKey) (string, string) {
	t.Helper()
	certPath, keyPath := filepath.Join(dir, name+".pem"), filepath.Join(dir, name+"-key.pem")
	certFile, err := os.Create(certPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := pem.Encode(certFile, &pem.Block{Type: "CERTIFICATE", Bytes: der}); err != nil {
		t.Fatal(err)
	}
	_ = certFile.Close()
	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	keyFile, err := os.Create(keyPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := pem.Encode(keyFile, &pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER}); err != nil {
		t.Fatal(err)
	}
	_ = keyFile.Close()
	return certPath, keyPath
}
