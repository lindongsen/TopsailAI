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
	"time"

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
	APIListenAddress     string
	ChannelListenAddress string
	DatabasePath         string
	AuthToken            string
	// EndpointExpiry is the Server-owned retention window for offline Endpoint records.
	EndpointExpiry time.Duration
	// CommandRetention is the Server-owned retention window for terminal command
	// records. A command row is the duplicate-detection evidence for its ID and
	// the Endpoint identity that retained command evidence protects, so purging
	// it is what lets an expired Endpoint metadata row be removed.
	CommandRetention time.Duration
	// EndpointDegradedRetention is the Server-owned window a degraded Endpoint is
	// retained before deletion. It is separate from EndpointExpiry because the two
	// answer different questions: EndpointExpiry decides when a disconnected
	// machine stops being usable, and this decides when the record of that machine
	// stops existing. Collapsing them into one window would delete the record at
	// the moment it became degraded, leaving no trace that the machine existed.
	EndpointDegradedRetention time.Duration
	// WriteLivenessBudget bounds how long the Server may keep running while the
	// database refuses every write. A zero value disables the watchdog, which is
	// the right choice only when the operator prefers a blocked Server to a
	// restarted one; a positive value ends the process instead of letting it serve
	// reads while silently discarding every state change.
	WriteLivenessBudget time.Duration
	// WriteLivenessInterval is how often the watchdog probes the database. It is
	// separate from the budget so a short probe interval can detect recovery
	// quickly without shortening the tolerance for a transient lock.
	WriteLivenessInterval time.Duration
	CommandAllowlistFile  string
	// EndpointAccessPolicyDir is the Endpoint-local directory holding one access
	// policy file per caller token. An empty value, or a directory that holds no
	// policy file, permits every caller, which keeps existing deployments
	// working. A directory that holds at least one policy file restricts every
	// caller to the tokens it lists.
	EndpointAccessPolicyDir string
	// ReplaceRequestFile is the Endpoint-local request document that activates one
	// Provider CLI version for one adapter. An empty value disables activation
	// entirely, which is the fail-closed default: an Endpoint that names no request
	// file cannot be asked to swap the program it runs.
	ReplaceRequestFile string
	ChannelAddress     string
	// ChannelAddresses is the ordered list of Server addresses the Endpoint
	// tries in turn. It exists because an Endpoint may be managed by one of
	// several independent Servers: when the first is unreachable the Endpoint
	// moves to the next instead of staying offline forever.
	//
	// Order is the contract. The first reachable address wins, so an operator
	// expresses preference by position rather than by a separate priority field.
	ChannelAddresses      []string
	ChannelDirection      string
	EndpointChannelListen string
	EndpointDialAddresses map[string]string
	// HeartbeatAckTimeout bounds how long one Endpoint heartbeat waits for the
	// Server's acknowledgement. A heartbeat that is not acknowledged is counted
	// as a failure, because sending alone only proves the local socket accepts
	// bytes, which stays true for a Server that has stopped reading.
	HeartbeatAckTimeout time.Duration
	// UnhealthyWindow is how long consecutive unacknowledged heartbeats must
	// accumulate before the Endpoint declares the Server unhealthy and closes the
	// connection. Closing makes the read fail, which lets the existing reconnect
	// path walk the configured address list from the first entry.
	UnhealthyWindow time.Duration
	// TLSSharedCertificate means every Endpoint presents the same Server
	// certificate, so the certificate no longer proves which Endpoint is
	// connecting. It is opt-in because that binding is a real security property.
	TLSSharedCertificate  bool
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
	// DirectionBidirectional means both sides dial at the same time. It covers a
	// deployment where neither side can be assumed reachable from the other, and
	// the two connections converge on the link installed last.
	DirectionBidirectional = "bidirectional"
)

// Defaults returns safe defaults for a command role.
func Defaults(role string) Config {
	databasePath := ".tmp/server.sqlite"
	if role == "agent-cluster-endpoint" {
		databasePath = ".tmp/endpoint.sqlite"
	}
	return Config{Role: role, LogOutput: "stderr", LogMaxSize: 100, LogBackups: 10, LogMaxAge: 30, APIListenAddress: ":8080", ChannelListenAddress: ":8443", DatabasePath: databasePath, AuthToken: "development-token", EndpointExpiry: 24 * time.Hour, CommandRetention: 720 * time.Hour, EndpointDegradedRetention: 720 * time.Hour, WriteLivenessBudget: 2 * time.Minute, WriteLivenessInterval: 5 * time.Second, InstanceID: "default", ChannelDirection: DirectionEndpointInitiated, ServerName: "agent-cluster-server", HeartbeatAckTimeout: 3 * time.Second, UnhealthyWindow: 30 * time.Second}
}

