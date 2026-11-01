package security

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestMTLSHandshakeMatrix(t *testing.T) {
	material := newTLSMaterial(t)
	t.Run("no client certificate", func(t *testing.T) {
		server := listenTLS(t, material, "")
		defer server.close()
		clientErr, serverErr := handshakePair(t, server, clientTLSConfig(t, material.ca, "", ""))
		if clientErr == nil && serverErr == nil {
			t.Fatal("expected certificate rejection")
		}
		if serverErr == nil || (!strings.Contains(serverErr.Error(), "certificate required") && !strings.Contains(serverErr.Error(), "didn't provide a certificate")) {
			t.Fatalf("server error = %v, client error = %v", serverErr, clientErr)
		}
	})
	t.Run("wrong CA", func(t *testing.T) {
		wrong := newTLSMaterial(t)
		server := listenTLS(t, material, "")
		defer server.close()
		clientErr, serverErr := handshakePair(t, server, clientTLSConfig(t, material.ca, wrong.clientCert, wrong.clientKey))
		if clientErr == nil && serverErr == nil {
			t.Fatal("expected wrong CA rejection")
		}
		if serverErr == nil || !strings.Contains(serverErr.Error(), "certificate") {
			t.Fatalf("server error = %v, client error = %v", serverErr, clientErr)
		}
	})
	t.Run("revoked certificate", func(t *testing.T) {
		revokedPath := filepath.Join(t.TempDir(), "revoked.txt")
		if err := os.WriteFile(revokedPath, []byte(material.clientSerial), 0o600); err != nil {
			t.Fatal(err)
		}
		server := listenTLSWithRevocation(t, material, revokedPath)
		defer server.close()
		clientErr, serverErr := handshakePair(t, server, clientTLSConfig(t, material.ca, material.clientCert, material.clientKey))
		if clientErr == nil && serverErr == nil {
			t.Fatal("expected revoked rejection")
		}
		if serverErr == nil || !strings.Contains(serverErr.Error(), "revoked") {
			t.Fatalf("server error = %v, client error = %v", serverErr, clientErr)
		}
	})
	t.Run("valid certificate", func(t *testing.T) {
		server := listenTLS(t, material, "")
		defer server.close()
		clientErr, serverErr := handshakePair(t, server, clientTLSConfig(t, material.ca, material.clientCert, material.clientKey))
		if clientErr != nil || serverErr != nil {
			t.Fatalf("client error = %v, server error = %v", clientErr, serverErr)
		}
	})
}

type tlsListener struct {
	listener net.Listener
	result   chan error
}

func listenTLS(t *testing.T, material tlsMaterial, revoked string) *tlsListener {
	return listenTLSWithConfig(t, material, func(c *tls.Config) { c.VerifyConnection = nil }, revoked)
}
func listenTLSWithRevocation(t *testing.T, material tlsMaterial, revoked string) *tlsListener {
	return listenTLSWithConfig(t, material, nil, revoked)
}
func listenTLSWithConfig(t *testing.T, material tlsMaterial, adjust func(*tls.Config), revoked string) *tlsListener {
	config, err := LoadMTLSConfig(MTLSConfig{CAFile: material.ca, CertificateFile: material.serverCert, KeyFile: material.serverKey, RevokedSerialsFile: revoked}, true)
	if err != nil {
		t.Fatal(err)
	}
	if adjust != nil {
		adjust(config)
	}
	listener, err := tls.Listen("tcp", "127.0.0.1:0", config)
	if err != nil {
		t.Fatal(err)
	}
	server := &tlsListener{listener: listener, result: make(chan error, 1)}
	go func() {
		conn, acceptErr := listener.Accept()
		if acceptErr != nil {
			server.result <- acceptErr
			return
		}
		tlsConn := conn.(*tls.Conn)
		server.result <- tlsConn.Handshake()
		_ = conn.Close()
	}()
	return server
}
func (s *tlsListener) close() { _ = s.listener.Close() }
func handshakePair(t *testing.T, server *tlsListener, config *tls.Config) (error, error) {
	t.Helper()
	client, clientErr := tls.Dial("tcp", server.listener.Addr().String(), config)
	if client != nil {
		_ = client.Close()
	}
	select {
	case serverErr := <-server.result:
		return clientErr, serverErr
	case <-time.After(2 * time.Second):
		t.Fatal("server handshake timeout")
		return clientErr, nil
	}
}

type tlsMaterial struct{ ca, serverCert, serverKey, clientCert, clientKey, clientSerial string }

func newTLSMaterial(t *testing.T) tlsMaterial {
	t.Helper()
	dir := t.TempDir()
	caKey := newKey(t)
	caTemplate := certTemplate(t, "ca", true)
	caDER := sign(t, caTemplate, caTemplate, &caKey.PublicKey, caKey)
	caPath := writeCert(t, dir, "ca", caDER)
	serverKey := newKey(t)
	serverDER := sign(t, certTemplate(t, "agent-cluster-server", false), caTemplate, &serverKey.PublicKey, caKey)
	clientKey := newKey(t)
	clientTemplate := certTemplate(t, "endpoint-1", false)
	clientDER := sign(t, clientTemplate, caTemplate, &clientKey.PublicKey, caKey)
	return tlsMaterial{ca: caPath, serverCert: writeCert(t, dir, "server", serverDER), serverKey: writeKey(t, dir, "server", serverKey), clientCert: writeCert(t, dir, "client", clientDER), clientKey: writeKey(t, dir, "client", clientKey), clientSerial: clientTemplate.SerialNumber.String()}
}
func newKey(t *testing.T) *ecdsa.PrivateKey {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	return key
}
func certTemplate(t *testing.T, name string, ca bool) *x509.Certificate {
	t.Helper()
	serial, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 120))
	return &x509.Certificate{SerialNumber: serial, Subject: pkix.Name{CommonName: name}, DNSNames: []string{name}, NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(time.Hour), IsCA: ca, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth, x509.ExtKeyUsageServerAuth}}
}
func sign(t *testing.T, tmpl, parent *x509.Certificate, pub *ecdsa.PublicKey, key *ecdsa.PrivateKey) []byte {
	t.Helper()
	der, err := x509.CreateCertificate(rand.Reader, tmpl, parent, pub, key)
	if err != nil {
		t.Fatal(err)
	}
	return der
}
func writeCert(t *testing.T, dir, name string, der []byte) string {
	t.Helper()
	path := filepath.Join(dir, name+".pem")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	_ = pem.Encode(f, &pem.Block{Type: "CERTIFICATE", Bytes: der})
	return path
}
func writeKey(t *testing.T, dir, name string, key *ecdsa.PrivateKey) string {
	t.Helper()
	path := filepath.Join(dir, name+"-key.pem")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	der, _ := x509.MarshalECPrivateKey(key)
	_ = pem.Encode(f, &pem.Block{Type: "EC PRIVATE KEY", Bytes: der})
	return path
}
func clientTLSConfig(t *testing.T, ca, cert, key string) *tls.Config {
	t.Helper()
	roots := x509.NewCertPool()
	data, _ := os.ReadFile(ca)
	roots.AppendCertsFromPEM(data)
	config := &tls.Config{RootCAs: roots, ServerName: "agent-cluster-server", MinVersion: tls.VersionTLS13}
	if cert != "" {
		pair, err := tls.LoadX509KeyPair(cert, key)
		if err != nil {
			t.Fatal(err)
		}
		config.Certificates = []tls.Certificate{pair}
	}
	return config
}
