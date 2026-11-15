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

// buildAsciiWithInsertion builds a byte slice of ASCII filler with one string
// inserted at a chosen byte offset.
//
// It exists so a scenario can place a non-ASCII character beyond the 32768-byte
// encoding detection sample without embedding a huge literal in the feature
// file. The filler is the ASCII letter "a", which is valid in every ASCII
// superset encoding and therefore carries no encoding evidence.
func buildAsciiWithInsertion(total int, insertion string, offset int) ([]byte, error) {
	if total <= 0 {
		return nil, fmt.Errorf("total size must be positive, got %d", total)
	}
	if offset < 0 || offset > total {
		return nil, fmt.Errorf("offset %d is outside a %d-byte file", offset, total)
	}
	payload := []byte(insertion)
	if offset+len(payload) > total {
		return nil, fmt.Errorf("insertion of %d bytes at offset %d exceeds a %d-byte file", len(payload), offset, total)
	}
	data := make([]byte, total)
	for index := range data {
		data[index] = 'a'
	}
	copy(data[offset:], payload)
	return data, nil
}

// givenScenarioAsciiFileWithInsertion writes a scenario file of ASCII filler
// with one string placed at a chosen byte offset.
func givenScenarioAsciiFileWithInsertion(ctx context.Context, relative, total, insertion, offset string) error {
	size, err := strconv.Atoi(strings.TrimSpace(total))
	if err != nil {
		return fmt.Errorf("invalid total size %q: %w", total, err)
	}
	position, err := strconv.Atoi(strings.TrimSpace(offset))
	if err != nil {
		return fmt.Errorf("invalid offset %q: %w", offset, err)
	}
	data, err := buildAsciiWithInsertion(size, unescapeContent(insertion), position)
	if err != nil {
		return err
	}
	return writeScenarioBytes(ctx, relative, data)
}

// givenScenarioAsciiFileWithInsertionAndInvalidByte writes a scenario file of
// ASCII filler with one string at a chosen offset and one invalid UTF-8 byte at
// another offset.
//
// It models a file that is valid UTF-8 except for a single stray byte, which is
// the case a whole-buffer validity check alone cannot rescue.
func givenScenarioAsciiFileWithInsertionAndInvalidByte(ctx context.Context, relative, total, insertion, offset, invalidOffset string) error {
	size, err := strconv.Atoi(strings.TrimSpace(total))
	if err != nil {
		return fmt.Errorf("invalid total size %q: %w", total, err)
	}
	position, err := strconv.Atoi(strings.TrimSpace(offset))
	if err != nil {
		return fmt.Errorf("invalid offset %q: %w", offset, err)
	}
	invalidPosition, err := strconv.Atoi(strings.TrimSpace(invalidOffset))
	if err != nil {
		return fmt.Errorf("invalid invalid-byte offset %q: %w", invalidOffset, err)
	}
	data, err := buildAsciiWithInsertion(size, unescapeContent(insertion), position)
	if err != nil {
		return err
	}
	if invalidPosition < 0 || invalidPosition >= len(data) {
		return fmt.Errorf("invalid byte offset %d is outside a %d-byte file", invalidPosition, len(data))
	}
	if invalidPosition >= position && invalidPosition < position+len(unescapeContent(insertion)) {
		return fmt.Errorf("invalid byte offset %d overlaps the inserted character at %d", invalidPosition, position)
	}
	data[invalidPosition] = 0xFF
	return writeScenarioBytes(ctx, relative, data)
}

// givenScenarioLatin1File writes a scenario file whose content is encoded as
// Latin-1 rather than UTF-8.
//
// It proves that a sample carrying genuine non-UTF-8 evidence still reaches the
// detected-decoder path instead of being forced to UTF-8.
func givenScenarioLatin1File(ctx context.Context, relative, content string) error {
	text := unescapeContent(content)
	data := make([]byte, 0, len(text))
	for _, character := range text {
		if character > 0xFF {
			return fmt.Errorf("character %q cannot be encoded as Latin-1", character)
		}
		data = append(data, byte(character))
	}
	return writeScenarioBytes(ctx, relative, data)
}

// writeScenarioBytes writes raw bytes to a file inside the scenario workspace.
func writeScenarioBytes(ctx context.Context, relative string, data []byte) error {
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
	if err := os.WriteFile(path, data, 0o644); err != nil {
		return fmt.Errorf("write scenario file %q: %w", relative, err)
	}
	return nil
}

