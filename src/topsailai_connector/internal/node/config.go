package node

import (
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"topsailai_connector/internal/node/embedded"
	"topsailai_connector/internal/security"
)

// DefaultConfigDirectoryName is the directory under the platform config directory
// where the Node keeps its identity file, its credential file and its policy file.
const DefaultConfigDirectoryName = "topsailai-connector"

// Config is the Node's startup configuration.
//
// It is built once at the process boundary and passed down as a value. Nothing below
// the boundary reads the environment, because a function that reads a process-wide
// variable hides a dependency and cannot be tested without mutating global state.
type Config struct {
	// ServerURL is the channel address the Node dials.
	ServerURL string
	// TunnelToken is the secret the Node presents in hello. It gates the channel and
	// grants nothing else.
	TunnelToken security.Secret
	// ConfigDir holds the identity file, the credential file and, by default, the
	// policy file.
	ConfigDir string
	// CredentialsPath is the credential file the Node verifies proofs with.
	CredentialsPath string
	// PolicyPath is the policy file the Node loads at startup. It is empty when the
	// policy was compiled into the binary, because an embedded policy has no file to
	// name.
	PolicyPath string
	// PolicyBytes is the policy document compiled into the binary. It is nil for a
	// normal build, and a nil value means "read PolicyPath instead".
	//
	// The two fields are mutually exclusive by construction: LoadConfig sets
	// PolicyBytes only when it did not set PolicyPath. A Config carrying both would be
	// a Config with two policies, and nothing would say which one wins.
	PolicyBytes []byte
	// ReplayWindow is how far a Node proof timestamp may differ from the Node's clock.
	ReplayWindow time.Duration
	// ReplayCapacity bounds the number of unexpired nonces the Node records.
	ReplayCapacity int
	// Stateless reports that this Node must not create a directory or a file. The
	// identity and the credentials are then held in memory only, and ConfigDir and
	// CredentialsPath are empty because there is nothing to name.
	//
	// The mode exists for a machine whose filesystem is read-only. It is off by
	// default, and a Node that does not set it behaves exactly as it did before the
	// mode existed.
	Stateless bool
}

// LoadConfig builds a Config from a lookup function.
//
// The lookup function is a parameter rather than a direct os.Getenv call so a test can
// supply a fixed environment without touching the process. Every failure is a startup
// failure: a Node that starts with a missing secret or a missing policy is a Node
// whose operator believes it is serving something it is not.
//
// # Precedence
//
// The environment wins over a value compiled into the binary, field by field. That
// order is deliberate: an embedded value is a default chosen by whoever packaged the
// binary, and the operator running it must be able to point the same binary at a
// different Server or a different token without a rebuild. A binary that ignored the
// environment would be a binary whose baked value could only be changed by
// repackaging, which is the failure mode a self-contained build is most likely to
// create.
//
// The policy is the exception, and it is an exception because it cannot be overridden
// safely. An embedded policy is a whole document, so an environment variable naming a
// file would silently replace every scope and every grant with a different set. A
// build that embedded a policy therefore refuses CONNECTOR_NODE_POLICY_FILE rather
// than letting the two disagree, and the operator who needs a different policy uses a
// build that embedded none.
func LoadConfig(lookup func(string) string) (Config, error) {
	if lookup == nil {
		return Config{}, fmt.Errorf("environment lookup is nil")
	}

	serverURL := lookup("CONNECTOR_NODE_SERVER_URL")
	if serverURL == "" {
		serverURL = embedded.ServerURL
	}
	if err := validateServerURL(serverURL); err != nil {
		return Config{}, err
	}

	tunnelToken := security.Secret(lookup("CONNECTOR_NODE_TUNNEL_TOKEN"))
	if tunnelToken == "" {
		tunnelToken = security.Secret(embedded.TunnelToken)
	}
	if err := tunnelToken.Validate("CONNECTOR_NODE_TUNNEL_TOKEN"); err != nil {
		return Config{}, err
	}

	stateless, err := resolveStateless(lookup("CONNECTOR_NODE_STATELESS"))
	if err != nil {
		return Config{}, err
	}

	// A stateless Node has no config directory and no credential file: writing
	// nothing is the whole point of the mode. The two paths are therefore left
	// empty rather than resolved, and every consumer already treats an empty path
	// as "this Node has none": the dialer skips the file watcher, the deny list
	// skips an empty entry, and the config-overlap check is disabled.
	var configDir, credentialsPath string
	if !stateless {
		configDir, err = resolveConfigDir(lookup("CONNECTOR_NODE_CONFIG_DIR"))
		if err != nil {
			return Config{}, err
		}
		credentialsPath, err = resolveCredentialsPath(lookup("CONNECTOR_NODE_CREDENTIALS_FILE"), configDir)
		if err != nil {
			return Config{}, err
		}
	}

	window, err := resolveReplayWindow(lookup("CONNECTOR_NODE_REPLAY_WINDOW_SECONDS"))
	if err != nil {
		return Config{}, err
	}

	capacity, err := resolveReplayCapacity(lookup("CONNECTOR_NODE_REPLAY_CAPACITY"))
	if err != nil {
		return Config{}, err
	}

	policyPath, policyBytes, err := resolvePolicySource(lookup, configDir)
	if err != nil {
		return Config{}, err
	}

	return Config{
		ServerURL:       serverURL,
		TunnelToken:     tunnelToken,
		ConfigDir:       configDir,
		CredentialsPath: credentialsPath,
		PolicyPath:      policyPath,
		PolicyBytes:     policyBytes,
		ReplayWindow:    window,
		ReplayCapacity:  capacity,
		Stateless:       stateless,
	}, nil
}

