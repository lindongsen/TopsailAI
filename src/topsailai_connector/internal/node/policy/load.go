package policy

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"

	"gopkg.in/yaml.v3"
)

// MaxPolicyBytes bounds the policy file. A policy is a short configuration, so a
// large file is a mistake or an attack rather than a legitimate policy, and
// reading it into memory before deciding that is the wrong order.
const MaxPolicyBytes = 1 << 20

// ErrMissingFile is returned when the policy file does not exist. It is a
// distinct error because a missing file must fail startup rather than be read as
// an empty policy: an empty policy refuses everything, which looks like a
// working Node that denies every request.
var ErrMissingFile = errors.New("policy file is missing")

// Load reads and validates the policy file at path.
//
// The file is read once and decoded strictly: an unknown key is an error, because
// a typo in a security configuration that is silently ignored is worse than a
// crash. The size cap is applied before decoding so a large file is refused
// without being parsed.
func Load(path string) (*Policy, error) {
	if path == "" {
		return nil, fmt.Errorf("policy file path is empty")
	}

	info, err := os.Stat(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, fmt.Errorf("%w: %s", ErrMissingFile, path)
		}
		return nil, fmt.Errorf("stat policy file %q: %w", path, err)
	}
	if info.IsDir() {
		return nil, fmt.Errorf("policy file %q is a directory", path)
	}
	if info.Size() > MaxPolicyBytes {
		return nil, fmt.Errorf("policy file %q is %d bytes, want at most %d", path, info.Size(), MaxPolicyBytes)
	}

	content, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read policy file %q: %w", path, err)
	}
	return ParseBytes(content)
}

// ParseBytes decodes and validates a policy document.
//
// Decoding is strict in both directions: an unknown key is refused, and a
// document with more than one YAML document is refused, because a second
// document would be silently ignored and a policy that is half-read is a policy
// nobody can reason about.
func ParseBytes(content []byte) (*Policy, error) {
	decoder := yaml.NewDecoder(bytes.NewReader(content))
	decoder.KnownFields(true)

	var decoded file
	if err := decoder.Decode(&decoded); err != nil {
		if errors.Is(err, io.EOF) {
			return nil, fmt.Errorf("policy file is empty; an empty file is not an empty policy")
		}
		return nil, fmt.Errorf("decode policy: %w", err)
	}

	var extra file
	if err := decoder.Decode(&extra); err == nil {
		return nil, fmt.Errorf("policy file holds more than one document; only the first would be read")
	} else if !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("decode policy: %w", err)
	}

	return Parse(decoded)
}
