package main

import (
	"strings"
)

const (
	cliServerURLEnv      = "AGENT_CLUSTER_CLI_SERVER_URL"
	cliServerTokenEnv    = "AGENT_CLUSTER_CLI_SERVER_TOKEN"
	cliEndpointTokensEnv = "AGENT_CLUSTER_CLI_ENDPOINT_TOKENS"
	// A profile is one Server URL and its bearer token under one name. The three
	// keys are separate because definition and selection are separate decisions:
	// a deployment ships the profiles once, and each operator or script selects
	// one without repeating the whole map.
	cliServerProfilesEnv      = "AGENT_CLUSTER_CLI_SERVER_PROFILES"
	cliServerProfileTokensEnv = "AGENT_CLUSTER_CLI_SERVER_PROFILE_TOKENS"
	cliServerProfileEnv       = "AGENT_CLUSTER_CLI_SERVER_PROFILE"
)

// cliEnvironmentValue returns the component-owned value, or an empty string
// when it is unset or blank. A blank value is treated as unset so a variable
// exported as an empty string cannot silently override a default.
func cliEnvironmentValue(lookup func(string) string, name string) string {
	return strings.TrimSpace(lookup(name))
}
