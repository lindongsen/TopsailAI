package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// validClientCredential and validNodeCredential are well-formed credentials.
//
// They are real values rather than placeholders because parseArguments validates
// them: a secret shorter than 32 characters is refused, so a short placeholder
// would make every test fail on the credential instead of on the property under
// test.
const (
	validClientCredential = "client-key.0123456789abcdef0123456789abcdef"
	validNodeCredential   = "node-key.0123456789abcdef0123456789abcdef"
)

// setRequiredEnvironment exports every value parseArguments requires, so a test
// that is about one property does not fail on a missing unrelated field.
func setRequiredEnvironment(t *testing.T) {
	t.Helper()
	t.Setenv("CONNECTOR_CLI_SERVER_URL", "http://192.168.2.3:8743")
	t.Setenv("CONNECTOR_CLI_NODE_ID", "node_ysj64hfylk2ke3aui65fygln2e")
	t.Setenv("CONNECTOR_CLI_CLIENT_CREDENTIAL", validClientCredential)
	t.Setenv("CONNECTOR_CLI_NODE_CREDENTIAL", validNodeCredential)
	t.Setenv("CONNECTOR_CLI_SCOPE", "project")
}

// captureRun calls run with stdout and stderr redirected to temporary files.
//
// run writes to os.Stdout and os.Stderr directly, because it is the process entry
// point. Redirecting them is what lets a test assert on what a caller would see
// without printing it into the test log.
func captureRun(t *testing.T, arguments []string) (int, string, string) {
	t.Helper()

	stdoutFile, err := os.CreateTemp(t.TempDir(), "stdout")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	stderrFile, err := os.CreateTemp(t.TempDir(), "stderr")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}

	originalStdout, originalStderr := os.Stdout, os.Stderr
	os.Stdout, os.Stderr = stdoutFile, stderrFile
	status := run(arguments)
	os.Stdout, os.Stderr = originalStdout, originalStderr

	if err := stdoutFile.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
	if err := stderrFile.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
	stdout, err := os.ReadFile(stdoutFile.Name())
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	stderr, err := os.ReadFile(stderrFile.Name())
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	return status, string(stdout), string(stderr)
}

// TestRunAnswersHelp checks that --help succeeds through the whole process, so the
// help text is reachable without any credential being configured. That is the one
// case where the caller has not yet learned what to supply.
func TestRunAnswersHelp(t *testing.T) {
	t.Setenv("CONNECTOR_CLI_ENV_FILE", filepath.Join(t.TempDir(), "absent"))

	status, stdout, stderr := captureRun(t, []string{"connector-cli", "--help"})
	if status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", status, stderr)
	}
	if !strings.Contains(stdout, "NAME") {
		t.Fatalf("stdout does not look like help: %q", stdout)
	}
	if !strings.Contains(stdout, "connector-cli") {
		t.Fatalf("help does not name the program: %q", stdout)
	}
}

// TestRunAnswersVersion checks that --version succeeds through the whole process.
func TestRunAnswersVersion(t *testing.T) {
	t.Setenv("CONNECTOR_CLI_ENV_FILE", filepath.Join(t.TempDir(), "absent"))

	status, stdout, stderr := captureRun(t, []string{"connector-cli", "--version"})
	if status != 0 {
		t.Fatalf("status = %d, want 0; stderr = %q", status, stderr)
	}
	if !strings.Contains(stdout, "connector-cli") {
		t.Fatalf("version does not name the program: %q", stdout)
	}
}

