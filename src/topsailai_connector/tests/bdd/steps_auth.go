//go:build bdd

package bdd

import (
	"encoding/json"
	"fmt"
	"strings"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// authSteps registers the steps the authentication scenarios use.
//
// They are registered from a second function rather than appended to steps() so the
// policy steps and the authentication steps stay readable as two groups. A step is
// still registered exactly once, and an unmatched step is still a failure.
func authSteps(registered *registry) {
	registered.given(`the node holds a credential the caller knows`, func(w *world, arguments []string) error {
		w.signWith = bddNodeCredential
		return nil
	})

	registered.given(`the caller signs with a credential the node does not hold`, func(w *world, arguments []string) error {
		w.signWith = bddUnknownCredential
		return nil
	})

	registered.given(`the caller signs with a timestamp older than the window`, func(w *world, arguments []string) error {
		w.timestampAge = staleAge
		return nil
	})

	registered.when(`the caller sends a read of "([^"]*)" on scope "([a-z]+)"`, func(w *world, arguments []string) error {
		w.send(protocol.OperationFileRead, security.Scope(arguments[1]), arguments[0])
		return nil
	})

	registered.when(`the caller sends the same request again`, func(w *world, arguments []string) error {
		w.resend()
		return nil
	})

	registered.when(`the caller changes the path to "([^"]*)" after signing`, func(w *world, arguments []string) error {
		w.tamper(arguments[0])
		return nil
	})

	registered.when(`the caller removes the proof after signing`, func(w *world, arguments []string) error {
		w.stripProof()
		return nil
	})

	registered.when(`the caller changes the node id after signing`, func(w *world, arguments []string) error {
		w.readdress()
		return nil
	})

	registered.then(`the response carries the code "([a-z_]+)"`, func(w *world, arguments []string) error {
		if got := w.code(); got != arguments[0] {
			return fmt.Errorf("code is %q, want %q", got, arguments[0])
		}
		return nil
	})

	registered.then(`the response carries the file content "([^"]*)"`, func(w *world, arguments []string) error {
		// The read payload is JSON with a base64 content field, so a scenario that
		// compared the raw bytes would be asserting the encoding rather than the
		// file. Decoding here keeps the scenario about the file.
		var payload struct {
			Content []byte `json:"content"`
		}
		if err := json.Unmarshal(w.data(), &payload); err != nil {
			return fmt.Errorf("decode the read payload: %w", err)
		}
		if got := string(payload.Content); got != arguments[0] {
			return fmt.Errorf("file content is %q, want %q", got, arguments[0])
		}
		return nil
	})

	registered.then(`the node log does not contain the credential secret`, func(w *world, arguments []string) error {
		if containsSecret(w.logText()) {
			return fmt.Errorf("the node log discloses the credential secret")
		}
		return nil
	})

	registered.then(`the node log names the key id "([^"]*)"`, func(w *world, arguments []string) error {
		if !strings.Contains(w.logText(), arguments[0]) {
			return fmt.Errorf("the node log does not name the key id %q", arguments[0])
		}
		return nil
	})
}
