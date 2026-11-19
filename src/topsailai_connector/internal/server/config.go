package server

import (
	"fmt"
	"net"
	"os"
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

// DefaultClientCredentialFile is the file the Server reads its client credentials
// from when CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE is unset.
//
// The credentials live in a file rather than in one environment variable because a
// single variable cannot express several public key identifiers, and because a file
// can be replaced atomically while an environment variable cannot. The file is
// resolved relative to the working directory only when the operator names it; the
// default is absolute so a Server started from a different directory does not read
// a different credential set.
const DefaultClientCredentialFile = ""

// Config is the Server's startup configuration.
//
// It holds the two secrets the Server owns and nothing else. There is
// deliberately no field for a Node's credential: the Server forwards the Node proof
// on the request it arrives with and keeps no copy, so a field for it would be the
// first step toward storing it.
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
	// ClientCredentials is the set of client credentials the Server accepts. Each
	// entry is a public key identifier and the secret that verifies its proofs.
	ClientCredentials *security.CredentialSet
	// ReplayWindow is how far a client proof timestamp may differ from the
	// Server's clock.
	ReplayWindow time.Duration
	// ReplayCapacity bounds the number of unexpired client nonces the Server
	// records.
	ReplayCapacity int
	// RequestTimeout bounds one forwarded request.
	RequestTimeout time.Duration
	// MaxInFlightPerCaller bounds one caller's concurrent requests. Zero means
	// the default, which is substituted in NewHandler.
	MaxInFlightPerCaller int
	// MaxInFlightPerNode bounds one Node's concurrent requests. Zero means the
	// default.
	MaxInFlightPerNode int
	// MaxInFlight bounds the whole process. Zero means the default.
	MaxInFlight int
	// AdmissionWait is how long a request may wait for a slot before it is
	// refused with overloaded. Zero means the default.
	AdmissionWait time.Duration
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

	credentials, err := loadClientCredentials(lookup)
	if err != nil {
		return Config{}, err
	}

	window, err := resolveReplayWindow(lookup("CONNECTOR_SERVER_REPLAY_WINDOW_SECONDS"))
	if err != nil {
		return Config{}, err
	}

	capacity, err := resolveReplayCapacity(lookup("CONNECTOR_SERVER_REPLAY_CAPACITY"))
	if err != nil {
		return Config{}, err
	}

	timeout, err := resolveRequestTimeout(lookup("CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS"))
	if err != nil {
		return Config{}, err
	}

	perCaller, err := resolveAdmissionLimit("CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_CALLER", lookup("CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_CALLER"), DefaultMaxInFlightPerCaller)
	if err != nil {
		return Config{}, err
	}

	perNode, err := resolveAdmissionLimit("CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_NODE", lookup("CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_NODE"), DefaultMaxInFlightPerNode)
	if err != nil {
		return Config{}, err
	}

	total, err := resolveAdmissionLimit("CONNECTOR_SERVER_MAX_IN_FLIGHT", lookup("CONNECTOR_SERVER_MAX_IN_FLIGHT"), DefaultMaxInFlight)
	if err != nil {
		return Config{}, err
	}

	wait, err := resolveAdmissionWait(lookup("CONNECTOR_SERVER_ADMISSION_WAIT_MS"))
	if err != nil {
		return Config{}, err
	}

	return Config{
		Listen:               listen,
		TLSCert:              certPath,
		TLSKey:               keyPath,
		TunnelToken:          tunnelToken,
		ClientCredentials:    credentials,
		ReplayWindow:         window,
		ReplayCapacity:       capacity,
		RequestTimeout:       timeout,
		MaxInFlightPerCaller: perCaller,
		MaxInFlightPerNode:   perNode,
		MaxInFlight:          total,
		AdmissionWait:        wait,
	}, nil
}

// resolveAdmissionLimit parses one admission limit, applying the default when the
// variable is unset.
//
// A value below one is refused rather than clamped. A zero limit refuses every
// request, and a Server that refuses everything looks like a Server that is
// working and denying, which is the most expensive kind of misconfiguration to
// diagnose.
func resolveAdmissionLimit(name, value string, fallback int) (int, error) {
	if value == "" {
		return fallback, nil
	}
	limit, err := strconv.Atoi(value)
	if err != nil {
		return 0, fmt.Errorf("%s %q is not a whole number", name, value)
	}
	if limit < 1 {
		return 0, fmt.Errorf("%s is %d, want at least 1", name, limit)
	}
	return limit, nil
}

