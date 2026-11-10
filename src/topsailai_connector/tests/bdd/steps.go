//go:build bdd

package bdd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"topsailai_connector/internal/node"
	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// steps returns the registry of step definitions the feature files use.
func steps() *registry {
	registered := &registry{}

	registered.given(`a policy that grants read on scope "([a-z]+)"`, func(w *world, arguments []string) error {
		return w.writePolicy(grantDocument(arguments[0], w.scopeDir, "read"))
	})

	registered.given(`a policy that grants read and stat on scope "([a-z]+)"`, func(w *world, arguments []string) error {
		return w.writePolicy(grantDocument(arguments[0], w.scopeDir, "read, stat"))
	})

	registered.given(`a policy file that does not exist`, func(w *world, arguments []string) error {
		w.policyPath = filepath.Join(w.baseDir, "absent-policy.yaml")
		return nil
	})

	registered.given(`a policy that grants nothing on scope "([a-z]+)"`, func(w *world, arguments []string) error {
		document := "version: 1\nscopes:\n  " + arguments[0] + ":\n    path: " + w.scopeDir + "\n"
		return w.writePolicy(document)
	})

	registered.given(`a policy that grants write on scope "([a-z]+)"`, func(w *world, arguments []string) error {
		return w.writePolicy(grantDocument(arguments[0], w.scopeDir, "write"))
	})

	registered.given(`a policy that grants exec on scope "([a-z]+)"`, func(w *world, arguments []string) error {
		return w.writePolicy(grantDocument(arguments[0], w.scopeDir, "exec"))
	})

	registered.given(`a policy that defines no scope`, func(w *world, arguments []string) error {
		return w.writePolicy("version: 1\nscopes: {}\n")
	})

	registered.given(`a policy whose scope "([a-z]+)" points at a missing directory`, func(w *world, arguments []string) error {
		return w.writePolicy(grantDocument(arguments[0], filepath.Join(w.baseDir, "absent"), "read"))
	})

	registered.given(`a policy whose scope "([a-z]+)" points at a file`, func(w *world, arguments []string) error {
		filePath := filepath.Join(w.baseDir, "not-a-directory")
		if err := os.WriteFile(filePath, []byte("x"), 0o644); err != nil {
			return err
		}
		return w.writePolicy(grantDocument(arguments[0], filePath, "read"))
	})

	registered.given(`a policy with an unknown version`, func(w *world, arguments []string) error {
		return w.writePolicy("version: 2\nscopes: {}\n")
	})

	registered.given(`a policy that is not valid YAML`, func(w *world, arguments []string) error {
		return w.writePolicy("version: 1\nscopes: [\n")
	})

	registered.given(`a file "([a-z.]+)" inside the scope containing "([^"]*)"`, func(w *world, arguments []string) error {
		return w.writeScopeFile(arguments[0], arguments[1])
	})

	registered.given(`a directory "([a-z]+)" inside the scope`, func(w *world, arguments []string) error {
		return os.MkdirAll(filepath.Join(w.scopeDir, arguments[0]), 0o755)
	})

	registered.given(`a symlink "([a-z.]+)" inside the scope pointing outside it`, func(w *world, arguments []string) error {
		outside := filepath.Join(w.baseDir, "outside")
		if err := os.MkdirAll(outside, 0o755); err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(outside, "secret.txt"), []byte("secret\n"), 0o644); err != nil {
			return err
		}
		return os.Symlink(outside, filepath.Join(w.scopeDir, arguments[0]))
	})

	registered.when(`the node loads the policy`, func(w *world, arguments []string) error {
		w.lastError = w.loadAuthority()
		return nil
	})

	registered.when(`the caller reads "([^"]*)" on scope "([a-z]+)"`, func(w *world, arguments []string) error {
		scope, err := w.authority.AuthorizeOperation(protocol.OperationFileRead, security.Scope(arguments[1]))
		if err != nil {
			w.lastError = err
			w.lastCode = node.CodeOf(err).Name()
			return nil
		}
		data, truncated, err := scope.Read(arguments[0], 0, 0)
		w.lastError = err
		w.lastCode = node.CodeOf(err).Name()
		w.lastData = data
		_ = truncated
		return nil
	})

	registered.when(`the caller lists "([^"]*)" on scope "([a-z]+)"`, func(w *world, arguments []string) error {
		scope, err := w.authority.AuthorizeOperation(protocol.OperationFileList, security.Scope(arguments[1]))
		if err != nil {
			w.lastError = err
			w.lastCode = node.CodeOf(err).Name()
			return nil
		}
		entries, err := scope.List(arguments[0])
		w.lastError = err
		w.lastCode = node.CodeOf(err).Name()
		w.lastList = entries
		return nil
	})

	registered.when(`the caller stats "([^"]*)" on scope "([a-z]+)"`, func(w *world, arguments []string) error {
		scope, err := w.authority.AuthorizeOperation(protocol.OperationFileStat, security.Scope(arguments[1]))
		if err != nil {
			w.lastError = err
			w.lastCode = node.CodeOf(err).Name()
			return nil
		}
		entry, err := scope.Stat(arguments[0])
		w.lastError = err
		w.lastCode = node.CodeOf(err).Name()
		w.lastEntry = entry
		return nil
	})

	registered.when(`the caller writes "([^"]*)" on scope "([a-z]+)"`, func(w *world, arguments []string) error {
		_, err := w.authority.AuthorizeOperation(protocol.OperationFileWrite, security.Scope(arguments[1]))
		w.lastError = err
		w.lastCode = node.CodeOf(err).Name()
		return nil
	})

	registered.when(`the caller runs a command on scope "([a-z]+)"`, func(w *world, arguments []string) error {
		_, err := w.authority.AuthorizeOperation(protocol.OperationCommandExec, security.Scope(arguments[0]))
		w.lastError = err
		w.lastCode = node.CodeOf(err).Name()
		return nil
	})

	registered.then(`the node starts`, func(w *world, arguments []string) error {
		if w.lastError != nil {
			return fmt.Errorf("startup failed: %v", w.lastError)
		}
		if w.authority == nil {
			return fmt.Errorf("no authority was loaded")
		}
		return nil
	})

	registered.then(`the node refuses to start`, func(w *world, arguments []string) error {
		if w.lastError == nil {
			return fmt.Errorf("startup succeeded, want a refusal")
		}
		return nil
	})

	registered.then(`the refusal names "([^"]*)"`, func(w *world, arguments []string) error {
		if w.lastError == nil {
			return fmt.Errorf("no refusal to inspect")
		}
		if !strings.Contains(w.lastError.Error(), arguments[0]) {
			return fmt.Errorf("refusal %q does not name %q", w.lastError.Error(), arguments[0])
		}
		return nil
	})

	registered.then(`the caller receives "([^"]*)"`, func(w *world, arguments []string) error {
		if w.lastError != nil {
			return fmt.Errorf("call failed: %v", w.lastError)
		}
		if string(w.lastData) != arguments[0] {
			return fmt.Errorf("received %q, want %q", string(w.lastData), arguments[0])
		}
		return nil
	})

	registered.then(`the caller receives the code "([a-z_]+)"`, func(w *world, arguments []string) error {
		if w.lastError == nil {
			return fmt.Errorf("call succeeded, want the code %q", arguments[0])
		}
		if w.lastCode != arguments[0] {
			return fmt.Errorf("code is %q, want %q", w.lastCode, arguments[0])
		}
		return nil
	})

	registered.then(`the listing contains "([a-z.]+)"`, func(w *world, arguments []string) error {
		if w.lastError != nil {
			return fmt.Errorf("list failed: %v", w.lastError)
		}
		for _, entry := range w.lastList {
			if entry.Name == arguments[0] {
				return nil
			}
		}
		return fmt.Errorf("listing does not contain %q", arguments[0])
	})

	registered.then(`the entry is a "([a-z]+)"`, func(w *world, arguments []string) error {
		if w.lastError != nil {
			return fmt.Errorf("stat failed: %v", w.lastError)
		}
		if w.lastEntry.Type != arguments[0] {
			return fmt.Errorf("entry type is %q, want %q", w.lastEntry.Type, arguments[0])
		}
		return nil
	})

	registered.then(`the entry reports a symlink`, func(w *world, arguments []string) error {
		if w.lastError != nil {
			return fmt.Errorf("stat failed: %v", w.lastError)
		}
		if !w.lastEntry.IsSymlink {
			return fmt.Errorf("entry does not report a symlink")
		}
		return nil
	})

	return registered
}

// grantDocument builds a policy document that defines one scope and grants it the
// named permissions. It is a helper rather than a string built at each call site,
// so a step cannot accidentally produce a document that grants something other
// than what its name says.
func grantDocument(scope string, path string, permissions string) string {
	return "version: 1\nscopes:\n  " + scope + ":\n    path: " + path +
		"\ngrants:\n  - scope: " + scope + "\n    permissions: [" + permissions + "]\n"
}
