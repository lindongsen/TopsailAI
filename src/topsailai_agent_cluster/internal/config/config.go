// Package config loads process-bound Agent Cluster configuration.
package config

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// AdapterConfig describes one Endpoint-local provider adapter.
type AdapterConfig struct {
	AdapterID    string                         `json:"adapter_id"`
	ProviderType string                         `json:"provider_type"`
	Command      string                         `json:"command"`
	Args         []string                       `json:"args"`
	TimeoutMS    int64                          `json:"timeout_ms"`
	Capabilities *protocol.CapabilityDescriptor `json:"capabilities,omitempty"`
}

// Config contains configuration shared by the command entry points.
type Config struct {
	Role                 string
	LogOutput            string
	LogPath              string
	LogMaxSize           int
	LogBackups           int
	LogMaxAge            int
	ListenAddress        string
	APIListenAddress     string
	ChannelListenAddress string
	DatabasePath         string
	AuthToken            string
	AuthScopes           []string
	CommandAllowlistFile string
	ChannelAddress        string
	ChannelDirection      string
	EndpointChannelListen string
	EndpointChannelAddr   string
	EndpointDialAddresses map[string]string
	ServerName            string
	EndpointID            string
	InstanceID            string
	TLSCAFile             string
	TLSCertificateFile    string
	TLSKeyFile            string
	TLSRevokedSerialsFile string
	Adapters              []AdapterConfig
}

// Channel direction values. The direction names which side dials, so a
// deployment can match whichever network path is actually reachable.
const (
	// DirectionEndpointInitiated means the Endpoint dials the Server.
	DirectionEndpointInitiated = "endpoint-initiated"
	// DirectionServerInitiated means the Server dials the Endpoint.
	DirectionServerInitiated = "server-initiated"
)

// Defaults returns safe defaults for a command role.
func Defaults(role string) Config {
	return Config{Role: role, LogOutput: "stderr", LogMaxSize: 100, LogBackups: 10, LogMaxAge: 30, ListenAddress: ":8080", APIListenAddress: ":8080", ChannelListenAddress: ":8443", DatabasePath: ".tmp/server.sqlite", AuthToken: "development-token", InstanceID: "default", ChannelDirection: DirectionEndpointInitiated, ServerName: "agent-cluster-server"}
}