// createFromScenarioFile creates an object whose content comes from a file the
// scenario wrote itself.
//
// The source is passed through --from, so the object is built through the public
// CLI exactly as a user would build it.
func createFromScenarioFile(ctx context.Context, name, relative, description string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	source, err := scenarioPath(state, "@"+relative)
	if err != nil {
		return err
	}
	runCLI(ctx, state, []string{
		"create", name,
		"--description", description,
		"--from", source,
	}, strings.NewReader(""))
	if state.result.code != 0 {
		return fmt.Errorf("create object %q from %q failed: stderr=%q stdout=%q", name, relative, state.result.stderr, state.result.stdout)
	}
	return nil
}

// runFileRead runs one read subcommand and returns its stdout.
func runFileRead(ctx context.Context, args ...string) ([]byte, error) {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return nil, err
	}
	runCLI(ctx, state, args, strings.NewReader(""))
	if state.result.code != 0 {
		return nil, fmt.Errorf("command %v failed: stderr=%q", args, state.result.stderr)
	}
	return state.result.stdout, nil
}

// fileReadEqualsScenarioFile verifies that "file read" returns the scenario file
// byte for byte.
//
// This is the core assertion of the feature: the read output must equal the
// stored bytes, not merely contain the character.
func fileReadEqualsScenarioFile(ctx context.Context, path, object, relative string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	expected, err := os.ReadFile(mustScenarioPath(state, relative))
	if err != nil {
		return fmt.Errorf("read scenario file %q: %w", relative, err)
	}
	actual, err := runFileRead(ctx, "file", "read", path, "--object", object)
	if err != nil {
		return err
	}
	if len(actual) != len(expected) {
		return fmt.Errorf("file read of %q in object %q returned %d bytes, want %d", path, object, len(actual), len(expected))
	}
	if string(actual) != string(expected) {
		return fmt.Errorf("file read of %q in object %q differs from %q", path, object, relative)
	}
	return nil
}

// fileReadContains verifies that "file read" output contains a fragment.
func fileReadContains(ctx context.Context, path, object, fragment string) error {
	actual, err := runFileRead(ctx, "file", "read", path, "--object", object)
	if err != nil {
		return err
	}
	expected := unescapeContent(fragment)
	if !strings.Contains(string(actual), expected) {
		return fmt.Errorf("file read of %q in object %q does not contain %q", path, object, expected)
	}
	return nil
}

// fileReadLinesContains verifies that "read-lines" output contains a fragment.
func fileReadLinesContains(ctx context.Context, path, object, fragment string) error {
	actual, err := runFileRead(ctx, "file", "read-lines", path, "--object", object, "--start", "1", "--end", "-1")
	if err != nil {
		return err
	}
	expected := unescapeContent(fragment)
	if !strings.Contains(string(actual), expected) {
		return fmt.Errorf("file read-lines of %q in object %q does not contain %q", path, object, expected)
	}
	return nil
}

// fileReadAroundContains verifies that "read-around" output contains a fragment.
func fileReadAroundContains(ctx context.Context, path, object, line, fragment string) error {
	actual, err := runFileRead(ctx, "file", "read-around", path, line, "--object", object)
	if err != nil {
		return err
	}
	expected := unescapeContent(fragment)
	if !strings.Contains(string(actual), expected) {
		return fmt.Errorf("file read-around of %q in object %q at line %s does not contain %q", path, object, line, expected)
	}
	return nil
}

// fileReadContextContains verifies that "read-context" output contains a
// fragment.
func fileReadContextContains(ctx context.Context, path, object, pattern, fragment string) error {
	actual, err := runFileRead(ctx, "file", "read-context", path, pattern, "--object", object)
	if err != nil {
		return err
	}
	expected := unescapeContent(fragment)
	if !strings.Contains(string(actual), expected) {
		return fmt.Errorf("file read-context of %q in object %q matching %q does not contain %q", path, object, pattern, expected)
	}
	return nil
}

