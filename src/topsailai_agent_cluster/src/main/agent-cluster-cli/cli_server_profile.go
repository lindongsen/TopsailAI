package main

import (
	"fmt"
	"strings"
)

// serverProfilesEnv names the configuration key that maps a profile name to a
// Server URL.
//
// A profile exists because a Server URL and its bearer token are one credential
// pair, not two independent settings. An operator who moves an Endpoint to a
// different Server has to change both at once, and changing them separately is
// how one Server's token ends up being presented to another Server.
const serverProfilesEnv = cliServerProfilesEnv

// serverProfileTokensEnv names the configuration key that maps a profile name to
// the bearer token that Server accepts.
//
// It is a separate key from the URL map because a token is a secret and an
// operator may keep the two in different files with different permissions. The
// two maps are joined by the profile name, so one name always selects one pair.
const serverProfileTokensEnv = cliServerProfileTokensEnv

// serverProfileEnv names the configuration key that selects a profile without a
// command-line flag.
//
// Selection is a separate key from definition so a deployment can ship the
// profiles once and let each operator or script choose one, instead of every
// caller repeating the whole map.
const serverProfileEnv = cliServerProfileEnv

// parseServerProfiles reads the "name=url" profile map.
//
// A URL may legitimately contain "=" in a query string, so the separator is not
// rejected inside the value. The split takes the first separator, so the value
// still parses unambiguously.
func parseServerProfiles(value string) (map[string]string, error) {
	return parsePairs(value, serverProfilesEnv, "name=url", "profile", "url", false)
}

// parseServerProfileTokens reads the "name=token" profile token map.
//
// A bearer token may legitimately end with "=" padding, so the separator is not
// rejected inside the value. Refusing it would reject a correct credential and
// report it as a formatting mistake.
func parseServerProfileTokens(value string) (map[string]string, error) {
	return parsePairs(value, serverProfileTokensEnv, "name=token", "profile", "token", false)
}

// validateServerProfileTokens rejects a token configured for a profile that has
// no URL.
//
// A token without a URL is always a typo: the operator believes a profile exists,
// and the selection would fail later with "unknown profile" while the token they
// configured sits unused. Reporting it at load time names the real mistake
// instead of letting the selection failure describe the symptom.
func validateServerProfileTokens(profiles, tokens map[string]string) error {
	for _, name := range sortedPairKeys(tokens) {
		if _, present := profiles[name]; !present {
			return fmt.Errorf("%s configures profile %q but %s does not define it", serverProfileTokensEnv, name, serverProfilesEnv)
		}
	}
	return nil
}

// resolveServerProfile returns the URL and token one profile selects.
//
// Both values come from the same profile, so a selection can never combine one
// Server's address with another Server's credential. A profile with no token is
// valid and yields an empty token, because a Server may be configured without one
// and an empty token means the CLI omits the Authorization header rather than
// inventing a default.
//
// An unknown name is refused with the configured names listed, because the
// alternative is a silent fallback to the built-in URL: the operator would then
// talk to the wrong Server while believing the profile took effect, and the only
// symptom would be an empty inventory.
func resolveServerProfile(name string, profiles, tokens map[string]string) (string, string, error) {
	url, present := profiles[name]
	if !present {
		configured := sortedPairKeys(profiles)
		if len(configured) == 0 {
			return "", "", fmt.Errorf("server profile %q was selected but %s defines no profiles", name, serverProfilesEnv)
		}
		return "", "", fmt.Errorf("server profile %q is not defined in %s; configured profiles: %s", name, serverProfilesEnv, strings.Join(configured, ", "))
	}
	return url, tokens[name], nil
}

// resolveServerTarget decides which Server URL and token one invocation uses.
//
// A profile supplies both values together. An explicit --server-url or --token
// alongside a profile is refused rather than merged, because merging is how a
// credential reaches the wrong Server: a stale --server-url left in a shell alias
// would silently redirect the profile's token to a different machine, and nothing
// in the output would show that the pair had been split. The refusal names both
// ways to proceed so the operator can pick one deliberately.
//
// Environment defaults for the URL and token are not a conflict. They are the
// fallback for an invocation that selects no profile, and a profile replaces them
// as a pair rather than overriding one of them.
func resolveServerTarget(profileName string, profiles, tokens map[string]string, explicitURL, explicitToken bool, flagURL, flagToken string) (string, string, error) {
	if profileName == "" {
		return flagURL, flagToken, nil
	}
	if explicitURL || explicitToken {
		return "", "", fmt.Errorf("--server-profile %q cannot be combined with --server-url or --token; state the profile alone, or state --server-url and --token without a profile", profileName)
	}
	return resolveServerProfile(profileName, profiles, tokens)
}
