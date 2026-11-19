package cli

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"strconv"
	"strings"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// Environment variable names the CLI reads.
//
// They are read once, at the command boundary, and converted into Options. Nothing
// below this layer reads the environment, so a test can exercise every path by passing
// Options instead of mutating process state.
//
// The two credentials are separate variables rather than one, because they are
// verified by different parties: the client credential by the Server and the node
// credential by the Node. A single variable holding both would make a rotation of one
// look like a rotation of the other.
const (
	EnvServerURL        = "CONNECTOR_CLI_SERVER_URL"
	EnvClientCredential = "CONNECTOR_CLI_CLIENT_CREDENTIAL"
	EnvNodeCredential   = "CONNECTOR_CLI_NODE_CREDENTIAL"
	EnvNodeID           = "CONNECTOR_CLI_NODE_ID"
	EnvScope            = "CONNECTOR_CLI_SCOPE"
	EnvPath             = "CONNECTOR_CLI_PATH"
	EnvOffset           = "CONNECTOR_CLI_OFFSET"
	EnvLength           = "CONNECTOR_CLI_LENGTH"
	EnvRequestID        = "CONNECTOR_CLI_REQUEST_ID"
	EnvOutput           = "CONNECTOR_CLI_OUTPUT"
	EnvForce            = "CONNECTOR_CLI_FORCE"
	EnvJSON             = "CONNECTOR_CLI_JSON"
	EnvEnvFile          = "CONNECTOR_CLI_ENV_FILE"
)

// defaultProgram is the name used when a caller does not supply one.
//
// It is the historical prefix, so an existing script that matched on
// "connector-server cli:" keeps working. A standalone binary passes its own name
// instead, so its messages name the program the operator actually ran.
const defaultProgram = "connector-server cli"

// Run executes one CLI invocation and writes its output.
//
// It keeps the historical program name, so an existing script that matched on
// "connector-server cli:" keeps working. A standalone binary calls RunAs with its
// own name instead, so its messages name the program the operator actually ran.
func Run(arguments []string, lookup func(string) string, stdout, stderr io.Writer) int {
	return RunAs(defaultProgram, arguments, lookup, stdout, stderr)
}

// RunAs executes one CLI invocation under the given program name.
//
// The exit status is returned rather than calling os.Exit, so the caller decides how
// to leave and a test can assert the status without ending the test process. A non-zero
// status accompanies every error code, so a shell script can branch on it.
func RunAs(program string, arguments []string, lookup func(string) string, stdout, stderr io.Writer) int {
	if lookup == nil {
		lookup = func(string) string { return "" }
	}

	// Help and version are answered before the arguments are parsed, because they are
	// requests to print something rather than requests to run an operation. Parsing
	// first would make `--help` fail on the missing credentials, which is the one case
	// where the caller has not yet learned what to supply.
	if handled, status := handleInformational(program, arguments, stdout, stderr); handled {
		return status
	}

	options, jsonOutput, err := parseArguments(arguments, lookup)
	if err != nil {
		fmt.Fprintf(stderr, "%s: %v\n", program, err)
		return 2
	}

	client := &Client{}

	// A destination changes the whole shape of the invocation: `file.read` loops until
	// end of file and the result is written atomically. Without one, the historical
	// single-request behaviour is kept exactly, so an existing script that relies on
	// one chunk and a truncation notice is unaffected.
	if options.Output != "" {
		if err := writeToDestination(client, options, stdout, stderr, program); err != nil {
			fmt.Fprintf(stderr, "%s: %v\n", program, err)
			return 1
		}
		return 0
	}

	// A `file.read` without a destination is one request, and it asks for the bytes
	// directly unless `--json` was given. The raw shape is the cheaper answer, and the
	// single-chunk case is the most common invocation, so leaving it on the envelope
	// would keep the encoding cost on the path most callers use.
	//
	// `--json` keeps the envelope because that flag asks for the envelope: a raw body
	// is not JSON, and printing it as JSON would produce something no parser accepts.
	if options.Operation == protocol.OperationFileRead && !jsonOutput {
		chunk, err := client.SendRaw(options)
		if err != nil {
			fmt.Fprintf(stderr, "%s: %v\n", program, err)
			if errors.Is(err, ErrUsage) {
				return 2
			}
			return 1
		}
		if _, err := stdout.Write(chunk.Content); err != nil {
			fmt.Fprintf(stderr, "%s: %v\n", program, err)
			return 1
		}
		// The notice goes to stderr, never to stdout, because a notice written to
		// stdout would corrupt a piped payload.
		if chunk.Truncated {
			fmt.Fprintf(stderr, "%s: content truncated at %d bytes\n", program, len(chunk.Content))
		}
		return 0
	}

	envelope, err := client.Send(options)
	if err != nil {
		fmt.Fprintf(stderr, "%s: %v\n", program, err)
		// A local check that refused the request before anything was sent is a usage
		// error, so it must exit 2 like every other refusal of that kind. The message
		// already begins with `usage:`, and a message that says `usage:` while the
		// status says 1 leaves a script unable to tell "the command line was rejected"
		// from "the request ran and failed".
		if errors.Is(err, ErrUsage) {
			return 2
		}
		return 1
	}

	if !envelope.Succeeded() {
		// The code and the message go to stderr and the payload is discarded, because
		// the caller has already been told the request failed. Writing a partial payload
		// to stdout would let a pipeline consume a result that does not exist.
		fmt.Fprintf(stderr, "%s: %s: %s\n", program, envelope.Code.Name(), envelope.Message)
		return 1
	}

	if err := writeResult(stdout, stderr, program, options.Operation, envelope, jsonOutput); err != nil {
		fmt.Fprintf(stderr, "%s: %v\n", program, err)
		return 1
	}
	return 0
}