// resolveAdmissionWait parses the admission wait in milliseconds.
//
// The unit is milliseconds rather than seconds because the useful range is a
// fraction of a second: the wait absorbs a burst, it does not queue work. A
// seconds-based variable would make the smallest useful value one second, which is
// already a queue.
func resolveAdmissionWait(value string) (time.Duration, error) {
	if value == "" {
		return DefaultAdmissionWait, nil
	}
	milliseconds, err := strconv.Atoi(value)
	if err != nil {
		return 0, fmt.Errorf("CONNECTOR_SERVER_ADMISSION_WAIT_MS %q is not a whole number of milliseconds", value)
	}
	if milliseconds < 0 {
		return 0, fmt.Errorf("CONNECTOR_SERVER_ADMISSION_WAIT_MS is %d, want zero or more", milliseconds)
	}
	wait := time.Duration(milliseconds) * time.Millisecond
	if wait > MaxAdmissionWait {
		return 0, fmt.Errorf("CONNECTOR_SERVER_ADMISSION_WAIT_MS is %d, want at most %d", milliseconds, int(MaxAdmissionWait/time.Millisecond))
	}
	return wait, nil
}

// loadClientCredentials reads the client credential set.
//
// The file is the only source. A second source would be a second answer to "which
// secret verifies this proof", and the precedence between them would be whatever
// the code happened to do first. A missing file is a startup failure rather than an
// empty set, because an empty set refuses every caller and looks like a working
// Server that denies everything.
func loadClientCredentials(lookup func(string) string) (*security.CredentialSet, error) {
	path := lookup("CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE")
	if path == "" {
		return nil, fmt.Errorf("CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE is empty; the Server has no client credential to verify proofs with")
	}
	if !filepath.IsAbs(path) {
		return nil, fmt.Errorf("CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE %q is relative; a relative path resolves differently per launch", path)
	}

	info, err := os.Stat(path)
	if err != nil {
		return nil, fmt.Errorf("stat CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE %q: %w", path, err)
	}
	if info.IsDir() {
		return nil, fmt.Errorf("CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE %q is a directory", path)
	}
	if info.Size() > security.MaxCredentialFileBytes {
		return nil, fmt.Errorf("CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE %q is %d bytes, want at most %d", path, info.Size(), security.MaxCredentialFileBytes)
	}

	content, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE %q: %w", path, err)
	}
	credentials, err := security.ParseCredentialSet(content)
	if err != nil {
		return nil, fmt.Errorf("CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE %q: %w", path, err)
	}
	return credentials, nil
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

// resolveReplayWindow parses the client replay window in seconds.
//
// A zero or negative value is refused rather than clamped, because a clamped window
// would silently accept a proof the operator meant to refuse.
func resolveReplayWindow(value string) (time.Duration, error) {
	if value == "" {
		return security.DefaultReplayWindow, nil
	}
	seconds, err := strconv.Atoi(value)
	if err != nil {
		return 0, fmt.Errorf("CONNECTOR_SERVER_REPLAY_WINDOW_SECONDS %q is not a whole number of seconds", value)
	}
	if seconds < 1 {
		return 0, fmt.Errorf("CONNECTOR_SERVER_REPLAY_WINDOW_SECONDS is %d, want at least 1", seconds)
	}
	window := time.Duration(seconds) * time.Second
	if window > security.MaxReplayWindow {
		return 0, fmt.Errorf("CONNECTOR_SERVER_REPLAY_WINDOW_SECONDS is %d, want at most %d", seconds, int(security.MaxReplayWindow/time.Second))
	}
	return window, nil
}

// resolveReplayCapacity parses the client replay cache capacity.
func resolveReplayCapacity(value string) (int, error) {
	if value == "" {
		return security.DefaultReplayCapacity, nil
	}
	capacity, err := strconv.Atoi(value)
	if err != nil {
		return 0, fmt.Errorf("CONNECTOR_SERVER_REPLAY_CAPACITY %q is not a whole number", value)
	}
	if capacity < 1 {
		return 0, fmt.Errorf("CONNECTOR_SERVER_REPLAY_CAPACITY is %d, want at least 1", capacity)
	}
	return capacity, nil
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
// The tunnel token is replaced by its redacted form and the client credential set is
// reported by its public key identifiers only. The method exists so a caller never
// has to decide field by field what may be printed: the decision is made once, here.
func (c Config) Redacted() string {
	keyIDs := "<none>"
	if c.ClientCredentials != nil {
		keyIDs = strings.Join(c.ClientCredentials.KeyIDs(), ",")
		if keyIDs == "" {
			keyIDs = "<empty>"
		}
	}
	return fmt.Sprintf("listen=%s tls=%t tunnel_token=%s client_key_ids=%s replay_window=%s replay_capacity=%d request_timeout=%s",
		c.Listen, c.TLSEnabled(), c.TunnelToken.Redacted(), keyIDs, c.ReplayWindow, c.ReplayCapacity, c.RequestTimeout)
}

// String renders the configuration with every secret redacted, so a Config that
// is printed by accident does not leak one.
func (c Config) String() string {
	return c.Redacted()
}
