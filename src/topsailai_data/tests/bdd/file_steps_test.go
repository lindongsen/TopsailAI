package bdd

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/cucumber/godog"
)

// scenarioPath resolves an argument that starts with "@" to a path inside the
// scenario workspace. Any other argument is returned unchanged so flags and
// literal values pass through untouched.
//
// The "@" convention keeps feature files free of absolute paths while still
// letting a scenario address files it created itself.
func scenarioPath(state *scenarioContext, argument string) (string, error) {
	if !strings.HasPrefix(argument, "@") {
		return argument, nil
	}
	relative := strings.TrimPrefix(argument, "@")
	if relative == "" {
		return "", fmt.Errorf("scenario path marker @ must be followed by a relative path")
	}
	resolved := filepath.Join(state.root, relative)
	base := state.root + string(os.PathSeparator)
	if resolved != state.root && !strings.HasPrefix(resolved, base) {
		return "", fmt.Errorf("scenario path %q escapes the scenario workspace", relative)
	}
	return resolved, nil
}

// unescapeContent expands the escape sequences a feature file can express in a
// single table cell.
func unescapeContent(value string) string {
	replacer := strings.NewReplacer(`\n`, "\n", `\t`, "\t", `\r`, "\r", `\\`, `\`)
	return replacer.Replace(value)
}

// givenScenarioFile writes a file inside the scenario workspace.
func givenScenarioFile(ctx context.Context, relative, content string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create parent folder for %q: %w", relative, err)
	}
	if err := os.WriteFile(path, []byte(unescapeContent(content)), 0o644); err != nil {
		return fmt.Errorf("write scenario file %q: %w", relative, err)
	}
	return nil
}

// givenScenarioRepeatedFile writes a file whose content repeats one character.
//
// It lets a scenario exceed the default read limit without embedding a huge
// literal in the feature file.
func givenScenarioRepeatedFile(ctx context.Context, relative, count, character string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return err
	}
	repeats, err := strconv.Atoi(strings.TrimSpace(count))
	if err != nil || repeats < 0 {
		return fmt.Errorf("invalid repeat count %q", count)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create parent folder for %q: %w", relative, err)
	}
	content := strings.Repeat(character, repeats)
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		return fmt.Errorf("write scenario file %q: %w", relative, err)
	}
	return nil
}

// givenScenarioFolder creates a folder inside the scenario workspace.
func givenScenarioFolder(ctx context.Context, relative string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(path, 0o755); err != nil {
		return fmt.Errorf("create scenario folder %q: %w", relative, err)
	}
	return nil
}

// runFileArguments runs the "file" command group with a table of arguments.
//
// Each row contributes exactly one argument. Arguments starting with "@" are
// resolved inside the scenario workspace, so a feature file never needs an
// absolute path.
func runFileArguments(ctx context.Context, table *godog.Table) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}

	args := make([]string, 0, len(table.Rows)+1)
	args = append(args, "file")
	for _, row := range table.Rows {
		if len(row.Cells) != 1 {
			return fmt.Errorf("each file argument row must contain one cell")
		}
		resolved, err := scenarioPath(state, row.Cells[0].Value)
		if err != nil {
			return err
		}
		args = append(args, resolved)
	}

	runCLI(ctx, state, args, strings.NewReader(""))
	return nil
}

// runFileArgumentsWithStdin runs the "file" command group with a table of
// arguments and pipes the given content into stdin. It proves that a write
// command reads redirected stdin when no --content or --from flag is given.
func runFileArgumentsWithStdin(ctx context.Context, content string, table *godog.Table) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}

	args := make([]string, 0, len(table.Rows)+1)
	args = append(args, "file")
	for _, row := range table.Rows {
		if len(row.Cells) != 1 {
			return fmt.Errorf("each file argument row must contain one cell")
		}
		resolved, err := scenarioPath(state, row.Cells[0].Value)
		if err != nil {
			return err
		}
		args = append(args, resolved)
	}

	runCLI(ctx, state, args, strings.NewReader(unescapeContent(content)))
	return nil
}

// scenarioFileContains verifies that a scenario file contains a fragment.
func scenarioFileContains(ctx context.Context, relative, fragment string) error {
	content, err := readScenarioFile(ctx, relative)
	if err != nil {
		return err
	}
	expected := unescapeContent(fragment)
	if !strings.Contains(content, expected) {
		return fmt.Errorf("expected %q to contain %q, got %q", relative, expected, content)
	}
	return nil
}

// scenarioFileDoesNotContain verifies that a scenario file lacks a fragment.
func scenarioFileDoesNotContain(ctx context.Context, relative, fragment string) error {
	content, err := readScenarioFile(ctx, relative)
	if err != nil {
		return err
	}
	expected := unescapeContent(fragment)
	if strings.Contains(content, expected) {
		return fmt.Errorf("expected %q not to contain %q, got %q", relative, expected, content)
	}
	return nil
}

// scenarioFileEquals verifies the exact content of a scenario file.
func scenarioFileEquals(ctx context.Context, relative, content string) error {
	actual, err := readScenarioFile(ctx, relative)
	if err != nil {
		return err
	}
	expected := unescapeContent(content)
	if actual != expected {
		return fmt.Errorf("expected %q to equal %q, got %q", relative, expected, actual)
	}
	return nil
}

// scenarioFileHasSize verifies the byte size of a scenario file.
func scenarioFileHasSize(ctx context.Context, relative, size string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return err
	}
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("stat scenario file %q: %w", relative, err)
	}
	expected, err := strconv.ParseInt(strings.TrimSpace(size), 10, 64)
	if err != nil {
		return fmt.Errorf("invalid expected size %q: %w", size, err)
	}
	if info.Size() != expected {
		return fmt.Errorf("expected %q to have size %d, got %d", relative, expected, info.Size())
	}
	return nil
}

// scenarioFolderExists verifies that a scenario folder exists.
func scenarioFolderExists(ctx context.Context, relative string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return err
	}
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("expected scenario folder %q to exist: %w", relative, err)
	}
	if !info.IsDir() {
		return fmt.Errorf("expected %q to be a folder", relative)
	}
	return nil
}

// readScenarioFile reads a scenario file by its workspace-relative name.
func readScenarioFile(ctx context.Context, relative string) (string, error) {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return "", err
	}
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return "", err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("read scenario file %q: %w", relative, err)
	}
	return string(data), nil
}
