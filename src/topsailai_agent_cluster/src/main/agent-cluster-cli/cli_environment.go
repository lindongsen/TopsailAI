package main

import (
	"strings"
)

const (
	cliServerURLEnv      = "AGENT_CLUSTER_CLI_SERVER_URL"
	cliServerTokenEnv    = "AGENT_CLUSTER_CLI_SERVER_TOKEN"
	cliEndpointTokensEnv = "AGENT_CLUSTER_CLI_ENDPOINT_TOKENS"
)

// cliEnvironmentValue returns the component-owned value, or an empty string
// when it is unset or blank. A blank value is treated as unset so a variable
// exported as an empty string cannot silently override a default.
func cliEnvironmentValue(lookup func(string) string, name string) string {
	return strings.TrimSpace(lookup(name))
}