// handleInformational answers --help, --version and the help subcommand.
//
// It reports whether the invocation was answered, so the caller can return the status
// without parsing. A help request is answered with status 0 because it succeeded at
// what it asked for. An operation named to `help` that this program does not offer is
// status 2, because the request named something that does not exist.
//
// The flags are read through the same registration parseArguments uses, rather than by
// scanning the arguments for the literal text. A scan cannot tell a flag from a value:
// `--path --help` names a file called --help, and a scan would print the help instead
// of reporting the path. Letting the parser decide means the answer comes from the
// grammar rather than from a string comparison.
func handleInformational(program string, arguments []string, stdout, stderr io.Writer) (bool, int) {
	// A parse error is not reported here. The caller parses again and reports it with
	// the same program name, so reporting it twice would print two lines for one
	// mistake. An unparseable command line cannot be a help request, so falling
	// through is correct.
	parsed := newCLIFlags()
	if err := parsed.set.Parse(arguments); err == nil {
		helpRequested := false
		versionRequested := false
		parsed.set.Visit(func(visited *flag.Flag) {
			switch visited.Name {
			case "h", "help":
				helpRequested = true
			case "version":
				versionRequested = true
			}
		})
		if helpRequested {
			fmt.Fprint(stdout, helpText(program))
			return true, 0
		}
		if versionRequested {
			fmt.Fprint(stdout, versionText(program))
			return true, 0
		}
	}

	// The help subcommand is a positional form, so it is read from the arguments
	// rather than from the flags. It is checked after the flags, because
	// `--help help` is a help request and the flag form is the more explicit one.
	if len(arguments) == 0 || arguments[0] != "help" {
		return false, 0
	}
	if len(arguments) == 1 {
		fmt.Fprint(stdout, helpText(program))
		return true, 0
	}
	if len(arguments) > 2 {
		fmt.Fprintf(stderr, "%s: usage: %s help [OPERATION]\n", program, program)
		return true, 2
	}

	name := arguments[1]
	if name != "help" {
		// Enabled is the right question, not Validate. `file.write` and
		// `command.exec` are declared in the wire vocabulary so a second-version
		// policy parses, but this version refuses them, so printing their help
		// would document an operation that cannot run. Validate would accept them
		// and fall through to the generic text, which is how `help file.write`
		// used to print the help for `help` itself.
		if !protocol.Operation(name).Enabled() {
			fmt.Fprintf(stderr, "%s: usage: %q is not an operation this version offers; want file.list, file.stat or file.read\n", program, name)
			return true, 2
		}
	}
	fmt.Fprint(stdout, operationHelpText(program, name))
	return true, 0
}