// TestRunRefusesAMalformedConfigurationFile checks that a file that exists and
// cannot be parsed stops the program with status 2, rather than being half-applied.
func TestRunRefusesAMalformedConfigurationFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env.local")
	if err := os.WriteFile(path, []byte("broken\n"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	t.Setenv("CONNECTOR_CLI_ENV_FILE", path)

	status, _, stderr := captureRun(t, []string{"connector-cli", "file.read"})
	if status != 2 {
		t.Fatalf("status = %d, want 2", status)
	}
	if !strings.Contains(stderr, path) {
		t.Fatalf("stderr does not name the file: %q", stderr)
	}
}

// TestRunRefusesAMissingRequiredValue checks that a request with no configuration
// is a usage error naming what is missing, so the caller knows what to supply.
func TestRunRefusesAMissingRequiredValue(t *testing.T) {
	t.Setenv("CONNECTOR_CLI_ENV_FILE", filepath.Join(t.TempDir(), "absent"))
	for _, name := range []string{
		"CONNECTOR_CLI_SERVER_URL", "CONNECTOR_CLI_NODE_ID",
		"CONNECTOR_CLI_CLIENT_CREDENTIAL", "CONNECTOR_CLI_NODE_CREDENTIAL",
		"CONNECTOR_CLI_SCOPE",
	} {
		t.Setenv(name, "")
	}

	status, _, stderr := captureRun(t, []string{"connector-cli", "file.read"})
	if status != 2 {
		t.Fatalf("status = %d, want 2", status)
	}
	if !strings.Contains(stderr, "usage:") {
		t.Fatalf("stderr does not begin a usage message: %q", stderr)
	}
}

// TestRunReadsTheConfigurationFileBesideTheBinary checks that a value in the file
// reaches the request, so a caller with no exported variable can still run. The
// request fails at the transport layer because no Server is listening, which is
// the evidence that the configuration was accepted and the request was attempted.
func TestRunReadsTheConfigurationFileBesideTheBinary(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env.local")
	content := strings.Join([]string{
		"CONNECTOR_CLI_SERVER_URL=http://127.0.0.1:1",
		"CONNECTOR_CLI_NODE_ID=node_ysj64hfylk2ke3aui65fygln2e",
		"CONNECTOR_CLI_CLIENT_CREDENTIAL=" + validClientCredential,
		"CONNECTOR_CLI_NODE_CREDENTIAL=" + validNodeCredential,
		"CONNECTOR_CLI_SCOPE=project",
		"",
	}, "\n")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	t.Setenv("CONNECTOR_CLI_ENV_FILE", path)

	status, _, stderr := captureRun(t, []string{"connector-cli", "--path", "notes.md", "file.read"})
	if status != 1 {
		t.Fatalf("status = %d, want 1 (transport failure); stderr = %q", status, stderr)
	}
	if strings.Contains(stderr, "is required") {
		t.Fatalf("a required value was not read from the file: %q", stderr)
	}
}

// TestProgramNameUsesTheTypedName checks that a renamed copy reports the name the
// operator typed, because that is the name in their shell history.
func TestProgramNameUsesTheTypedName(t *testing.T) {
	if got := programName([]string{"/usr/local/bin/connector-cli"}); got != "connector-cli" {
		t.Fatalf("programName = %q, want connector-cli", got)
	}
}

// TestProgramNameFallsBackForAnEmptyArgument checks that an empty first argument
// produces a usable prefix rather than an empty one, because an empty prefix makes
// a message look like a continuation of the previous line.
func TestProgramNameFallsBackForAnEmptyArgument(t *testing.T) {
	if got := programName([]string{""}); got != "connector-cli" {
		t.Fatalf("programName = %q, want connector-cli", got)
	}
	if got := programName(nil); got != "connector-cli" {
		t.Fatalf("programName = %q, want connector-cli", got)
	}
}

// TestConfigurationPathDefaultsBesideTheBinary checks that the default file is the
// one beside the executable, which is the documented behaviour for a binary
// installed anywhere.
func TestConfigurationPathDefaultsBesideTheBinary(t *testing.T) {
	t.Setenv("CONNECTOR_CLI_ENV_FILE", "")

	path, err := configurationPath()
	if err != nil {
		t.Fatalf("configurationPath: %v", err)
	}
	if filepath.Base(path) != ".env.local" {
		t.Fatalf("path = %q, want a .env.local", path)
	}
	if !filepath.IsAbs(path) {
		t.Fatalf("path = %q, want an absolute path", path)
	}
}

// TestConfigurationPathHonoursTheOverride checks that CONNECTOR_CLI_ENV_FILE
// selects a different file, which is how one installation serves two nodes.
func TestConfigurationPathHonoursTheOverride(t *testing.T) {
	wanted := filepath.Join(t.TempDir(), ".env.other")
	t.Setenv("CONNECTOR_CLI_ENV_FILE", wanted)

	path, err := configurationPath()
	if err != nil {
		t.Fatalf("configurationPath: %v", err)
	}
	if path != wanted {
		t.Fatalf("path = %q, want %q", path, wanted)
	}
}

// TestLoadConfigurationReadsTheFile checks that the values in the file reach the
// returned map, and that the path is reported so a warning can name it.
func TestLoadConfigurationReadsTheFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env.local")
	content := "CONNECTOR_CLI_SERVER_URL=http://file.example:8743\nCONNECTOR_CLI_NODE_ID=node_file\n"
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	t.Setenv("CONNECTOR_CLI_ENV_FILE", path)

	values, reported, err := loadConfiguration()
	if err != nil {
		t.Fatalf("loadConfiguration: %v", err)
	}
	if reported != path {
		t.Fatalf("reported path = %q, want %q", reported, path)
	}
	if values["CONNECTOR_CLI_SERVER_URL"] != "http://file.example:8743" {
		t.Fatalf("SERVER_URL = %q", values["CONNECTOR_CLI_SERVER_URL"])
	}
	if values["CONNECTOR_CLI_NODE_ID"] != "node_file" {
		t.Fatalf("NODE_ID = %q", values["CONNECTOR_CLI_NODE_ID"])
	}
}