// fileReadFilesContains verifies that "read-files" output contains a fragment.
func fileReadFilesContains(ctx context.Context, path, object, fragment string) error {
	actual, err := runFileRead(ctx, "file", "read-files", path, "--object", object, "--format", "json")
	if err != nil {
		return err
	}
	expected := unescapeContent(fragment)
	if !strings.Contains(string(actual), expected) {
		return fmt.Errorf("file read-files of %q in object %q does not contain %q", path, object, expected)
	}
	return nil
}

// putFileReadBack writes the current "file read" output back into the object.
//
// It reproduces the read-modify-write cycle that previously destroyed the
// stored original, so the scenario proves the cycle is now lossless.
func putFileReadBack(ctx context.Context, path, object, destination string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	content, err := runFileRead(ctx, "file", "read", path, "--object", object)
	if err != nil {
		return err
	}
	runCLI(ctx, state, []string{"put", object, destination, "--from", "-"}, strings.NewReader(string(content)))
	if state.result.code != 0 {
		return fmt.Errorf("put %q into object %q failed: stderr=%q", destination, object, state.result.stderr)
	}
	return nil
}

// mustScenarioPath resolves a scenario-relative path and panics on an escape.
//
// The helper is only used after scenarioPath has already validated the same
// relative name, so a failure here indicates a programming error in the steps.
func mustScenarioPath(state *scenarioContext, relative string) string {
	path, err := scenarioPath(state, "@"+relative)
	if err != nil {
		panic(err)
	}
	return path
}

// objectFileEqualsScenarioFile verifies that a file inside an object equals a
// scenario file byte for byte.
//
// It is used by the read-modify-write scenario, where the stored content must
// survive a full read and write-back cycle unchanged.
func objectFileEqualsScenarioFile(ctx context.Context, name, path, relative string) error {
	state, err := scenarioFrom(ctx)
	if err != nil {
		return err
	}
	expected, err := os.ReadFile(mustScenarioPath(state, relative))
	if err != nil {
		return fmt.Errorf("read scenario file %q: %w", relative, err)
	}
	actual, err := objectFileContent(ctx, name, path)
	if err != nil {
		return err
	}
	if len(actual) != len(expected) {
		return fmt.Errorf("object %q file %q has %d bytes, want %d", name, path, len(actual), len(expected))
	}
	if actual != string(expected) {
		return fmt.Errorf("object %q file %q differs from %q", name, path, relative)
	}
	return nil
}

// registerEncodingSteps registers the steps of the encoding fidelity feature.
func registerEncodingSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a scenario file "([^"]+)" with (\d+) ASCII bytes and "([^"]*)" at byte (\d+)$`, givenScenarioAsciiFileWithInsertion)
	ctx.Step(`^a scenario file "([^"]+)" with (\d+) ASCII bytes and "([^"]*)" at byte (\d+) and an invalid byte at byte (\d+)$`, givenScenarioAsciiFileWithInsertionAndInvalidByte)
	ctx.Step(`^a scenario latin1 file "([^"]+)" with content "([^"]*)"$`, givenScenarioLatin1File)
	ctx.Step(`^I create object "([^"]+)" from scenario file "([^"]+)" with description "([^"]+)"$`, createFromScenarioFile)
	ctx.Step(`^the file read of "([^"]+)" in object "([^"]+)" equals scenario file "([^"]+)"$`, fileReadEqualsScenarioFile)
	ctx.Step(`^the file read of "([^"]+)" in object "([^"]+)" contains "([^"]*)"$`, fileReadContains)
	ctx.Step(`^the file read-lines of "([^"]+)" in object "([^"]+)" contains "([^"]*)"$`, fileReadLinesContains)
	ctx.Step(`^the file read-around of "([^"]+)" in object "([^"]+)" at line (\d+) contains "([^"]*)"$`, fileReadAroundContains)
	ctx.Step(`^the file read-context of "([^"]+)" in object "([^"]+)" matching "([^"]*)" contains "([^"]*)"$`, fileReadContextContains)
	ctx.Step(`^the file read-files of "([^"]+)" in object "([^"]+)" contains "([^"]*)"$`, fileReadFilesContains)
	ctx.Step(`^I put the file read of "([^"]+)" in object "([^"]+)" back as "([^"]+)"$`, putFileReadBack)
	ctx.Step(`^object "([^"]+)" file "([^"]+)" equals scenario file "([^"]+)"$`, objectFileEqualsScenarioFile)
}
