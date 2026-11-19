// Package envfile reads KEY=VALUE pairs from a dotenv file.
//
// The format is deliberately small: one assignment per line, an optional
// `export` prefix, an optional pair of surrounding quotes, and `#` comments on
// their own line. Nothing is expanded, so a value is exactly the bytes written
// between the `=` and the end of the line. Expansion would mean a credential
// containing `$` is silently rewritten, and a rewritten credential fails
// authentication with a message that names nothing useful.
//
// A malformed line is an error rather than a skipped line. A configuration file
// that is half-read is a configuration nobody can reason about, and a silently
// ignored line is the failure mode that makes an operator believe a value is in
// force when it is not.
package envfile

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"strings"
)

// maxLineBytes bounds one line of the file.
//
// The scanner default is 64 KiB, which is far above any credential. The limit is
// raised anyway so a long line is refused by the size check rather than silently
// truncated by the scanner, because a truncated credential is a value that looks
// present and authenticates nothing.
const maxLineBytes = 1 << 20

// Load reads path and returns the pairs it defines.
//
// A missing file is not an error: it returns an empty map and no error. The file
// is a convenience for a caller that would otherwise export four variables, so
// its absence must not stop the program. A file that exists and cannot be read,
// or that holds a malformed line, is an error, because that is a configuration
// the caller believes is in force.
func Load(path string) (map[string]string, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return map[string]string{}, nil
		}
		return nil, fmt.Errorf("read %s: %w", path, err)
	}

	values, err := Parse(content)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return values, nil
}

// Parse parses dotenv content into a map.
//
// A key that appears twice keeps its last value, which is what a shell does when
// the same variable is assigned twice. The alternative, refusing the duplicate,
// would make a file that appends an override unreadable.
func Parse(content []byte) (map[string]string, error) {
	values := make(map[string]string)

	scanner := bufio.NewScanner(bytes.NewReader(content))
	scanner.Buffer(make([]byte, 0, 64*1024), maxLineBytes)

	lineNumber := 0
	for scanner.Scan() {
		lineNumber++

		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		// `export KEY=VALUE` is accepted because a caller often copies a line
		// straight out of a shell script. The prefix carries no meaning here:
		// nothing is exported to a parent process.
		line = strings.TrimPrefix(line, "export ")

		key, value, found := strings.Cut(line, "=")
		if !found {
			return nil, fmt.Errorf("line %d: expected KEY=VALUE, got %q", lineNumber, line)
		}

		key = strings.TrimSpace(key)
		if key == "" {
			return nil, fmt.Errorf("line %d: the key is empty", lineNumber)
		}
		if err := validateKey(key); err != nil {
			return nil, fmt.Errorf("line %d: %w", lineNumber, err)
		}

		values[key] = unquote(strings.TrimSpace(value))
	}

	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read: %w", err)
	}
	return values, nil
}

// validateKey refuses a key that is not an environment variable name.
//
// The check is a whitelist rather than a list of rejected characters, so a key
// containing a space, a dash or a control character is refused because it is not
// in the alphabet rather than because someone remembered to name it.
func validateKey(key string) error {
	for index := 0; index < len(key); index++ {
		character := key[index]
		switch {
		case character >= 'A' && character <= 'Z':
		case character >= 'a' && character <= 'z':
		case character >= '0' && character <= '9':
		case character == '_':
		default:
			return fmt.Errorf("the key %q contains %q; want letters, digits and underscore", key, string(character))
		}
	}
	return nil
}

// unquote removes one matching pair of surrounding quotes.
//
// Only a matching pair is removed, so a value that begins with a quote and does
// not end with one keeps both characters. A value is never partially unquoted,
// because a half-quoted credential is a credential that authenticates nothing.
func unquote(value string) string {
	if len(value) < 2 {
		return value
	}
	first := value[0]
	last := value[len(value)-1]
	if first == last && (first == '"' || first == '\'') {
		return value[1 : len(value)-1]
	}
	return value
}
