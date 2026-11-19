package main

import (
	"fmt"
	"io"
	"os"

	"topsailai_connector/internal/node"
	"topsailai_connector/internal/security"
)

// isTerminal reports whether a file is an interactive terminal.
//
// It exists because the startup summary prints a secret in full only when a human is
// looking at it. A launcher that redirects stdout to a log file would otherwise write a
// credential that never expires to disk on every start, which is the leak the earlier
// print-once rule existed to prevent.
//
// The check is the standard library's character-device bit rather than a platform call,
// so it answers the same question on Linux, macOS and Windows: a console is a character
// device, a file and a pipe are not.
func isTerminal(file *os.File) bool {
	if file == nil {
		return false
	}
	info, err := file.Stat()
	if err != nil {
		return false
	}
	return info.Mode()&os.ModeCharDevice != 0
}

// printStartupSummary writes the facts an operator needs to reach this Node.
//
// It runs on every start, not only the first, because the operator who restarts a Node
// has the same question as the operator who started it: what do I put in the CLI. The
// earlier rule printed a generated credential once and never again, which left an
// operator who lost the terminal scroll with no way to recover the value except reading
// the credential file by hand.
//
// The secret is printed in full only when terminal is true. When stdout is redirected
// the summary still appears, with the secret replaced by its redacted form and a line
// saying why, so a log file records that a credential exists without recording the
// credential.
//
// The credential list is read from the file rather than from the runtime, because the
// runtime deliberately holds no secret: a runtime that could render a secret would be a
// runtime that could print one at any later moment. Reading it here makes the decision
// to write a secret to a terminal an act of the process boundary, which is where it
// belongs.
func printStartupSummary(w io.Writer, runtime *node.Runtime, terminal bool) error {
	config := runtime.Config()

	credentials, err := node.LoadCredentialList(config.CredentialsPath)
	if err != nil {
		return fmt.Errorf("read the credentials to report them: %w", err)
	}

	names := runtime.Authority().ScopeNames()
	scopes := make([]string, 0, len(names))
	absent := make([]string, 0, len(names))
	for _, name := range names {
		scopes = append(scopes, string(name))
		if scope, ok := runtime.Authority().Scope(name); ok && scope.Absent() {
			absent = append(absent, string(name))
		}
	}

	policy := config.PolicyPath
	if config.PolicyBytes != nil {
		policy = "embedded in this binary"
	}

	fmt.Fprintln(w, "=== connector-node ===")
	fmt.Fprintf(w, "server        : %s\n", config.ServerURL)
	fmt.Fprintf(w, "node id       : %s\n", runtime.IdentityID())
	fmt.Fprintf(w, "config dir    : %s\n", config.ConfigDir)
	fmt.Fprintf(w, "credentials   : %s\n", config.CredentialsPath)
	fmt.Fprintf(w, "policy        : %s\n", policy)
	fmt.Fprintf(w, "scopes        : %s\n", joinOrNone(scopes))
	if len(absent) > 0 {
		fmt.Fprintf(w, "absent scopes : %s\n", joinOrNone(absent))
		fmt.Fprintln(w, "                (defined but the directory does not exist; every request")
		fmt.Fprintln(w, "                 on these answers not_found until it exists and the node restarts)")
	}

	if len(credentials) == 0 {
		fmt.Fprintln(w, "credential    : none; this node refuses every caller")
	} else {
		for _, credential := range credentials {
			printCredential(w, credential, terminal)
		}
	}

	fmt.Fprintln(w, "")
	printClientEnvironment(w, config, runtime.IdentityID(), credentials, terminal)
	return nil
}

// printCredential writes one credential, in full only when a human is watching.
func printCredential(w io.Writer, credential security.Credential, terminal bool) {
	fmt.Fprintf(w, "key id        : %s\n", credential.KeyID)
	if terminal {
		fmt.Fprintf(w, "secret        : %s\n", string(credential.Secret))
		fmt.Fprintf(w, "credential    : %s\n", credential.String())
		return
	}
	fmt.Fprintf(w, "secret        : %s\n", credential.Secret.Redacted())
	fmt.Fprintf(w, "credential    : %s\n", credential.Redacted())
	fmt.Fprintln(w, "                (withheld because stdout is not a terminal; run the node in a")
	fmt.Fprintln(w, "                 terminal to see it, or read the credentials file named above)")
}

// printClientEnvironment writes the variables a CLI needs, ready to copy.
//
// It is printed because the operator's next act after starting a Node is pointing a CLI
// at it, and assembling four values by hand from a summary is where a copy-paste mistake
// happens. The block is omitted when there is no credential to present, because a CLI
// configured with a credential that does not exist fails with an authentication error
// that reads like a Server problem.
func printClientEnvironment(w io.Writer, config node.Config, nodeID string, credentials []security.Credential, terminal bool) {
	if len(credentials) == 0 {
		return
	}
	credential := credentials[0]
	secret := credential.Redacted()
	if terminal {
		secret = credential.String()
	}

	fmt.Fprintln(w, "To reach this node from a CLI, set:")
	fmt.Fprintf(w, "  CONNECTOR_CLI_SERVER_URL=%s\n", cliServerURL(config.ServerURL))
	fmt.Fprintf(w, "  CONNECTOR_CLI_NODE_ID=%s\n", nodeID)
	fmt.Fprintf(w, "  CONNECTOR_CLI_NODE_CREDENTIAL=%s\n", secret)
	if len(credentials) > 1 {
		fmt.Fprintf(w, "  (this node accepts %d credentials; the first is shown)\n", len(credentials))
	}
	fmt.Fprintln(w, "  CONNECTOR_CLI_CLIENT_CREDENTIAL=<the server's client credential>")
}

// cliServerURL converts the channel address into the address the CLI calls.
//
// The two are different surfaces on one listener: the Node dials `/channel` over a
// WebSocket, and the CLI posts to `/v1/` over HTTP. Printing the channel address as the
// CLI address would send an operator to a path that answers nothing, so the scheme and
// the path are rewritten here rather than left for the reader to work out.
func cliServerURL(channelURL string) string {
	trimmed := channelURL
	for _, prefix := range []string{"wss://", "ws://"} {
		if len(trimmed) >= len(prefix) && trimmed[:len(prefix)] == prefix {
			trimmed = trimmed[len(prefix):]
			break
		}
	}
	for _, suffix := range []string{"/channel", "/"} {
		if len(trimmed) >= len(suffix) && trimmed[len(trimmed)-len(suffix):] == suffix {
			trimmed = trimmed[:len(trimmed)-len(suffix)]
			break
		}
	}
	return "https://" + trimmed
}

// joinOrNone renders a list, or the word that says there is nothing to list.
func joinOrNone(values []string) string {
	if len(values) == 0 {
		return "none"
	}
	joined := ""
	for index, value := range values {
		if index > 0 {
			joined += " "
		}
		joined += value
	}
	return joined
}
