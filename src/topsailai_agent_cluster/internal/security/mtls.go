package security

import (
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"fmt"
	"os"
	"strings"
)

// MTLSConfig contains certificate material and the revoked certificate serials.
type MTLSConfig struct {
	CAFile             string
	CertificateFile    string
	KeyFile            string
	RevokedSerialsFile string
}

// LoadMTLSConfig builds a mutual-TLS configuration for a server or client.
func LoadMTLSConfig(config MTLSConfig, server bool) (*tls.Config, error) {
	caBytes, err := os.ReadFile(config.CAFile)
	if err != nil {
		return nil, fmt.Errorf("read CA certificate: %w", err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(caBytes) {
		return nil, fmt.Errorf("parse CA certificate")
	}
	certificate, err := tls.LoadX509KeyPair(config.CertificateFile, config.KeyFile)
	if err != nil {
		return nil, fmt.Errorf("load TLS certificate: %w", err)
	}
	revoked, err := loadRevokedSerials(config.RevokedSerialsFile)
	if err != nil {
		return nil, err
	}
	verify := func(state tls.ConnectionState) error {
		if len(state.PeerCertificates) == 0 {
			return fmt.Errorf("peer certificate is required")
		}
		if revoked[state.PeerCertificates[0].SerialNumber.String()] {
			return fmt.Errorf("peer certificate is revoked")
		}
		return nil
	}
	result := &tls.Config{MinVersion: tls.VersionTLS13, Certificates: []tls.Certificate{certificate}, ClientCAs: roots, RootCAs: roots, VerifyConnection: verify}
	if server {
		result.ClientAuth = tls.RequireAndVerifyClientCert
		result.ClientCAs = roots
	} else {
		result.ServerName = "agent-cluster-server"
	}
	return result, nil
}

// ValidateEndpointIdentity verifies that a certificate identifies the claimed Endpoint.
func ValidateEndpointIdentity(certificate *x509.Certificate, endpointID string) error {
	if certificate == nil || endpointID == "" {
		return fmt.Errorf("endpoint identity certificate is missing")
	}
	if certificate.Subject.CommonName == endpointID {
		return nil
	}
	for _, name := range certificate.DNSNames {
		if name == endpointID {
			return nil
		}
	}
	for _, name := range certificate.URIs {
		if name.String() == endpointID {
			return nil
		}
	}
	return fmt.Errorf("certificate identity does not match endpoint %q", endpointID)
}

// IsCertificateRevoked reports whether a certificate serial is in the configured rejection set.
func IsCertificateRevoked(certificate *x509.Certificate, revoked map[string]bool) bool {
	return certificate != nil && revoked[certificate.SerialNumber.String()]
}

// CertificateFingerprint returns the SHA-256 fingerprint of a DER certificate.
func CertificateFingerprint(certificate *x509.Certificate) string {
	digest := sha256.Sum256(certificate.Raw)
	return strings.ToUpper(hex.EncodeToString(digest[:]))
}

func loadRevokedSerials(path string) (map[string]bool, error) {
	result := make(map[string]bool)
	if path == "" {
		return result, nil
	}
	contents, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read revoked certificate list: %w", err)
	}
	for _, line := range strings.Split(string(contents), "\n") {
		serial := strings.TrimSpace(line)
		if serial != "" {
			result[serial] = true
		}
	}
	return result, nil
}
