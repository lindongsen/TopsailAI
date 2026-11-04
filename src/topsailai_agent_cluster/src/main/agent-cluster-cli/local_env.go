package main

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

const maxLocalEnvBytes = 1 << 20

// loadExecutableEnv reads only the executable-local configuration, never the cwd.
func loadExecutableEnv(executable string, lookup func(string) (string, bool), set func(string, string) error) error {
	path := filepath.Join(filepath.Dir(executable), ".env.local")
	file, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("open executable-local .env.local: %w", err)
	}
	defer file.Close()
	values, err := parseLocalEnv(io.LimitReader(file, maxLocalEnvBytes+1))
	if err != nil {
		return fmt.Errorf("load executable-local .env.local: %w", err)
	}
	for key, value := range values {
		if _, exists := lookup(key); exists {
			continue
		}
		if err := set(key, value); err != nil {
			return fmt.Errorf("set environment key %s: %w", key, err)
		}
	}
	return nil
}

// parseLocalEnv validates all assignments before any process environment mutation.
// Values are literals: expansion and command substitution are deliberately unsupported.
func parseLocalEnv(reader io.Reader) (map[string]string, error) {
	data, err := io.ReadAll(io.LimitReader(reader, maxLocalEnvBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) > maxLocalEnvBytes {
		return nil, fmt.Errorf("file exceeds %d bytes", maxLocalEnvBytes)
	}
	values := make(map[string]string)
	scanner := bufio.NewScanner(strings.NewReader(string(data)))
	scanner.Buffer(make([]byte, 4096), maxLocalEnvBytes+1)
	line := 0
	for scanner.Scan() {
		line++
		text := strings.TrimSpace(scanner.Text())
		if text == "" || strings.HasPrefix(text, "#") {
			continue
		}
		text = strings.TrimPrefix(text, "export ")
		key, value, ok := strings.Cut(text, "=")
		key = strings.TrimSpace(key)
		if !ok || !validEnvKey(key) {
			return nil, fmt.Errorf("invalid assignment at line %d", line)
		}
		value = strings.TrimSpace(value)
		if strings.ContainsRune(value, 0) {
			return nil, fmt.Errorf("invalid value at line %d", line)
		}
		if strings.HasPrefix(value, "\"") || strings.HasPrefix(value, "'") {
			quote := value[0]
			end := strings.IndexByte(value[1:], quote)
			if end < 0 {
				return nil, fmt.Errorf("unclosed quote at line %d", line)
			}
			end++
			tail := strings.TrimSpace(value[end+1:])
			if tail != "" && !strings.HasPrefix(tail, "#") {
				return nil, fmt.Errorf("invalid quoted value at line %d", line)
			}
			value = value[1:end]
		} else if index := strings.Index(value, " #"); index >= 0 {
			value = strings.TrimSpace(value[:index])
		}
		values[key] = value
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read .env.local: %w", err)
	}
	return values, nil
}

// validEnvKey accepts portable environment names without interpreting shell syntax.
func validEnvKey(key string) bool {
	if key == "" {
		return false
	}
	for i, r := range key {
		if r == '_' || r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z' || i > 0 && r >= '0' && r <= '9' {
			continue
		}
		return false
	}
	return true
}

// prepareExecutableEnv keeps process-level configuration at the actual CLI entry point.
func prepareExecutableEnv() error {
	executable, err := os.Executable()
	if err != nil {
		return fmt.Errorf("locate CLI executable: %w", err)
	}
	return loadExecutableEnv(executable, os.LookupEnv, os.Setenv)
}
