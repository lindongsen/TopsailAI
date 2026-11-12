package main

import "strings"

const (
	cliServerURLEnv             = "AGENT_CLUSTER_CLI_SERVER_URL"
	cliTokenEnv                 = "AGENT_CLUSTER_CLI_TOKEN"
	cliEndpointTokensEnv        = "AGENT_CLUSTER_CLI_ENDPOINT_TOKENS"
	deprecatedServerURLEnv      = "AGENT_CLUSTER_SERVER_URL"
	deprecatedTokenEnv          = "AGENT_CLUSTER_TOKEN"
	deprecatedEndpointTokensEnv = "AGENT_CLUSTER_ENDPOINT_TOKENS"
)

// cliEnvironmentValue returns the component-owned value or a deprecated alias.
func cliEnvironmentValue(lookup func(string) string, primary string, deprecated ...string) string {
	if value := strings.TrimSpace(lookup(primary)); value != "" {
		return value
	}
	for _, name := range deprecated {
		if value := strings.TrimSpace(lookup(name)); value != "" {
			return value
		}
	}
	return ""
}