// Load parses command-line flags and applies environment configuration.
func Load(args []string, role string) (Config, error) {
	cfg := Defaults(role)
	serverRole := role == "agent-cluster-server"
	endpointRole := role == "agent-cluster-endpoint"
	genericRole := !serverRole && !endpointRole

	if serverRole || genericRole {
		if value := os.Getenv("AGENT_CLUSTER_SERVER_API_LISTEN_ADDR"); value != "" {
			cfg.APIListenAddress = value
		}
		if value := os.Getenv("AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR"); value != "" {
			cfg.ChannelListenAddress = value
		}
		if value := os.Getenv("AGENT_CLUSTER_SERVER_AUTH_TOKEN"); value != "" {
			cfg.AuthToken = value
		}
		if value := os.Getenv("AGENT_CLUSTER_SERVER_ENDPOINT_EXPIRY"); value != "" {
			parsed, err := time.ParseDuration(value)
			if err != nil {
				return Config{}, fmt.Errorf("parse AGENT_CLUSTER_SERVER_ENDPOINT_EXPIRY: %w", err)
			}
			cfg.EndpointExpiry = parsed
		}
		// The write-liveness bounds are read here rather than inside the watchdog so
		// the process boundary owns configuration, exactly as every other setting
		// does. A malformed duration is rejected at startup instead of silently
		// falling back to the default, because a watchdog that runs with an
		// unintended budget is indistinguishable from one that is disabled.
		if value := os.Getenv("AGENT_CLUSTER_SERVER_WRITE_LIVENESS_BUDGET"); value != "" {
			parsed, err := time.ParseDuration(value)
			if err != nil {
				return Config{}, fmt.Errorf("parse AGENT_CLUSTER_SERVER_WRITE_LIVENESS_BUDGET: %w", err)
			}
			cfg.WriteLivenessBudget = parsed
		}
		if value := os.Getenv("AGENT_CLUSTER_SERVER_WRITE_LIVENESS_INTERVAL"); value != "" {
			parsed, err := time.ParseDuration(value)
			if err != nil {
				return Config{}, fmt.Errorf("parse AGENT_CLUSTER_SERVER_WRITE_LIVENESS_INTERVAL: %w", err)
			}
			cfg.WriteLivenessInterval = parsed
		}
		if value := os.Getenv("AGENT_CLUSTER_SERVER_COMMAND_RETENTION"); value != "" {
			parsed, err := time.ParseDuration(value)
			if err != nil {
				return Config{}, fmt.Errorf("parse AGENT_CLUSTER_SERVER_COMMAND_RETENTION: %w", err)
			}
			cfg.CommandRetention = parsed
		}
		if value := os.Getenv("AGENT_CLUSTER_SERVER_ENDPOINT_DEGRADED_RETENTION"); value != "" {
			parsed, err := time.ParseDuration(value)
			if err != nil {
				return Config{}, fmt.Errorf("parse AGENT_CLUSTER_SERVER_ENDPOINT_DEGRADED_RETENTION: %w", err)
			}
			cfg.EndpointDegradedRetention = parsed
		}
		if value := os.Getenv("AGENT_CLUSTER_SERVER_ENDPOINT_DIAL_ADDRESSES"); value != "" {
			addresses, err := ParseDialAddresses(value)
			if err != nil {
				return Config{}, err
			}
			cfg.EndpointDialAddresses = addresses
		}
		if value := os.Getenv("AGENT_CLUSTER_SERVER_TLS_SHARED_CERTIFICATE"); value != "" {
			parsed, err := strconv.ParseBool(value)
			if err != nil {
				return Config{}, fmt.Errorf("parse AGENT_CLUSTER_SERVER_TLS_SHARED_CERTIFICATE: %w", err)
			}
			cfg.TLSSharedCertificate = parsed
		}
	}
	if endpointRole || genericRole {
		if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_COMMAND_ALLOWLIST_FILE"); value != "" {
			cfg.CommandAllowlistFile = value
		}
		if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_ACCESS_POLICY_DIR"); value != "" {
			cfg.EndpointAccessPolicyDir = value
		}
		if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_REPLACE_REQUEST_FILE"); value != "" {
			cfg.ReplaceRequestFile = value
		}
		if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS"); value != "" {
			cfg.ChannelAddress = value
		}
		if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESSES"); value != "" {
			cfg.ChannelAddresses = splitList(value)
		}
		if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_CHANNEL_LISTEN_ADDR"); value != "" {
			cfg.EndpointChannelListen = value
		}
		if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_HEARTBEAT_ACK_TIMEOUT"); value != "" {
			parsed, err := time.ParseDuration(value)
			if err != nil {
				return Config{}, fmt.Errorf("parse AGENT_CLUSTER_ENDPOINT_HEARTBEAT_ACK_TIMEOUT: %w", err)
			}
			cfg.HeartbeatAckTimeout = parsed
		}
		if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_UNHEALTHY_WINDOW"); value != "" {
			parsed, err := time.ParseDuration(value)
			if err != nil {
				return Config{}, fmt.Errorf("parse AGENT_CLUSTER_ENDPOINT_UNHEALTHY_WINDOW: %w", err)
			}
			cfg.UnhealthyWindow = parsed
		}
		if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_ID"); value != "" {
			cfg.EndpointID = value
		}
		if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_INSTANCE_ID"); value != "" {
			cfg.InstanceID = value
		}
		if value := os.Getenv("AGENT_CLUSTER_ENDPOINT_ADAPTERS"); value != "" {
			adapters, err := ParseAdapters(value)
			if err != nil {
				return Config{}, err
			}
			cfg.Adapters = adapters
		}
	}
	if value := os.Getenv("AGENT_CLUSTER_DATABASE_PATH"); value != "" {
		cfg.DatabasePath = value
	}
	if value := os.Getenv("AGENT_CLUSTER_CHANNEL_DIRECTION"); value != "" {
		cfg.ChannelDirection = value
	}
	if value := os.Getenv("AGENT_CLUSTER_TLS_SERVER_NAME"); value != "" {
		cfg.ServerName = value
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
	flags.StringVar(&cfg.DatabasePath, "database-path", cfg.DatabasePath, "SQLite database path")
	flags.StringVar(&cfg.ChannelDirection, "channel-direction", cfg.ChannelDirection, "channel direction: endpoint-initiated, server-initiated or bidirectional")
	flags.StringVar(&cfg.ServerName, "server-name", cfg.ServerName, "expected Server certificate identity when the Endpoint accepts a connection")
	flags.StringVar(&cfg.TLSCAFile, "tls-ca-file", cfg.TLSCAFile, "TLS CA file")
	flags.StringVar(&cfg.TLSCertificateFile, "tls-certificate-file", cfg.TLSCertificateFile, "TLS certificate file")
	flags.StringVar(&cfg.TLSKeyFile, "tls-key-file", cfg.TLSKeyFile, "TLS key file")
	flags.StringVar(&cfg.TLSRevokedSerialsFile, "tls-revoked-serials-file", cfg.TLSRevokedSerialsFile, "revoked certificate serial file")
	flags.StringVar(&cfg.LogOutput, "log-output", cfg.LogOutput, "log destination: stderr or file")
	flags.StringVar(&cfg.LogPath, "log-path", cfg.LogPath, "log file path when file output is selected")
	flags.IntVar(&cfg.LogMaxSize, "log-max-size-mb", cfg.LogMaxSize, "maximum log file size in megabytes")
	flags.IntVar(&cfg.LogBackups, "log-max-backups", cfg.LogBackups, "maximum retained log backups")
	flags.IntVar(&cfg.LogMaxAge, "log-max-age-days", cfg.LogMaxAge, "maximum log backup age in days")
	if serverRole || genericRole {
		flags.StringVar(&cfg.APIListenAddress, "api-listen-addr", cfg.APIListenAddress, "Bearer-authenticated API listen address")
		flags.StringVar(&cfg.ChannelListenAddress, "channel-listen-addr", cfg.ChannelListenAddress, "mTLS channel listen address")
		flags.StringVar(&cfg.AuthToken, "auth-token", cfg.AuthToken, "pre-provisioned bearer token")
		flags.DurationVar(&cfg.EndpointExpiry, "endpoint-expiry", cfg.EndpointExpiry, "retention window for offline Endpoint records")
		flags.DurationVar(&cfg.CommandRetention, "command-retention", cfg.CommandRetention, "retention window for terminal command records")
		flags.DurationVar(&cfg.EndpointDegradedRetention, "endpoint-degraded-retention", cfg.EndpointDegradedRetention, "retention window for degraded Endpoint records")
		flags.DurationVar(&cfg.WriteLivenessBudget, "write-liveness-budget", cfg.WriteLivenessBudget, "how long the Server may run while the database refuses every write; zero disables the watchdog")
		flags.DurationVar(&cfg.WriteLivenessInterval, "write-liveness-interval", cfg.WriteLivenessInterval, "how often the write-liveness watchdog probes the database")
		flags.Func("endpoint-dial-addresses", "comma-separated endpoint_id=wss://address pairs the Server dials", func(value string) error {
			addresses, err := ParseDialAddresses(value)
			if err != nil {
				return err
			}
			cfg.EndpointDialAddresses = addresses
			return nil
		})
		flags.BoolVar(&cfg.TLSSharedCertificate, "tls-shared-certificate", cfg.TLSSharedCertificate, "every Endpoint presents the same Server certificate; the certificate no longer proves Endpoint identity")
	}
	if endpointRole || genericRole {
		flags.StringVar(&cfg.CommandAllowlistFile, "command-allowlist-file", cfg.CommandAllowlistFile, "Endpoint-global command allowlist file")
		flags.StringVar(&cfg.EndpointAccessPolicyDir, "endpoint-access-policy-dir", cfg.EndpointAccessPolicyDir, "Endpoint-local directory holding one access policy file per caller token")
		flags.StringVar(&cfg.ReplaceRequestFile, "replace-request-file", cfg.ReplaceRequestFile, "Endpoint-local request document that activates one Provider CLI version for one adapter")
		flags.StringVar(&cfg.ChannelAddress, "channel-address", cfg.ChannelAddress, "Server WSS address the Endpoint dials")
		flags.Func("channel-addresses", "ordered Server WSS addresses the Endpoint tries in turn", func(value string) error {
			cfg.ChannelAddresses = splitList(value)
			return nil
		})
		flags.StringVar(&cfg.EndpointChannelListen, "endpoint-channel-listen-addr", cfg.EndpointChannelListen, "Endpoint mTLS channel listen address for server-initiated connections")
		flags.DurationVar(&cfg.HeartbeatAckTimeout, "heartbeat-ack-timeout", cfg.HeartbeatAckTimeout, "how long one Endpoint heartbeat waits for the Server acknowledgement")
		flags.DurationVar(&cfg.UnhealthyWindow, "unhealthy-window", cfg.UnhealthyWindow, "how long consecutive unacknowledged heartbeats accumulate before the Server is declared unhealthy")
		flags.StringVar(&cfg.EndpointID, "endpoint-id", cfg.EndpointID, "Endpoint identity")
		flags.StringVar(&cfg.InstanceID, "instance-id", cfg.InstanceID, "Endpoint instance identity")
	}
	if err := flags.Parse(args); err != nil {
		return Config{}, err
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
		return nil, fmt.Errorf("parse AGENT_CLUSTER_ENDPOINT_ADAPTERS: %w", err)
	}
	// An empty list is valid and means the Endpoint is configured with no
	// Adapter. Such an Endpoint still starts, connects and reports health; it
	// simply advertises no resource and refuses every command, because there is
	// no Adapter to route to. Rejecting the empty list would make a
	// zero-Adapter node impossible to run, which is the state a fresh install
	// and a Provider CLI rollout both pass through.
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
	if c.EndpointExpiry <= 0 {
		return fmt.Errorf("endpoint expiry must be positive")
	}
	if c.CommandRetention <= 0 {
		return fmt.Errorf("command retention must be positive")
	}
	if c.EndpointDegradedRetention <= 0 {
		return fmt.Errorf("endpoint degraded retention must be positive")
	}
	// A non-positive heartbeat bound would disable the Endpoint's only liveness
	// judgement, and a disabled judgement is indistinguishable from a healthy
	// Server. Rejecting it at startup keeps that failure visible instead of
	// letting the Endpoint stay attached to an unresponsive Server forever.
	if c.HeartbeatAckTimeout <= 0 {
		return fmt.Errorf("heartbeat acknowledgement timeout must be positive")
	}
	if c.UnhealthyWindow <= 0 {
		return fmt.Errorf("unhealthy window must be positive")
	}
	// A negative write-liveness budget is a configuration mistake, not a request to
	// disable the watchdog: zero is the documented way to disable it. Accepting a
	// negative value would make the watchdog fire on the first probe, which looks
	// like a database fault rather than the misconfiguration it is.
	if c.WriteLivenessBudget < 0 {
		return fmt.Errorf("write liveness budget must not be negative")
	}
	// A non-positive interval would make the watchdog probe in a tight loop, which
	// turns a diagnostic into a load source on the very database it is watching.
	if c.WriteLivenessInterval <= 0 {
		return fmt.Errorf("write liveness interval must be positive")
	}
	switch c.ChannelDirection {
	case DirectionEndpointInitiated, DirectionServerInitiated, DirectionBidirectional:
	default:
		return fmt.Errorf("invalid channel direction %q", c.ChannelDirection)
	}
	return nil
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
