package node

import (
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"topsailai_connector/internal/security"
)

// DefaultConfigDirectoryName is the directory under the platform config
// directory where the Node keeps its identity file and its policy file.
const DefaultConfigDirectoryName = "topsailai-connector"

// Config is the Node's startup configuration.
//
// It is built once at the process boundary and passed down as a value. Nothing
// below the boundary reads the environment, because a function that reads a
// process-wide variable hides a dependency and cannot be tested without mutating
// global state.
type Config struct {
	// ServerURL is the channel address the Node dials.
	ServerURL string
	// TunnelToken is the secret the Node presents in hello. It gates the
	// channel and grants nothing else.
	TunnelToken security.Secret
	// ConfigDir holds the identity file and, by default, the policy file.
	ConfigDir string
	// PolicyPath is the policy file the Node loads at startup.
	PolicyPath string
}

// LoadConfig builds a Config from a lookup function.
//
// The lookup function is a parameter rather than a direct os.Getenv call so a
// test can supply a fixed environment without touching the process. Every
// failure is a startup failure: a Node that starts with a missing secret or a
// missing policy is a Node whose operator believes it is serving something it is
// not.
func LoadConfig(lookup func(string) string) (Config, error) {
	if lookup == nil {
		return Config{}, fmt.Errorf("environment lookup is nil")
	}

	serverURL := lookup("CONNECTOR_NODE_SERVER_URL")
	if err := validateServerURL(serverURL); err != nil {
		return Config{}, err
	}

	tunnelToken := security.Secret(lookup("CONNECTOR_NODE_TUNNEL_TOKEN"))
	if err := tunnelToken.Validate("CONNECTOR_NODE_TUNNEL_TOKEN"); err != nil {
		return Config{}, err
	}

	configDir, err := resolveConfigDir(lookup("CONNECTOR_NODE_CONFIG_DIR"))
	if err != nil {
		return Config{}, err
	}

	policyPath := lookup("CONNECTOR_NODE_POLICY_FILE")
	if policyPath == "" {
		policyPath = filepath.Join(configDir, "policy.yaml")
	}
	if !filepath.IsAbs(policyPath) {
		return Config{}, fmt.Errorf("CONNECTOR_NODE_POLICY_FILE %q is relative; a relative path resolves differently per launch", policyPath)
	}

	return Config{
		ServerURL:   serverURL,
		TunnelToken: tunnelToken,
		ConfigDir:   configDir,
		PolicyPath:  policyPath,
	}, nil
}

// ResolveConfigDir returns the absolute config directory from a lookup function,
// creating it when it does not exist.
//
// It exists because two subcommands need the config directory and nothing else.
// `id` prints the identity pair and `regenerate` replaces it; neither dials the
// Server, so neither may require a dial target or a tunnel token. Loading the
// whole configuration for them made the documented first-run order impossible:
// the operator is told to run `id` before the tunnel token exists, and
// LoadConfig refuses that order.
//
// This is deliberately narrower than LoadConfig, not a relaxation of it. The
// dial path still calls LoadConfig and still refuses to start without a secret,
// because a Node that started without one would be a Node whose operator
// believes it is serving something it is not.
func ResolveConfigDir(lookup func(string) string) (string, error) {
	if lookup == nil {
		return "", fmt.Errorf("environment lookup is nil")
	}
	return resolveConfigDir(lookup("CONNECTOR_NODE_CONFIG_DIR"))
}

// validateServerURL checks that the channel address is a WebSocket URL with a
// host. A plain `ws://` address is accepted because a Node on a loopback network
// has nothing to protect, but the scheme is checked so a typo such as `http://`
// fails at startup instead of at the first dial.
func validateServerURL(value string) error {
	if value == "" {
		return fmt.Errorf("CONNECTOR_NODE_SERVER_URL is empty; the Node has no address to dial")
	}
	parsed, err := url.Parse(value)
	if err != nil {
		return fmt.Errorf("CONNECTOR_NODE_SERVER_URL %q is not a URL: %w", value, err)
	}
	if parsed.Scheme != "wss" && parsed.Scheme != "ws" {
		return fmt.Errorf("CONNECTOR_NODE_SERVER_URL %q has scheme %q, want wss or ws", value, parsed.Scheme)
	}
	if parsed.Host == "" {
		return fmt.Errorf("CONNECTOR_NODE_SERVER_URL %q has no host", value)
	}
	return nil
}

// resolveConfigDir returns the absolute config directory, creating it when it
// does not exist.
//
// The directory is created with 0700 because it holds the node token. An
// existing directory is not re-permissioned: changing the mode of a directory the
// operator created is a surprise, and the identity file has its own check.
func resolveConfigDir(value string) (string, error) {
	if value == "" {
		base, err := os.UserConfigDir()
		if err != nil {
			return "", fmt.Errorf("resolve the platform config directory: %w", err)
		}
		value = filepath.Join(base, DefaultConfigDirectoryName)
	}
	if !filepath.IsAbs(value) {
		return "", fmt.Errorf("CONNECTOR_NODE_CONFIG_DIR %q is relative; a relative path resolves differently per launch", value)
	}

	info, err := os.Stat(value)
	if err == nil {
		if !info.IsDir() {
			return "", fmt.Errorf("CONNECTOR_NODE_CONFIG_DIR %q is not a directory", value)
		}
		return value, nil
	}
	if !os.IsNotExist(err) {
		return "", fmt.Errorf("stat CONNECTOR_NODE_CONFIG_DIR %q: %w", value, err)
	}
	if err := os.MkdirAll(value, 0o700); err != nil {
		return "", fmt.Errorf("create CONNECTOR_NODE_CONFIG_DIR %q: %w", value, err)
	}
	return value, nil
}

// Redacted renders the configuration for a log line.
//
// The tunnel token is replaced by its redacted form and the policy path is kept,
// because a path is not a credential. The method exists so a caller never has to
// decide field by field what may be printed: the decision is made once, here.
func (c Config) Redacted() string {
	return fmt.Sprintf("server=%s tunnel_token=%s config_dir=%s policy=%s",
		c.ServerURL, c.TunnelToken.Redacted(), c.ConfigDir, c.PolicyPath)
}

// String renders the configuration with the secret redacted, so a Config that is
// printed by accident does not leak the tunnel token.
func (c Config) String() string {
	return c.Redacted()
}

// trimLineTerminator removes exactly one trailing line terminator.
//
// It is used when reading a file the Node wrote itself, which ends with a
// newline. It is deliberately not a general trim: trimming arbitrary whitespace
// would hide a hand-edited file, which is the case the parser refuses on purpose.
func trimLineTerminator(value string) string {
	value = strings.TrimSuffix(value, "\n")
	return strings.TrimSuffix(value, "\r")
}
