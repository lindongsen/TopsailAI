package main

import (
	"fmt"
	"strings"
)

// endpointTokensEnv names the configuration key that maps an Endpoint ID to the
// token that Endpoint accepts.
//
// The mapping lives in the CLI configuration rather than on the Server because a
// Server that held Endpoint tokens could hand them out, and could therefore grant
// access to every machine. Distributing them locally is what keeps the Server
// unable to grant or revoke access.
const endpointTokensEnv = "AGENT_CLUSTER_ENDPOINT_TOKENS"

// parseEndpointTokens reads the "endpoint_id=token" mapping.
//
// The format is a comma-separated list of pairs because it has to survive one
// environment assignment, and because a nested format would need a parser the
// operator cannot read at a glance. An empty value yields no mapping, which is
// the correct state for a deployment whose Endpoints require no token.
//
// Every malformed entry is rejected rather than skipped. A skipped entry would
// leave the operator believing a token was configured while the CLI silently sent
// nothing, and the resulting refusal would look like a policy problem on the
// Endpoint instead of a typo in the CLI configuration.
func parseEndpointTokens(value string) (map[string]string, error) {
	tokens := make(map[string]string)
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return tokens, nil
	}
	for _, entry := range strings.Split(trimmed, ",") {
		pair := strings.TrimSpace(entry)
		if pair == "" {
			return nil, fmt.Errorf("%s contains an empty entry", endpointTokensEnv)
		}
		endpointID, token, found := strings.Cut(pair, "=")
		endpointID = strings.TrimSpace(endpointID)
		token = strings.TrimSpace(token)
		if !found || endpointID == "" || token == "" {
			return nil, fmt.Errorf("%s entry %q is not an endpoint_id=token pair", endpointTokensEnv, pair)
		}
		// A token containing a separator could not be written back unambiguously,
		// so it is rejected instead of being silently truncated on the next read.
		if strings.ContainsAny(token, ",=") {
			return nil, fmt.Errorf("%s entry %q has a token containing a comma or equals sign", endpointTokensEnv, endpointID)
		}
		if _, duplicate := tokens[endpointID]; duplicate {
			return nil, fmt.Errorf("%s configures endpoint %q more than once", endpointTokensEnv, endpointID)
		}
		tokens[endpointID] = token
	}
	return tokens, nil
}

// resolveEndpointTokenTarget reports the one Endpoint a command addresses, so a
// command-line token can be attached to it.
//
// The explicit --endpoint filter wins when it is set. Otherwise the first
// argument after the command name is the Endpoint, because every endpoint-scoped
// command states its target there. A command that addresses no single Endpoint
// yields an empty result, and the caller then refuses a command-line token rather
// than guessing a destination.
func resolveEndpointTokenTarget(filter string, args []string) string {
	if filter != "" {
		return filter
	}
	if len(args) >= 2 {
		return args[1]
	}
	return ""
}

// applyEndpointTokenFlag records the token given on the command line for exactly
// one Endpoint.
//
// The flag is deliberately tied to one Endpoint instead of acting as a default
// for every target. A default would send one machine's credential to whichever
// machine a command happened to address, which is a credential leak rather than a
// convenience. The mapping file remains the normal path, because a token written
// on a command line stays in the shell history.
func applyEndpointTokenFlag(tokens map[string]string, endpointID, token string) error {
	if token == "" {
		return nil
	}
	if endpointID == "" {
		return fmt.Errorf("--endpoint-token requires a single endpoint, stated with --endpoint or as the command's endpoint argument")
	}
	if existing, present := tokens[endpointID]; present && existing != token {
		return fmt.Errorf("--endpoint-token conflicts with the configured token for endpoint %q", endpointID)
	}
	tokens[endpointID] = token
	return nil
}