// resolveStateless parses the stateless-mode switch.
//
// The value is validated strictly: `1` enables the mode, an empty value or `0`
// disables it, and anything else is refused rather than read as "off". A mode that
// decides whether the process may write to disk is a mode whose state must be
// statable, and a switch that silently accepts a spelling it does not understand is
// a switch nobody can state. This follows the PACKAGE_ALLOW_FILESYSTEM_ROOT
// precedent.
//
// An empty value falls back to the mode the build embedded, so an artifact built
// for a read-only machine runs stateless without the recipient exporting anything.
// An explicit value wins, which is what lets the same binary be run file-backed
// with CONNECTOR_NODE_STATELESS=0. The fallback lives here rather than at each call
// site because three callers ask the same question, and three copies of a
// precedence rule is how they drift apart.
func resolveStateless(value string) (bool, error) {
	switch value {
	case "":
		return embedded.StatelessDefault()
	case "0":
		return false, nil
	case "1":
		return true, nil
	default:
		return false, fmt.Errorf("CONNECTOR_NODE_STATELESS is %q, want 1, 0 or empty", value)
	}
}

// resolvePolicySource decides where the policy comes from: the document compiled
// into the binary, or a file. Exactly one of the two results is set.
//
// It is a separate function because two callers need the same decision. The dial
// path needs it to build a Config, and `scope list` needs it to read the policy
// without dialling. A second copy of the rule would be a second definition of
// which policy is in force, and the two would eventually disagree about a build
// that embedded one.
//
// The refusal of CONNECTOR_NODE_POLICY_FILE on an embedded build lives here rather
// than in either caller, so a build that carries a policy cannot be made to read a
// different one through a path that forgot the check.
func resolvePolicySource(lookup func(string) string, configDir string) (string, []byte, error) {
	policyBytes, err := embedded.Policy()
	if err != nil {
		return "", nil, err
	}

	policyPath := lookup("CONNECTOR_NODE_POLICY_FILE")
	if policyBytes != nil {
		if policyPath != "" {
			return "", nil, fmt.Errorf("CONNECTOR_NODE_POLICY_FILE is set but this build compiled its policy in; a build that carries a policy cannot also read one from a file, because the two would disagree about every scope and every grant")
		}
		return "", policyBytes, nil
	}

	if policyPath == "" {
		if configDir == "" {
			return "", nil, fmt.Errorf("no policy is in force: this build compiled none in and CONNECTOR_NODE_POLICY_FILE is unset, and a stateless Node has no config directory to hold a default policy.yaml; set CONNECTOR_NODE_POLICY_FILE to an absolute path or use a build that compiled its policy in")
		}
		policyPath = filepath.Join(configDir, "policy.yaml")
	}
	if !filepath.IsAbs(policyPath) {
		return "", nil, fmt.Errorf("CONNECTOR_NODE_POLICY_FILE %q is relative; a relative path resolves differently per launch", policyPath)
	}
	return policyPath, nil, nil
}

// ResolveConfigDir returns the absolute config directory from a lookup function,
// creating it when it does not exist.
//
// It exists because two subcommands need the config directory and nothing else. `id`
// prints the node id and `regenerate` replaces it; neither dials the Server, so
// neither may require a dial target or a tunnel token. Loading the whole configuration
// for them made the documented first-run order impossible: the operator is told to run
// `id` before the tunnel token exists, and LoadConfig refuses that order.
//
// This is deliberately narrower than LoadConfig, not a relaxation of it. The dial path
// still calls LoadConfig and still refuses to start without a secret, because a Node
// that started without one would be a Node whose operator believes it is serving
// something it is not.
func ResolveConfigDir(lookup func(string) string) (string, error) {
	if lookup == nil {
		return "", fmt.Errorf("environment lookup is nil")
	}
	return resolveConfigDir(lookup("CONNECTOR_NODE_CONFIG_DIR"))
}