// TestLoadConfigurationToleratesAMissingFile checks that a binary with no
// configuration file still runs, because the file is a convenience.
func TestLoadConfigurationToleratesAMissingFile(t *testing.T) {
	t.Setenv("CONNECTOR_CLI_ENV_FILE", filepath.Join(t.TempDir(), "absent"))

	values, _, err := loadConfiguration()
	if err != nil {
		t.Fatalf("loadConfiguration: %v", err)
	}
	if len(values) != 0 {
		t.Fatalf("got %#v, want an empty map", values)
	}
}

// TestLoadConfigurationRefusesAMalformedFile checks that a malformed file stops the
// program instead of being half-applied, and that the error names the file.
func TestLoadConfigurationRefusesAMalformedFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env.local")
	if err := os.WriteFile(path, []byte("broken\n"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	t.Setenv("CONNECTOR_CLI_ENV_FILE", path)

	_, _, err := loadConfiguration()
	if err == nil {
		t.Fatal("loadConfiguration returned no error")
	}
	if !strings.Contains(err.Error(), path) {
		t.Fatalf("error %q does not name %q", err, path)
	}
}

// warnToFile calls warnAboutPermissions with a real file and returns what it wrote.
//
// warnAboutPermissions takes an *os.File rather than an io.Writer because it is
// called with os.Stderr in production. A test therefore needs a real file, and
// reading it back is the only way to see the warning.
func warnToFile(t *testing.T, path string) string {
	t.Helper()

	file, err := os.CreateTemp(t.TempDir(), "stderr")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	warnAboutPermissions("connector-cli", path, file)
	if err := file.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
	content, err := os.ReadFile(file.Name())
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	return string(content)
}

// TestWarnAboutPermissionsWarnsForAGroupReadableFile checks that a file another
// account can read produces a warning, because it holds credentials that never
// expire.
func TestWarnAboutPermissionsWarnsForAGroupReadableFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env.local")
	if err := os.WriteFile(path, []byte("A=1\n"), 0o644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	if err := os.Chmod(path, 0o644); err != nil {
		t.Fatalf("Chmod: %v", err)
	}

	warning := warnToFile(t, path)
	if !strings.Contains(warning, "readable by other accounts") {
		t.Fatalf("no warning for a group-readable file: %q", warning)
	}
	if !strings.Contains(warning, path) {
		t.Fatalf("warning does not name the file: %q", warning)
	}
}

// TestWarnAboutPermissionsIsSilentForAnOwnerOnlyFile checks that the documented
// mode produces no warning, so the warning stays meaningful.
func TestWarnAboutPermissionsIsSilentForAnOwnerOnlyFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env.local")
	if err := os.WriteFile(path, []byte("A=1\n"), 0o600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatalf("Chmod: %v", err)
	}

	if warning := warnToFile(t, path); warning != "" {
		t.Fatalf("unexpected warning for a 0600 file: %q", warning)
	}
}

// TestWarnAboutPermissionsIsSilentForAMissingFile checks that a missing file
// produces no warning, because its absence is already tolerated.
func TestWarnAboutPermissionsIsSilentForAMissingFile(t *testing.T) {
	if warning := warnToFile(t, filepath.Join(t.TempDir(), "absent")); warning != "" {
		t.Fatalf("unexpected warning for a missing file: %q", warning)
	}
}
