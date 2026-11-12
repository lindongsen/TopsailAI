package main

import (
	"fmt"
	"io"
	"strings"
)

const (
	cliServerURLEnv             = "AGENT_CLUSTER_CLI_SERVER_URL"
	cliServerTokenEnv           = "AGENT_CLUSTER_CLI_SERVER_TOKEN"
	transitionalCLITokenEnv     = "AGENT_CLUSTER_CLI_TOKEN"
	cliEndpointTokensEnv        = "AGENT_CLUSTER_CLI_ENDPOINT_TOKENS"
	deprecatedServerURLEnv      = "AGENT_CLUSTER_SERVER_URL"
	deprecatedServerTokenEnv    = "AGENT_CLUSTER_TOKEN"
	deprecatedEndpointTokensEnv = "AGENT_CLUSTER_ENDPOINT_TOKENS"
)

// cliEnvironmentValue returns the component-owned value or a deprecated alias.
func cliEnvironmentValue(lookup func(string) string, primary string, deprecated ...string) string {
	return cliEnvironmentValueWithDiagnostics(lookup, io.Discard, primary, deprecated...)
}

// cliEnvironmentValueWithDiagnostics reports a deprecated name only when its
// value is actually selected. A configured primary name therefore stays quiet.
func cliEnvironmentValueWithDiagnostics(lookup func(string) string, diagnostics io.Writer, primary string, deprecated ...string) string {
	if value := strings.TrimSpace(lookup(primary)); value != "" {
		return value
	}
	for _, name := range deprecated {
		if value := strings.TrimSpace(lookup(name)); value != "" {
			if diagnostics != nil {
				fmt.Fprintf(diagnostics, "warning: %s is deprecated; use %s\n", name, primary)
			}
			return value
		}
	}
	return ""
}
