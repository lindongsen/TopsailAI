package channel

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
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
	"topsailai_agent_cluster/internal/security"
)

type channelTLSMaterial struct{ ca, serverCert, serverKey, clientCert, clientKey string }

func newChannelTLSMaterial(t *testing.T) channelTLSMaterial {
	t.Helper()
	dir := t.TempDir()
	caKey := channelKey(t)
	ca := channelCert(t, "ca", true)
	caDER := channelSign(t, ca, ca, &caKey.PublicKey, caKey)
	serverKey := channelKey(t)
	serverDER := channelSign(t, channelCert(t, "agent-cluster-server", false), ca, &serverKey.PublicKey, caKey)
	clientKey := channelKey(t)
	clientDER := channelSign(t, channelCert(t, "endpoint-1", false), ca, &clientKey.PublicKey, caKey)
	return channelTLSMaterial{ca: channelWriteCert(t, dir, "ca", caDER), serverCert: channelWriteCert(t, dir, "server", serverDER), serverKey: channelWriteKey(t, dir, "server", serverKey), clientCert: channelWriteCert(t, dir, "client", clientDER), clientKey: channelWriteKey(t, dir, "client", clientKey)}
}
func (m channelTLSMaterial) pool(t *testing.T) *x509.CertPool {
	t.Helper()
	pool := x509.NewCertPool()
	data, err := os.ReadFile(m.ca)
	if err != nil {
		t.Fatal(err)
	}
	pool.AppendCertsFromPEM(data)
	return pool
}
func channelKey(t *testing.T) *ecdsa.PrivateKey {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	return key
}
func channelCert(t *testing.T, name string, ca bool) *x509.Certificate {
	t.Helper()
	serial, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 120))
	return &x509.Certificate{SerialNumber: serial, Subject: pkix.Name{CommonName: name}, DNSNames: []string{name}, NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(time.Hour), IsCA: ca, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth, x509.ExtKeyUsageServerAuth}}
}
func channelSign(t *testing.T, cert, parent *x509.Certificate, pub *ecdsa.PublicKey, key *ecdsa.PrivateKey) []byte {
	t.Helper()
	data, err := x509.CreateCertificate(rand.Reader, cert, parent, pub, key)
	if err != nil {
		t.Fatal(err)
	}
	return data
}
func channelWriteCert(t *testing.T, dir, name string, data []byte) string {
	t.Helper()
	path := filepath.Join(dir, name+".pem")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	_ = pem.Encode(f, &pem.Block{Type: "CERTIFICATE", Bytes: data})
	return path
}
func channelWriteKey(t *testing.T, dir, name string, key *ecdsa.PrivateKey) string {
	t.Helper()
	path := filepath.Join(dir, name+"-key.pem")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	data, _ := x509.MarshalECPrivateKey(key)
	_ = pem.Encode(f, &pem.Block{Type: "EC PRIVATE KEY", Bytes: data})
	return path
}

func TestMTLSRejectsHelloIdentityMismatch(t *testing.T) {
	material := newChannelTLSMaterial(t)
	serverTLS, err := security.LoadMTLSConfig(security.MTLSConfig{CAFile: material.ca, CertificateFile: material.serverCert, KeyFile: material.serverKey}, true)
	if err != nil {
		t.Fatal(err)
	}
	channelServer := NewServer(serverTLS)
	rejected := make(chan string, 1)
	channelServer.OnRejectReason = func(_, _, reason, _ string) { rejected <- reason }
	httpServer := httpServerForChannel(t, channelServer, serverTLS)
	defer httpServer.Close()
	defer channelServer.Close()
	clientCert, err := tls.LoadX509KeyPair(material.clientCert, material.clientKey)
	if err != nil {
		t.Fatal(err)
	}
	u, _ := url.Parse(httpServer.URL)
	u.Scheme = "wss"
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, u.String(), &websocket.DialOptions{HTTPClient: &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{RootCAs: material.pool(t), ServerName: "agent-cluster-server", Certificates: []tls.Certificate{clientCert}, MinVersion: tls.VersionTLS13}}}})
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "done")
	if err := wsjson.Write(ctx, conn, Frame{Type: FrameHello, ProtocolVersion: ProtocolVersion, EndpointID: "wrong-endpoint", InstanceID: "instance-1", RequestID: "request-1"}); err != nil {
		t.Fatal(err)
	}
	var rejection Frame
	if err := wsjson.Read(ctx, conn, &rejection); err != nil {
		t.Fatalf("read structured rejection: %v", err)
	}
	if rejection.Type != FrameHelloRejected || rejection.Reason != "identity_mismatch" || rejection.RequestID != "request-1" {
		t.Fatalf("unexpected rejection frame: %+v", rejection)
	}
	select {
	case reason := <-rejected:
		if reason != "identity_mismatch" {
			t.Fatalf("rejection reason = %q", reason)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("identity rejection was not logged")
	}
}

func httpServerForChannel(t *testing.T, channelServer *Server, config *tls.Config) *httptest.Server {
	t.Helper()
	httpServer := httptest.NewUnstartedServer(http.HandlerFunc(channelServer.Handler))
	httpServer.TLS = config
	httpServer.StartTLS()
	return httpServer
}
