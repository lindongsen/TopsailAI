package server

import (
	"fmt"
	"net"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"topsailai_connector/internal/security"
)

// DefaultListenAddress is the address the Server listens on when
// CONNECTOR_SERVER_LISTEN is unset. One listener serves both the channel at
// /channel and the CLI API at /v1/, so there is no second port to configure and
// no way for the two to be configured out of step.
const DefaultListenAddress = ":8443"

// DefaultRequestTimeout is how long the Server waits for a Node response before
// reporting node_timeout. It is a bound on one forwarded request, not on the
// channel, because a channel that has been open for a month says nothing about
// whether the Node is answering now.
const DefaultRequestTimeout = 30 * time.Second

// MaxRequestTimeout bounds the configured timeout. A timeout measured in hours
// is not a timeout: it turns a dead Node into a request that holds a caller's
// connection open until the caller gives up, which is the failure the timeout
// exists to prevent.
const MaxRequestTimeout = time.Hour

// Config is the Server's startup configuration.
//
// It holds the two secrets the Server owns and nothing else. There is
// deliberately no field for a Node's node-token: the Server forwards that value
// on the request it arrives with and keeps no copy, so a field for it would be
// the first step toward storing it.
//
// The value is built once at the process boundary and passed down. Nothing below
// the boundary reads the environment, because a function that reads a
// process-wide variable hides a dependency and cannot be tested without mutating
// global state.
type Config struct {
	// Listen is the address the single listener binds.
	Listen string
	// TLSCert is the path to the TLS certificate, or empty when TLS is
	// terminated in front of the Server.
	TLSCert string
	// TLSKey is the path to the TLS private key, or empty for the same reason.
	TLSKey string
	// TunnelToken is the secret a Node presents in hello. It gates the channel
	// and grants nothing else.
	TunnelToken security.Secret
	// ClientToken is the secret a CLI presents on every request. It gates the
	// CLI API and grants nothing else.
	ClientToken security.Secret
	// RequestTimeout bounds one forwarded request.
	RequestTimeout time.Duration
}

// LoadConfig builds a Config from a lookup function.
//
// The lookup function is a parameter rather than a direct os.Getenv call so a
// test can supply a fixed environment without touching the process. Every
// failure is a startup failure: a Server that starts with a missing secret is a
// Server whose operator believes it is authenticating callers it is not.
func LoadConfig(lookup func(string) string) (Config, error) {
	if lookup == nil {
		return Config{}, fmt.Errorf("environment lookup is nil")
	}

	listen := lookup("CONNECTOR_SERVER_LISTEN")
	if listen == "" {
		listen = DefaultListenAddress
	}
	if err := validateListenAddress(listen); err != nil {
		return Config{}, err
	}

	certPath, keyPath, err := resolveTLS(lookup("CONNECTOR_SERVER_TLS_CERT"), lookup("CONNECTOR_SERVER_TLS_KEY"))
	if err != nil {
		return Config{}, err
	}

	tunnelToken := security.Secret(lookup("CONNECTOR_SERVER_TUNNEL_TOKEN"))
	if err := tunnelToken.Validate("CONNECTOR_SERVER_TUNNEL_TOKEN"); err != nil {
		return Config{}, err
	}

	clientToken := security.Secret(lookup("CONNECTOR_SERVER_CLIENT_TOKEN"))
	if err := clientToken.Validate("CONNECTOR_SERVER_CLIENT_TOKEN"); err != nil {
		return Config{}, err
	}

	timeout, err := resolveRequestTimeout(lookup("CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS"))
	if err != nil {
		return Config{}, err
	}

	return Config{
		Listen:         listen,
		TLSCert:        certPath,
		TLSKey:         keyPath,
		TunnelToken:    tunnelToken,
		ClientToken:    clientToken,
		RequestTimeout: timeout,
	}, nil
}

