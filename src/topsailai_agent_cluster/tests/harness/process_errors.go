package harness

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
)

// FreePortE reserves and releases a loopback port without terminating a test.
func FreePortE() (string, error) {
	return freePortAtE("127.0.0.1:0")
}

func freePortAtE(address string) (string, error) {
	listener, err := net.Listen("tcp", address)
	if err != nil {
		return "", fmt.Errorf("reserve loopback port: %w", err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	if err := listener.Close(); err != nil {
		return "", fmt.Errorf("release loopback port %d: %w", port, err)
	}
	return fmt.Sprint(port), nil
}

// CertificatesE creates certificates and reports filesystem or cryptographic failures.
func CertificatesE(dir string) (CertFiles, error) {
	caKey, err := generateKeyE()
	if err != nil {
		return CertFiles{}, fmt.Errorf("generate CA key: %w", err)
	}
	caTemplate := certificateTemplateE("ca", true)
	caDER, err := x509.CreateCertificate(rand.Reader, caTemplate, caTemplate, &caKey.PublicKey, caKey)
	if err != nil {
		return CertFiles{}, fmt.Errorf("create CA certificate: %w", err)
	}
	ca, _, err := writeCertificateE(dir, "ca", caDER, caKey)
	if err != nil {
		return CertFiles{}, err
	}
	serverKey, err := generateKeyE()
	if err != nil {
		return CertFiles{}, fmt.Errorf("generate server key: %w", err)
	}
	serverTemplate := certificateTemplateE("agent-cluster-server", false)
	serverTemplate.DNSNames = []string{"localhost", "agent-cluster-server"}
	serverDER, err := x509.CreateCertificate(rand.Reader, serverTemplate, caTemplate, &serverKey.PublicKey, caKey)
	if err != nil {
		return CertFiles{}, fmt.Errorf("create server certificate: %w", err)
	}
	serverCert, serverKeyPath, err := writeCertificateE(dir, "server", serverDER, serverKey)
	if err != nil {
		return CertFiles{}, err
	}
	clientKey, err := generateKeyE()
	if err != nil {
		return CertFiles{}, fmt.Errorf("generate client key: %w", err)
	}
	clientDER, err := x509.CreateCertificate(rand.Reader, certificateTemplateE("endpoint-1", false), caTemplate, &clientKey.PublicKey, caKey)
	if err != nil {
		return CertFiles{}, fmt.Errorf("create client certificate: %w", err)
	}
	clientCert, clientKeyPath, err := writeCertificateE(dir, "client", clientDER, clientKey)
	if err != nil {
		return CertFiles{}, err
	}
	clientKey2, err := generateKeyE()
	if err != nil {
		return CertFiles{}, fmt.Errorf("generate second client key: %w", err)
	}
	clientDER2, err := x509.CreateCertificate(rand.Reader, certificateTemplateE("endpoint-2", false), caTemplate, &clientKey2.PublicKey, caKey)
	if err != nil {
		return CertFiles{}, fmt.Errorf("create second client certificate: %w", err)
	}
	clientCert2, clientKeyPath2, err := writeCertificateE(dir, "client-2", clientDER2, clientKey2)
	if err != nil {
		return CertFiles{}, err
	}
	return CertFiles{CA: ca, ServerCert: serverCert, ServerKey: serverKeyPath, ClientCert: clientCert, ClientKey: clientKeyPath, ClientCert2: clientCert2, ClientKey2: clientKeyPath2}, nil
}

// StartProcessE starts a child process and reports startup failures.
func StartProcessE(path string, env []string) (*exec.Cmd, error) {
	cmd := exec.Command(path)
	cmd.Dir = ModuleRootForBuild()
	cmd.Env = mergeEnvironment(env)
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start process %s: %w", path, err)
	}
	return cmd, nil
}

// StopProcessE stops one owned child and reports signaling or wait failures.
func StopProcessE(cmd *exec.Cmd) error {
	if cmd == nil || cmd.Process == nil || cmd.ProcessState != nil {
		return nil
	}
	pid := cmd.Process.Pid
	if err := syscall.Kill(pid, syscall.SIGTERM); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("stop process %d: %w", pid, err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		if err != nil && !os.IsNotExist(err) {
			return fmt.Errorf("wait for process %d: %w", pid, err)
		}
		return nil
	case <-time.After(30 * time.Second):
		return fmt.Errorf("process %d did not stop", pid)
	}
}

// WaitHTTPE waits for a bounded HTTP status result and reports timeout or request failures.
func WaitHTTPE(url, token string, want int, limit time.Duration) error {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		req, err := http.NewRequest(http.MethodGet, url, nil)
		if err != nil {
			return fmt.Errorf("create HTTP readiness request: %w", err)
		}
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		resp, err := http.DefaultClient.Do(req)
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == want {
				return nil
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	return fmt.Errorf("HTTP %s did not return %d before deadline", url, want)
}

// WaitInventoryE waits for the first real Endpoint inventory report.
func WaitInventoryE(url, token string, limit time.Duration) error {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		req, err := http.NewRequest(http.MethodGet, url, nil)
		if err != nil {
			return fmt.Errorf("create inventory request: %w", err)
		}
		req.Header.Set("Authorization", "Bearer "+token)
		resp, err := http.DefaultClient.Do(req)
		if err == nil {
			data, readErr := io.ReadAll(resp.Body)
			resp.Body.Close()
			if readErr != nil {
				return fmt.Errorf("read inventory response: %w", readErr)
			}
			if resp.StatusCode == http.StatusOK && (bytes.Contains(data, []byte("fixture-main")) || bytes.Contains(data, []byte("adapter-a"))) {
				return nil
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	return fmt.Errorf("real Endpoint inventory was not reported before deadline")
}

func generateKeyE() (*ecdsa.PrivateKey, error) {
	return ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
}
func certificateTemplateE(name string, ca bool) *x509.Certificate {
	return &x509.Certificate{SerialNumber: big.NewInt(time.Now().UnixNano()), Subject: pkix.Name{CommonName: name}, NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(time.Hour), IsCA: ca, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign}
}
func writeCertificateE(dir, name string, der []byte, key *ecdsa.PrivateKey) (string, string, error) {
	certPath, keyPath := filepath.Join(dir, name+".pem"), filepath.Join(dir, name+"-key.pem")
	certFile, err := os.Create(certPath)
	if err != nil {
		return "", "", fmt.Errorf("create certificate %s: %w", certPath, err)
	}
	if err := pem.Encode(certFile, &pem.Block{Type: "CERTIFICATE", Bytes: der}); err != nil {
		_ = certFile.Close()
		return "", "", fmt.Errorf("write certificate %s: %w", certPath, err)
	}
	if err := certFile.Close(); err != nil {
		return "", "", fmt.Errorf("close certificate %s: %w", certPath, err)
	}
	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		return "", "", fmt.Errorf("marshal key %s: %w", keyPath, err)
	}
	keyFile, err := os.Create(keyPath)
	if err != nil {
		return "", "", fmt.Errorf("create key %s: %w", keyPath, err)
	}
	if err := pem.Encode(keyFile, &pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER}); err != nil {
		_ = keyFile.Close()
		return "", "", fmt.Errorf("write key %s: %w", keyPath, err)
	}
	if err := keyFile.Close(); err != nil {
		return "", "", fmt.Errorf("close key %s: %w", keyPath, err)
	}
	return certPath, keyPath, nil
}
