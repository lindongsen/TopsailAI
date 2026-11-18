package main

import (
	"strings"
)

const (
	cliServerURLEnv      = "AGENT_CLUSTER_CLI_SERVER_URL"
	cliServerTokenEnv    = "AGENT_CLUSTER_CLI_SERVER_TOKEN"
	cliEndpointTokensEnv = "AGENT_CLUSTER_CLI_ENDPOINT_TOKENS"
	// cliAuthModeEnv selects how the CLI presents its credentials.
	//
	// It is a CLI-owned key rather than a reuse of the Server or Endpoint key
	// because the CLI is a separate process with its own configuration file. A
	// CLI that read the Server's key would present a mode chosen for a different
	// process, and the two would disagree the moment one of them was changed.
	cliAuthModeEnv = "AGENT_CLUSTER_CLI_AUTH_MODE"
	// A profile is one Server URL and its bearer token under one name. The three
	// keys are separate because definition and selection are separate decisions:
	// a deployment ships the profiles once, and each operator or script selects
	// one without repeating the whole map.
	cliServerProfilesEnv      = "AGENT_CLUSTER_CLI_SERVER_PROFILES"
	cliServerProfileTokensEnv = "AGENT_CLUSTER_CLI_SERVER_PROFILE_TOKENS"
	cliServerProfileEnv       = "AGENT_CLUSTER_CLI_SERVER_PROFILE"
	// cliServerProfileStickyFileEnv overrides where the last Server that answered
	// is remembered. It is a path, not a name, because the file is per-user state
	// and an operator may keep it beside other state they already manage.
	cliServerProfileStickyFileEnv = "AGENT_CLUSTER_CLI_SERVER_PROFILE_STICKY_FILE"
)

// cliEnvironmentValue returns the component-owned value, or an empty string
// when it is unset or blank. A blank value is treated as unset so a variable
// exported as an empty string cannot silently override a default.
func cliEnvironmentValue(lookup func(string) string, name string) string {
	return strings.TrimSpace(lookup(name))
}
