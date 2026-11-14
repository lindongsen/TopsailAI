package tui

import (
	"fmt"
	"strings"
)

// resumeUsage is the accepted interactive resume grammar.
//
// The session form is listed first because it is the form an operator uses when
// they already know the target, which is the common case inside endpoint scope.
const resumeUsage = "usage: resume [-s <session_id>] [row]"

// resumeArgs is one parsed interactive resume argument.
type resumeArgs struct {
	// Handle is the provider session identifier the operator named with -s.
	// It is empty when the operator used a row number or the bare form.
	Handle string
	// Token is the positional argument, which is a row number or, in endpoint
	// scope, a session identifier.
	Token string
}

// parseResumeArgs parses the interactive resume argument.
//
// The -s form exists because an operator inside one endpoint usually knows the
// provider's own session identifier and should not have to render a table first
// just to learn a row number. It is a client-side convenience only: the value is
// forwarded to the Endpoint, which resolves it to a durable mapping without
// asking the provider whether the session exists. The operator named the target,
// so the client must not judge it.
//
// A flag and a positional argument are mutually exclusive, because they are two
// different ways to name one target and accepting both would leave the client
// choosing between them. An unknown flag is rejected with the usage line rather
// than ignored, so a typo cannot silently resume a different session.
func parseResumeArgs(rest string) (resumeArgs, error) {
	var parsed resumeArgs
	tokens := strings.Fields(rest)
	for i := 0; i < len(tokens); i++ {
		token := tokens[i]
		switch {
		case token == "-s" || token == "--session":
			if i+1 >= len(tokens) {
				return resumeArgs{}, fmt.Errorf("%s", resumeUsage)
			}
			i++
			if parsed.Handle != "" {
				return resumeArgs{}, fmt.Errorf("%s", resumeUsage)
			}
			parsed.Handle = tokens[i]
		case strings.HasPrefix(token, "--session="):
			if parsed.Handle != "" {
				return resumeArgs{}, fmt.Errorf("%s", resumeUsage)
			}
			// An empty value is rejected rather than treated as an omitted
			// flag. Accepting it would leave Handle empty, and the bare form
			// then means "the only unknown session", so a typo would silently
			// resume a different target than the one named.
			parsed.Handle = strings.TrimPrefix(token, "--session=")
			if strings.TrimSpace(parsed.Handle) == "" {
				return resumeArgs{}, fmt.Errorf("%s", resumeUsage)
			}
		case strings.HasPrefix(token, "-"):
			return resumeArgs{}, fmt.Errorf("%s", resumeUsage)
		default:
			if parsed.Token != "" {
				return resumeArgs{}, fmt.Errorf("%s", resumeUsage)
			}
			parsed.Token = token
		}
	}
	if parsed.Handle == "" && parsed.Token == "" {
		return parsed, nil
	}
	if parsed.Handle != "" && parsed.Token != "" {
		return resumeArgs{}, fmt.Errorf("%s", resumeUsage)
	}
	if parsed.Handle != "" && strings.TrimSpace(parsed.Handle) == "" {
		return resumeArgs{}, fmt.Errorf("%s", resumeUsage)
	}
	return parsed, nil
}