// cliFlags holds one registration of every flag this program accepts.
//
// The registration lives in one place because two callers need it: parseArguments
// reads the values, and handleInformational asks the parser which tokens are flags
// rather than scanning the arguments itself. A second registration list would drift
// from the first, and the drift would show up as a flag that parses but is not
// recognised as a flag, or the reverse.
type cliFlags struct {
	set              *flag.FlagSet
	server           *string
	clientCredential *string
	nodeCredential   *string
	nodeID           *string
	scope            *string
	path             *string
	offset           *int64
	length           *int64
	requestID        *string
	jsonOutput       *bool
	output           *string
	force            *bool
}

// newCLIFlags registers every flag and returns the handles.
//
// The parser writes nothing to stderr, because the caller decides what to print and
// with which program name. A parser that printed its own message would produce a
// second, differently prefixed line for the same failure.
func newCLIFlags() *cliFlags {
	set := flag.NewFlagSet("cli", flag.ContinueOnError)
	set.SetOutput(io.Discard)

	registered := &cliFlags{set: set}
	registered.server = set.String("server", "", "Server base URL")
	registered.clientCredential = set.String("client-credential", "", "client credential in key_id.secret form")
	registered.nodeCredential = set.String("node-credential", "", "node credential in key_id.secret form")
	registered.nodeID = set.String("node-id", "", "node id the request is for")
	registered.scope = set.String("scope", "", "scope name the Node's policy defines")
	registered.path = set.String("path", "", "relative path inside the scope")
	registered.offset = set.Int64("offset", 0, "byte offset for file.read")
	registered.length = set.Int64("length", 0, "byte count for file.read; 0 means up to the cap")
	registered.requestID = set.String("request-id", "", "correlation id signed by both proofs")
	registered.jsonOutput = set.Bool("json", false, "print the whole response envelope as JSON")
	// -o and --output are two registrations of one variable, because Go's flag
	// package treats them as unrelated names. Registering only one would make the
	// other an unknown flag, and the documented short form is the one an operator
	// types.
	registered.output = set.String("o", "", "local destination for the result, or - for stdout")
	set.StringVar(registered.output, "output", "", "local destination for the result, or - for stdout")
	registered.force = set.Bool("force", false, "replace an existing destination file")
	// -h, --help and --version are registered rather than left to the parser's
	// built-in behaviour. Without a registered "h", flag.Parse returns ErrHelp and
	// prints its own usage, which would bypass the help text this program documents.
	// Registering them also lets handleInformational ask Visit which of them was
	// written, instead of scanning the arguments for the literal text.
	set.Bool("h", false, "print this help and exit 0")
	set.Bool("help", false, "print this help and exit 0")
	set.Bool("version", false, "print the build version and exit 0")
	return registered
}

