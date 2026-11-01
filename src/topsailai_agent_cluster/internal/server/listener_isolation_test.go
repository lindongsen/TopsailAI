package server_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/security"
	server "topsailai_agent_cluster/internal/server"
	storage "topsailai_agent_cluster/internal/storage/server"
)

func TestListenerIsolation(t *testing.T) {
	files := makeCerts(t)
	store, err := storage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	tlsConfig, err := security.LoadMTLSConfig(security.MTLSConfig{CAFile: files.ca, CertificateFile: files.cert, KeyFile: files.key}, true)
	if err != nil {
		t.Fatal(err)
	}
	api, channelAddr := freePort(t), freePort(t)
	svc, err := server.NewService(server.ServiceDeps{APIHandler: server.NewHandler(store, "secret"), ChannelServer: channel.NewServer(tlsConfig), Storage: store, APIListenAddress: "127.0.0.1:" + api, ChannelListenAddress: "127.0.0.1:" + channelAddr, ChannelTLSConfig: tlsConfig})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- svc.Run(ctx) }()
	waitHTTP(t, "http://127.0.0.1:"+api+"/healthz", "", http.StatusOK)
	request(t, "http://127.0.0.1:"+api+"/api/v1/endpoints", "secret", http.StatusOK)
	request(t, "http://127.0.0.1:"+api+"/api/v1/endpoints", "wrong", http.StatusUnauthorized)
	raw, err := net.DialTimeout("tcp", "127.0.0.1:"+channelAddr, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer raw.Close()
	tlsConn := tls.Client(raw, &tls.Config{InsecureSkipVerify: true})
	err = tlsConn.Handshake()
	if err == nil {
		buffer := make([]byte, 1)
		_ = tlsConn.SetReadDeadline(time.Now().Add(time.Second))
		_, err = tlsConn.Read(buffer)
	}
	if err == nil {
		tlsConn.Close()
		t.Fatal("channel accepted no certificate")
	}
	if !strings.Contains(err.Error(), "certificate") && !strings.Contains(err.Error(), "handshake") && !strings.Contains(err.Error(), "closed") {
		t.Fatalf("unexpected TLS error: %v", err)
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("service did not stop")
	}
	if err := svc.Close(); err != nil {
		t.Fatal(err)
	}
}
func request(t *testing.T, url, token string, want int) {
	t.Helper()
	req, _ := http.NewRequest(http.MethodGet, url, nil)
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != want {
		t.Fatalf("status=%d want=%d", resp.StatusCode, want)
	}
}
func waitHTTP(t *testing.T, url, token string, want int) {
	t.Helper()
	end := time.Now().Add(5 * time.Second)
	for time.Now().Before(end) {
		req, _ := http.NewRequest(http.MethodGet, url, nil)
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		resp, err := http.DefaultClient.Do(req)
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == want {
				return
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("did not receive HTTP %d", want)
}
func freePort(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	p := l.Addr().(*net.TCPAddr).Port
	l.Close()
	return big.NewInt(int64(p)).String()
}

type certFiles struct{ ca, cert, key string }

func makeCerts(t *testing.T) certFiles {
	t.Helper()
	dir := t.TempDir()
	cak := newKey(t)
	cat := cert("ca", true)
	cad, err := x509.CreateCertificate(rand.Reader, cat, cat, &cak.PublicKey, cak)
	if err != nil {
		t.Fatal(err)
	}
	cap, _ := write(t, dir, "ca", cad, cak)
	sk := newKey(t)
	st := cert("agent-cluster-server", false)
	st.DNSNames = []string{"localhost", "agent-cluster-server"}
	sd, err := x509.CreateCertificate(rand.Reader, st, cat, &sk.PublicKey, cak)
	if err != nil {
		t.Fatal(err)
	}
	cp, kp := write(t, dir, "server", sd, sk)
	return certFiles{cap, cp, kp}
}
func newKey(t *testing.T) *ecdsa.PrivateKey {
	t.Helper()
	k, e := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if e != nil {
		t.Fatal(e)
	}
	return k
}
func cert(name string, ca bool) *x509.Certificate {
	return &x509.Certificate{SerialNumber: big.NewInt(time.Now().UnixNano()), Subject: pkix.Name{CommonName: name}, NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(time.Hour), IsCA: ca, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign}
}
func write(t *testing.T, dir, name string, der []byte, k *ecdsa.PrivateKey) (string, string) {
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