// StatelessRequested reports whether the environment asks for stateless mode.
//
// It exists so a subcommand that would write a file can refuse before it resolves a
// config directory, because resolving one creates it. A subcommand that called
// ResolveConfigDir first and then discovered the mode would have created the very
// directory the mode exists to avoid, and the refusal would arrive after the damage.
func StatelessRequested(lookup func(string) string) (bool, error) {
	if lookup == nil {
		return false, fmt.Errorf("environment lookup is nil")
	}
	return resolveStateless(lookup("CONNECTOR_NODE_STATELESS"))
}

// resolveCredentialsPath returns the absolute credential file path.
//
// The default lives inside the config directory, because the file is the Node's own
// and the Node creates it on first start. A path the operator names must be absolute,
// because a relative path resolves differently per launch and a credential file that
// moves with the working directory is a credential file the Node may not find.
func resolveCredentialsPath(value string, configDir string) (string, error) {
	if value == "" {
		return CredentialsPath(configDir), nil
	}
	if !filepath.IsAbs(value) {
		return "", fmt.Errorf("CONNECTOR_NODE_CREDENTIALS_FILE %q is relative; a relative path resolves differently per launch", value)
	}
	return value, nil
}

// validateServerURL checks that the channel address is a WebSocket URL with a host. A
// plain `ws://` address is accepted because a Node on a loopback network has nothing
// to protect, but the scheme is checked so a typo such as `http://` fails at startup
// instead of at the first dial.
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

// resolveConfigDir returns the absolute config directory, creating it when it does not
// exist.
//
// The directory is created with 0700 because it holds the credential file. An existing
// directory is not re-permissioned: changing the mode of a directory the operator
// created is a surprise, and each file has its own check.
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

// resolveReplayWindow parses the Node replay window in seconds.
//
// A zero or negative value is refused rather than clamped, because a clamped window
// would silently accept a proof the operator meant to refuse.
func resolveReplayWindow(value string) (time.Duration, error) {
	if value == "" {
		return security.DefaultReplayWindow, nil
	}
	seconds, err := strconv.Atoi(value)
	if err != nil {
		return 0, fmt.Errorf("CONNECTOR_NODE_REPLAY_WINDOW_SECONDS %q is not a whole number of seconds", value)
	}
	if seconds < 1 {
		return 0, fmt.Errorf("CONNECTOR_NODE_REPLAY_WINDOW_SECONDS is %d, want at least 1", seconds)
	}
	window := time.Duration(seconds) * time.Second
	if window > security.MaxReplayWindow {
		return 0, fmt.Errorf("CONNECTOR_NODE_REPLAY_WINDOW_SECONDS is %d, want at most %d", seconds, int(security.MaxReplayWindow/time.Second))
	}
	return window, nil
}

// resolveReplayCapacity parses the Node replay cache capacity.
func resolveReplayCapacity(value string) (int, error) {
	if value == "" {
		return security.DefaultReplayCapacity, nil
	}
	capacity, err := strconv.Atoi(value)
	if err != nil {
		return 0, fmt.Errorf("CONNECTOR_NODE_REPLAY_CAPACITY %q is not a whole number", value)
	}
	if capacity < 1 {
		return 0, fmt.Errorf("CONNECTOR_NODE_REPLAY_CAPACITY is %d, want at least 1", capacity)
	}
	return capacity, nil
}

// Redacted renders the configuration for a log line.
//
// The tunnel token is replaced by its redacted form and the paths are kept, because a
// path is not a credential. The method exists so a caller never has to decide field by
// field what may be printed: the decision is made once, here.
func (c Config) Redacted() string {
	policy := c.PolicyPath
	if c.PolicyBytes != nil {
		// An embedded policy has no path, so the log line says where it came from
		// instead of printing an empty value that reads like a missing configuration.
		policy = "embedded"
	}
	// A stateless Node has no config directory and no credential file, so the two
	// fields are reported as the mode rather than as empty values. An empty
	// config_dir= in a log line reads as a configuration mistake, and the operator
	// would go looking for a directory that the mode exists to avoid creating.
	configDir := c.ConfigDir
	credentials := c.CredentialsPath
	if c.Stateless {
		configDir = "stateless"
		credentials = "stateless"
	}
	return fmt.Sprintf("server=%s tunnel_token=%s config_dir=%s credentials=%s policy=%s replay_window=%s replay_capacity=%d",
		c.ServerURL, c.TunnelToken.Redacted(), configDir, credentials, policy, c.ReplayWindow, c.ReplayCapacity)
}

// String renders the configuration with the secret redacted, so a Config that is
// printed by accident does not leak the tunnel token.
func (c Config) String() string {
	return c.Redacted()
}

// trimLineTerminator removes exactly one trailing line terminator.
//
// It is used when reading a file the Node wrote itself, which ends with a newline. It
// is deliberately not a general trim: trimming arbitrary whitespace would hide a
// hand-edited file, which is the case the parser refuses on purpose.
func trimLineTerminator(value string) string {
	value = strings.TrimSuffix(value, "\n")
	return strings.TrimSuffix(value, "\r")
}