// parseArguments turns the command line and the environment into Options.
//
// Flags take precedence over the environment, because a flag is the more explicit
// statement of intent. The environment is a convenience for scripting, not a second
// configuration system.
func parseArguments(arguments []string, lookup func(string) string) (Options, bool, error) {
	parsed := newCLIFlags()
	if err := parsed.set.Parse(arguments); err != nil {
		return Options{}, false, fmt.Errorf("%w: %v", ErrUsage, err)
	}
	server := parsed.server
	clientCredential := parsed.clientCredential
	nodeCredential := parsed.nodeCredential
	nodeID := parsed.nodeID
	scope := parsed.scope
	path := parsed.path
	offset := parsed.offset
	length := parsed.length
	requestID := parsed.requestID
	jsonOutput := parsed.jsonOutput
	output := parsed.output
	force := parsed.force

	// Visit reports only the flags actually written, which is the distinction the
	// default value cannot express. Two cases depend on it: `-o ""` asks for a
	// destination and names none, and `--offset 0` must override a non-zero
	// environment value because the caller typed it. Testing the value against the
	// default would read both as "not set".
	given := map[string]bool{}
	parsed.set.Visit(func(visited *flag.Flag) {
		name := visited.Name
		if name == "o" {
			name = "output"
		}
		given[name] = true
	})
	if given["output"] && *output == "" {
		return Options{}, false, fmt.Errorf("%w: -o needs a destination; use - for stdout or a file path", ErrUsage)
	}

	operation, err := parseOperation(parsed.set.Args())
	if err != nil {
		return Options{}, false, err
	}

	clientValue := firstNonEmpty(*clientCredential, lookup(EnvClientCredential))
	nodeValue := firstNonEmpty(*nodeCredential, lookup(EnvNodeCredential))

	// A numeric or boolean value from the environment is parsed rather than trusted,
	// because a malformed value that was silently read as zero would run a different
	// request than the one the operator configured.
	offsetValue, err := firstInt64(*offset, given["offset"], lookup(EnvOffset), EnvOffset)
	if err != nil {
		return Options{}, false, err
	}
	lengthValue, err := firstInt64(*length, given["length"], lookup(EnvLength), EnvLength)
	if err != nil {
		return Options{}, false, err
	}
	forceValue, err := firstBool(*force, given["force"], lookup(EnvForce), EnvForce)
	if err != nil {
		return Options{}, false, err
	}
	jsonValue, err := firstBool(*jsonOutput, given["json"], lookup(EnvJSON), EnvJSON)
	if err != nil {
		return Options{}, false, err
	}

	options := Options{
		ServerURL: firstNonEmpty(*server, lookup(EnvServerURL)),
		NodeID:    firstNonEmpty(*nodeID, lookup(EnvNodeID)),
		Operation: operation,
		Scope:     security.Scope(firstNonEmpty(*scope, lookup(EnvScope))),
		Path:      firstNonEmpty(*path, lookup(EnvPath)),
		Offset:    offsetValue,
		Length:    lengthValue,
		RequestID: firstNonEmpty(*requestID, lookup(EnvRequestID)),
		Output:    firstNonEmpty(*output, lookup(EnvOutput)),
		Force:     forceValue,
	}

	if options.ServerURL == "" {
		return Options{}, false, fmt.Errorf("%w: --server or %s is required", ErrUsage, EnvServerURL)
	}
	if clientValue == "" {
		return Options{}, false, fmt.Errorf("%w: --client-credential or %s is required", ErrUsage, EnvClientCredential)
	}
	if nodeValue == "" {
		return Options{}, false, fmt.Errorf("%w: --node-credential or %s is required", ErrUsage, EnvNodeCredential)
	}
	if options.NodeID == "" {
		return Options{}, false, fmt.Errorf("%w: --node-id or %s is required", ErrUsage, EnvNodeID)
	}
	if options.Scope == "" {
		return Options{}, false, fmt.Errorf("%w: --scope or %s is required", ErrUsage, EnvScope)
	}
	if options.Offset < 0 {
		return Options{}, false, fmt.Errorf("%w: --offset must not be negative", ErrUsage)
	}
	if options.Length < 0 {
		return Options{}, false, fmt.Errorf("%w: --length must not be negative", ErrUsage)
	}
	// --json and -o describe two different output contracts: one wraps the envelope,
	// the other writes the payload. Accepting both would mean one of them silently
	// wins, so the combination is refused instead of resolved.
	if jsonValue && options.Output != "" {
		return Options{}, false, fmt.Errorf("%w: --json and -o cannot be combined; --json prints the envelope and -o writes the payload", ErrUsage)
	}
	// --force without a destination has nothing to force. Accepting it would let a
	// caller believe a protection was in effect when no file was ever written.
	if options.Force && options.Output == "" {
		return Options{}, false, fmt.Errorf("%w: --force requires -o", ErrUsage)
	}

	parsedClient, err := security.ParseCredential(clientValue)
	if err != nil {
		return Options{}, false, fmt.Errorf("%w: --client-credential %v", ErrUsage, err)
	}
	parsedNode, err := security.ParseCredential(nodeValue)
	if err != nil {
		return Options{}, false, fmt.Errorf("%w: --node-credential %v", ErrUsage, err)
	}
	options.ClientCredential = parsedClient
	options.NodeCredential = parsedNode

	return options, jsonValue, nil
}