// Load parses command-line flags and applies environment configuration.
func Load(args []string, role string) (Config, error) {
	cfg := Defaults(role)
	if value := os.Getenv("AGENT_CLUSTER_LISTEN_ADDRESS"); value != "" {
		cfg.ListenAddress = value
		cfg.APIListenAddress = value
	}
	if value := os.Getenv("AGENT_CLUSTER_API_LISTEN_ADDR"); value != "" {
		cfg.APIListenAddress = value
	}
	if value := os.Getenv("AGENT_CLUSTER_CHANNEL_LISTEN_ADDR"); value != "" {
		cfg.ChannelListenAddress = value
	}
	if value := os.Getenv("AGENT_CLUSTER_DATABASE_PATH"); value != "" {
		cfg.DatabasePath = value
	}
	if value := os.Getenv("AGENT_CLUSTER_AUTH_TOKEN"); value != "" {
		cfg.AuthToken = value
	}
	if value := os.Getenv("AGENT_CLUSTER_AUTH_SCOPES"); value != "" {
		cfg.AuthScopes = splitList(value)
	}
	if value := os.Getenv("AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE"); value != "" {
		cfg.CommandAllowlistFile = value
	}
	if value := os.Getenv("AGENT_CLUSTER_CHANNEL_ADDRESS"); value != "" {
		cfg.ChannelAddress = value
	}
	if value := os.Getenv("AGENT_CLUSTER_CHANNEL_DIRECTION"); value != "" {
		cfg.ChannelDirection = value
	}
	if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_CHANNEL_LISTEN_ADDR"); value != "" {
		cfg.EndpointChannelListen = value
	}
	if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS"); value != "" {
		cfg.EndpointChannelAddr = value
	}
	if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_DIAL_ADDRESSES"); value != "" {
		addresses, err := ParseDialAddresses(value)
		if err != nil {
			return Config{}, err
		}
		cfg.EndpointDialAddresses = addresses
	}
	if value := os.Getenv("AGENT_CLUSTER_SERVER_NAME"); value != "" {
		cfg.ServerName = value
	}
	if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_ID"); value != "" {
		cfg.EndpointID = value
	}
	if value := os.Getenv("AGENT_CLUSTER_INSTANCE_ID"); value != "" {
		cfg.InstanceID = value
	}
	if value := os.Getenv("AGENT_CLUSTER_TLS_CA_FILE"); value != "" {
		cfg.TLSCAFile = value
	}
	if value := os.Getenv("AGENT_CLUSTER_TLS_CERTIFICATE_FILE"); value != "" {
		cfg.TLSCertificateFile = value
	}
	if value := os.Getenv("AGENT_CLUSTER_TLS_KEY_FILE"); value != "" {
		cfg.TLSKeyFile = value
	}
	if value := os.Getenv("AGENT_CLUSTER_TLS_REVOKED_SERIALS_FILE"); value != "" {
		cfg.TLSRevokedSerialsFile = value
	}
	if value := os.Getenv("AGENT_CLUSTER_ADAPTERS"); value != "" {
		adapters, err := ParseAdapters(value)
		if err != nil {
			return Config{}, err
		}
		cfg.Adapters = adapters
	}
	if value := os.Getenv("AGENT_CLUSTER_LOG_OUTPUT"); value != "" {
		cfg.LogOutput = value
	}
	if value := os.Getenv("AGENT_CLUSTER_LOG_PATH"); value != "" {
		cfg.LogPath = value
	}
	applyIntEnv("AGENT_CLUSTER_LOG_MAX_SIZE_MB", &cfg.LogMaxSize)
	applyIntEnv("AGENT_CLUSTER_LOG_MAX_BACKUPS", &cfg.LogBackups)
	applyIntEnv("AGENT_CLUSTER_LOG_MAX_AGE_DAYS", &cfg.LogMaxAge)

	flags := flag.NewFlagSet(role, flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	flags.StringVar(&cfg.APIListenAddress, "api-listen-addr", cfg.APIListenAddress, "Bearer-authenticated API listen address")
	flags.StringVar(&cfg.ChannelListenAddress, "channel-listen-addr", cfg.ChannelListenAddress, "mTLS channel listen address")
	flags.StringVar(&cfg.ListenAddress, "listen-address", cfg.ListenAddress, "deprecated API listen address")
	flags.StringVar(&cfg.DatabasePath, "database-path", cfg.DatabasePath, "SQLite database path")
	flags.StringVar(&cfg.AuthToken, "auth-token", cfg.AuthToken, "pre-provisioned bearer token")
	flags.Func("auth-scopes", "comma-separated operator scopes granted to the bearer token", func(value string) error {
		cfg.AuthScopes = splitList(value)
		return nil
	})
	flags.StringVar(&cfg.CommandAllowlistFile, "command-allowlist-file", cfg.CommandAllowlistFile, "Endpoint-global command allowlist file")
	flags.StringVar(&cfg.ChannelAddress, "channel-address", cfg.ChannelAddress, "Endpoint WSS address")
	flags.StringVar(&cfg.ChannelDirection, "channel-direction", cfg.ChannelDirection, "channel direction: endpoint-initiated or server-initiated")
	flags.StringVar(&cfg.EndpointChannelListen, "endpoint-channel-listen-addr", cfg.EndpointChannelListen, "Endpoint mTLS channel listen address for server-initiated connections")
	flags.Func("endpoint-dial-addresses", "comma-separated endpoint_id=wss://address pairs the Server dials", func(value string) error {
		addresses, err := ParseDialAddresses(value)
		if err != nil {
			return err
		}
		cfg.EndpointDialAddresses = addresses
		return nil
	})
	flags.StringVar(&cfg.EndpointChannelAddr, "endpoint-channel-address", cfg.EndpointChannelAddr, "Endpoint WSS address the Server dials")
	flags.StringVar(&cfg.ServerName, "server-name", cfg.ServerName, "expected Server certificate identity when the Endpoint accepts a connection")
	flags.StringVar(&cfg.EndpointID, "endpoint-id", cfg.EndpointID, "Endpoint identity")
	flags.StringVar(&cfg.InstanceID, "instance-id", cfg.InstanceID, "Endpoint instance identity")
	flags.StringVar(&cfg.TLSCAFile, "tls-ca-file", cfg.TLSCAFile, "TLS CA file")
	flags.StringVar(&cfg.TLSCertificateFile, "tls-certificate-file", cfg.TLSCertificateFile, "TLS certificate file")
	flags.StringVar(&cfg.TLSKeyFile, "tls-key-file", cfg.TLSKeyFile, "TLS key file")
	flags.StringVar(&cfg.TLSRevokedSerialsFile, "tls-revoked-serials-file", cfg.TLSRevokedSerialsFile, "revoked certificate serial file")
	flags.StringVar(&cfg.LogOutput, "log-output", cfg.LogOutput, "log destination: stderr or file")
	flags.StringVar(&cfg.LogPath, "log-path", cfg.LogPath, "log file path when file output is selected")
	flags.IntVar(&cfg.LogMaxSize, "log-max-size-mb", cfg.LogMaxSize, "maximum log file size in megabytes")
	flags.IntVar(&cfg.LogBackups, "log-max-backups", cfg.LogBackups, "maximum retained log backups")
	flags.IntVar(&cfg.LogMaxAge, "log-max-age-days", cfg.LogMaxAge, "maximum log backup age in days")
	if err := flags.Parse(args); err != nil {
		return Config{}, err
	}
	if cfg.APIListenAddress == "" {
		cfg.APIListenAddress = cfg.ListenAddress
	}

	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

// ParseDialAddresses parses endpoint_id=wss://address pairs the Server dials in
// the server-initiated direction. The address is operator configuration, never a
// remote payload, so a command can never choose where the Server connects.
func ParseDialAddresses(value string) (map[string]string, error) {
	result := make(map[string]string)
	for _, pair := range splitList(value) {
		endpointID, address, found := strings.Cut(pair, "=")
		endpointID = strings.TrimSpace(endpointID)
		address = strings.TrimSpace(address)
		if !found || endpointID == "" || address == "" {
			return nil, fmt.Errorf("dial address %q must be endpoint_id=address", pair)
		}
		if _, ok := result[endpointID]; ok {
			return nil, fmt.Errorf("dial address for endpoint %q is duplicated", endpointID)
		}
		result[endpointID] = address
	}
	return result, nil
}

// ParseAdapters validates the JSON adapter configuration supplied at the process boundary.
func ParseAdapters(value string) ([]AdapterConfig, error) {
	var adapters []AdapterConfig
	if err := json.Unmarshal([]byte(value), &adapters); err != nil {
		return nil, fmt.Errorf("parse AGENT_CLUSTER_ADAPTERS: %w", err)
	}
	if len(adapters) == 0 {
		return nil, fmt.Errorf("AGENT_CLUSTER_ADAPTERS must contain at least one adapter")
	}
	seen := make(map[string]struct{}, len(adapters))
	for i := range adapters {
		item := &adapters[i]
		if item.AdapterID == "" || item.ProviderType == "" || item.Command == "" {
			return nil, fmt.Errorf("adapter %d requires adapter_id, provider_type, and command", i)
		}
		if _, ok := seen[item.AdapterID]; ok {
			return nil, fmt.Errorf("adapter ID %q is duplicated", item.AdapterID)
		}
		seen[item.AdapterID] = struct{}{}
		if !filepath.IsAbs(item.Command) {
			return nil, fmt.Errorf("adapter %q command must be an absolute path", item.AdapterID)
		}
		if item.TimeoutMS <= 0 {
			return nil, fmt.Errorf("adapter %q timeout_ms must be positive", item.AdapterID)
		}
	}
	return adapters, nil
}

// Validate checks configuration values before service initialization.
func (c Config) Validate() error {
	if c.LogOutput != "stderr" && c.LogOutput != "file" {
		return fmt.Errorf("invalid log output %q", c.LogOutput)
	}
	if c.LogOutput == "file" && c.LogPath == "" {
		return fmt.Errorf("log path is required for file output")
	}
	if c.LogMaxSize <= 0 || c.LogBackups < 0 || c.LogMaxAge < 0 {
		return fmt.Errorf("log rotation limits must be positive or zero where allowed")
	}
	switch c.ChannelDirection {
	case DirectionEndpointInitiated, DirectionServerInitiated:
	default:
		return fmt.Errorf("invalid channel direction %q", c.ChannelDirection)
	}
	for _, scope := range c.AuthScopes {
		if !knownScope(scope) {
			return fmt.Errorf("unknown operator scope %q", scope)
		}
	}
	return nil
}

// knownScope reports whether the scope is one of the defined operator scopes.
// An unknown scope is rejected at startup rather than silently ignored, because
// a typo would otherwise grant less authority than the operator intended.
func knownScope(scope string) bool {
	switch scope {
	case "view", "read_output", "send_message", "control", "endpoint_admin":
		return true
	}
	return false
}

// splitList splits a comma-separated value and drops empty entries.
func splitList(value string) []string {
	parts := strings.Split(value, ",")
	result := make([]string, 0, len(parts))
	for _, part := range parts {
		trimmed := strings.TrimSpace(part)
		if trimmed != "" {
			result = append(result, trimmed)
		}
	}
	return result
}

func applyIntEnv(name string, target *int) {
	value := os.Getenv(name)
	if value == "" {
		return
	}
	parsed, err := strconv.Atoi(value)
	if err == nil {
		*target = parsed
	}
}