// validateListenAddress checks that the address is a host and a port.
//
// An empty host is accepted because ":8443" means every interface, which is the
// ordinary deployment. A missing port is refused, because a listener with no port
// is a listener the operator cannot predict.
//
// The host is not resolved here. A DNS lookup during configuration validation
// would make startup depend on a resolver, would turn a typo into a slow failure
// instead of an immediate one, and would make the check untestable without a
// network. The bind call is the authority on whether the host is usable.
func validateListenAddress(value string) error {
	host, port, err := net.SplitHostPort(value)
	if err != nil {
		return fmt.Errorf("CONNECTOR_SERVER_LISTEN %q is not host:port: %w", value, err)
	}
	if port == "" {
		return fmt.Errorf("CONNECTOR_SERVER_LISTEN %q has no port", value)
	}
	number, err := strconv.Atoi(port)
	if err != nil {
		return fmt.Errorf("CONNECTOR_SERVER_LISTEN %q has a non-numeric port %q", value, port)
	}
	if number < 1 || number > 65535 {
		return fmt.Errorf("CONNECTOR_SERVER_LISTEN %q has port %d, want 1 to 65535", value, number)
	}
	if host != strings.TrimSpace(host) {
		return fmt.Errorf("CONNECTOR_SERVER_LISTEN %q has whitespace around the host", value)
	}
	return nil
}

// resolveTLS returns the certificate and key paths, refusing a half-configured
// pair.
//
// One path without the other is refused rather than ignored, because a Server
// that silently fell back to plaintext after a typo in the key path would serve
// two secrets over an unprotected connection.
func resolveTLS(certPath, keyPath string) (string, string, error) {
	if certPath == "" && keyPath == "" {
		return "", "", nil
	}
	if certPath == "" {
		return "", "", fmt.Errorf("CONNECTOR_SERVER_TLS_KEY is set but CONNECTOR_SERVER_TLS_CERT is empty; a key without a certificate cannot serve TLS")
	}
	if keyPath == "" {
		return "", "", fmt.Errorf("CONNECTOR_SERVER_TLS_CERT is set but CONNECTOR_SERVER_TLS_KEY is empty; a certificate without a key cannot serve TLS")
	}
	for name, value := range map[string]string{
		"CONNECTOR_SERVER_TLS_CERT": certPath,
		"CONNECTOR_SERVER_TLS_KEY":  keyPath,
	} {
		if !filepath.IsAbs(value) {
			return "", "", fmt.Errorf("%s %q is relative; a relative path resolves differently per launch", name, value)
		}
	}
	return certPath, keyPath, nil
}

// resolveRequestTimeout parses the timeout in seconds, applying the default when
// the variable is unset.
func resolveRequestTimeout(value string) (time.Duration, error) {
	if value == "" {
		return DefaultRequestTimeout, nil
	}
	seconds, err := strconv.Atoi(value)
	if err != nil {
		return 0, fmt.Errorf("CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS %q is not a whole number of seconds", value)
	}
	if seconds < 1 {
		return 0, fmt.Errorf("CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS is %d, want at least 1", seconds)
	}
	timeout := time.Duration(seconds) * time.Second
	if timeout > MaxRequestTimeout {
		return 0, fmt.Errorf("CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS is %d, want at most %d", seconds, int(MaxRequestTimeout/time.Second))
	}
	return timeout, nil
}

// TLSEnabled reports whether the Server terminates TLS itself.
func (c Config) TLSEnabled() bool {
	return c.TLSCert != "" && c.TLSKey != ""
}

// Redacted renders the configuration for a log line.
//
// Both secrets are replaced by their redacted form and the paths are kept,
// because a path is not a credential. The method exists so a caller never has to
// decide field by field what may be printed: the decision is made once, here.
func (c Config) Redacted() string {
	return fmt.Sprintf("listen=%s tls=%t tunnel_token=%s client_token=%s request_timeout=%s",
		c.Listen, c.TLSEnabled(), c.TunnelToken.Redacted(), c.ClientToken.Redacted(), c.RequestTimeout)
}

// String renders the configuration with both secrets redacted, so a Config that
// is printed by accident does not leak either one.
func (c Config) String() string {
	return c.Redacted()
}