// firstInt64 returns the flag value when the flag was written, otherwise the
// environment value.
//
// The `given` argument is the signal, not the value. A flag that was written is
// authoritative even when it equals the default, because the caller typed it: without
// this, `--offset 0` could not override a non-zero CONNECTOR_CLI_OFFSET, and the
// documented rule "a flag wins over the environment" would be false for exactly the
// value a caller is most likely to want. The environment is parsed rather than
// trusted: a value that is not a number is refused instead of being read as zero,
// which would silently run a different request than the one configured.
func firstInt64(flagValue int64, given bool, environmentValue, name string) (int64, error) {
	if given {
		return flagValue, nil
	}
	if environmentValue == "" {
		return flagValue, nil
	}
	parsed, err := strconv.ParseInt(strings.TrimSpace(environmentValue), 10, 64)
	if err != nil {
		return 0, fmt.Errorf("%w: %s must be a whole number, got %q", ErrUsage, name, environmentValue)
	}
	return parsed, nil
}

// firstBool returns the flag value when the flag was written, otherwise the
// environment value.
//
// The `given` argument is the signal for the same reason as in firstInt64: a written
// `--force=false` must override CONNECTOR_CLI_FORCE=1, and testing the value against
// the default would read that as "not set" and silently re-enable the switch the
// caller just turned off.
//
// The accepted spellings are the ones a shell script actually writes. Anything else is
// refused, because a security-relevant switch that silently accepts a spelling it does
// not understand is a switch whose state nobody can state.
func firstBool(flagValue bool, given bool, environmentValue, name string) (bool, error) {
	if given {
		return flagValue, nil
	}
	if environmentValue == "" {
		return flagValue, nil
	}
	switch strings.ToLower(strings.TrimSpace(environmentValue)) {
	case "1", "true", "yes", "on":
		return true, nil
	case "0", "false", "no", "off":
		return false, nil
	default:
		return false, fmt.Errorf("%w: %s must be 1 or 0, got %q", ErrUsage, name, environmentValue)
	}
}

// parseOperation reads the operation name from the positional arguments.
//
// Exactly one positional argument is accepted. A second one is refused rather than
// ignored, because an ignored argument is a command that did something other than what
// it looked like it did.
func parseOperation(rest []string) (protocol.Operation, error) {
	if len(rest) == 0 {
		return "", fmt.Errorf("%w: an operation is required; want file.list, file.stat or file.read", ErrUsage)
	}
	if len(rest) > 1 {
		return "", fmt.Errorf("%w: got %d positional arguments, want 1", ErrUsage, len(rest))
	}

	operation := protocol.Operation(rest[0])
	if err := operation.Validate(); err != nil {
		return "", fmt.Errorf("%w: %v", ErrUsage, err)
	}
	return operation, nil
}

// firstNonEmpty returns the first non-empty value.
func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

// writeResult prints one successful result.
//
// `file.read` writes the file content as raw bytes so it can be piped, and `--json`
// wraps the whole envelope for scripting. The two are separate because a caller that
// pipes a file does not want a header, and a caller that parses a result does not want
// to guess the shape.
func writeResult(writer, notice io.Writer, program string, operation protocol.Operation, envelope Envelope, jsonOutput bool) error {
	if jsonOutput {
		encoded, err := json.Marshal(envelope)
		if err != nil {
			return fmt.Errorf("encode envelope: %w", err)
		}
		_, err = fmt.Fprintln(writer, string(encoded))
		return err
	}

	switch operation {
	case protocol.OperationFileRead:
		return writeReadResult(writer, notice, program, envelope.Data)
	case protocol.OperationFileList:
		return writeListResult(writer, envelope.Data)
	case protocol.OperationFileStat:
		return writeStatResult(writer, envelope.Data)
	default:
		return fmt.Errorf("operation %q has no output format", operation)
	}
}

// readResult is the documented read payload.
type readResult struct {
	Content   []byte `json:"content"`
	Size      int64  `json:"size"`
	Truncated bool   `json:"truncated"`
}

// writeReadResult writes the file content as raw bytes.
//
// A truncated read is reported on the notice stream, not on the payload stream, because
// a notice written to stdout would corrupt a piped payload. A caller that received a
// truncated file without being told would treat a partial read as a complete one.
func writeReadResult(writer, notice io.Writer, program string, data json.RawMessage) error {
	var result readResult
	if err := json.Unmarshal(data, &result); err != nil {
		return fmt.Errorf("decode read result: %w", err)
	}
	if _, err := writer.Write(result.Content); err != nil {
		return err
	}
	if result.Truncated {
		fmt.Fprintf(notice, "%s: content truncated at %d bytes\n", program, result.Size)
	}
	return nil
}

// listEntry is one entry in the documented list payload.
//
// The field names follow docs/API.md exactly. A struct that renamed a field would decode
// it as the zero value and print a timestamp of 0, which looks like a file modified at
// the epoch rather than like a bug.
type listEntry struct {
	Name       string `json:"name"`
	Type       string `json:"type"`
	Size       int64  `json:"size"`
	Mode       string `json:"mode"`
	ModifiedAt int64  `json:"modified_at"`
}

// listResult is the documented list payload.
type listResult struct {
	Entries []listEntry `json:"entries"`
}

// writeListResult writes one entry per line.
func writeListResult(writer io.Writer, data json.RawMessage) error {
	var result listResult
	if err := json.Unmarshal(data, &result); err != nil {
		return fmt.Errorf("decode list result: %w", err)
	}
	for _, entry := range result.Entries {
		if _, err := fmt.Fprintf(writer, "%s\t%s\t%d\n", entry.Name, entry.Type, entry.Size); err != nil {
			return err
		}
	}
	return nil
}

// statResult is the documented stat payload.
//
// The field names follow docs/API.md exactly, for the same reason listEntry does.
type statResult struct {
	Name       string `json:"name"`
	Type       string `json:"type"`
	Size       int64  `json:"size"`
	Mode       string `json:"mode"`
	ModifiedAt int64  `json:"modified_at"`
	IsSymlink  bool   `json:"is_symlink"`
	LinkTarget string `json:"link_target,omitempty"`
}

// writeStatResult writes one line of key and value pairs.
func writeStatResult(writer io.Writer, data json.RawMessage) error {
	var result statResult
	if err := json.Unmarshal(data, &result); err != nil {
		return fmt.Errorf("decode stat result: %w", err)
	}
	if _, err := fmt.Fprintf(writer, "name\t%s\n", result.Name); err != nil {
		return err
	}
	if _, err := fmt.Fprintf(writer, "type\t%s\n", result.Type); err != nil {
		return err
	}
	if _, err := fmt.Fprintf(writer, "size\t%d\n", result.Size); err != nil {
		return err
	}
	if _, err := fmt.Fprintf(writer, "mode\t%s\n", result.Mode); err != nil {
		return err
	}
	if _, err := fmt.Fprintf(writer, "modified_at\t%d\n", result.ModifiedAt); err != nil {
		return err
	}
	if _, err := fmt.Fprintf(writer, "is_symlink\t%t\n", result.IsSymlink); err != nil {
		return err
	}
	if result.LinkTarget != "" {
		_, err := fmt.Fprintf(writer, "link_target\t%s\n", result.LinkTarget)
		return err
	}
	return nil
}

// Redact replaces a secret with a fixed marker.
//
// It is exported so a verbose dump and an error message share one implementation. A
// redaction that printed a prefix or a length would still be a value derived from the
// secret, which the design forbids.
func Redact(secret security.Secret) string {
	if secret == "" {
		return ""
	}
	return "<redacted>"
}

// Describe renders one request for a verbose dump, with both secrets redacted.
//
// The node id and both key identifiers are printed in full because they are public: an
// operator debugging a routing or authentication problem needs to see which Node was
// addressed and which credential was used.
func Describe(options Options) string {
	parts := []string{
		"server=" + options.ServerURL,
		"node=" + options.NodeID,
		"operation=" + string(options.Operation),
		"scope=" + string(options.Scope),
		"client_key_id=" + options.ClientCredential.KeyID,
		"client_secret=" + Redact(options.ClientCredential.Secret),
		"node_key_id=" + options.NodeCredential.KeyID,
		"node_secret=" + Redact(options.NodeCredential.Secret),
	}
	if options.Path != "" {
		parts = append(parts, "path="+options.Path)
	}
	if options.Offset != 0 {
		parts = append(parts, fmt.Sprintf("offset=%d", options.Offset))
	}
	if options.Length != 0 {
		parts = append(parts, fmt.Sprintf("length=%d", options.Length))
	}
	return strings.Join(parts, " ")
}
