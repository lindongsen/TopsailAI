package cli

import (
	"encoding/json"

	"flag"
	"fmt"
	"io"
	"strings"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// Environment variable names the CLI reads.
//
// They are read once, at the command boundary, and converted into Options. Nothing
// below this layer reads the environment, so a test can exercise every path by
// passing Options instead of mutating process state.
const (
	EnvServerURL   = "CONNECTOR_CLI_SERVER_URL"
	EnvClientToken = "CONNECTOR_CLI_CLIENT_TOKEN"
	EnvNode        = "CONNECTOR_CLI_NODE"
)

// Run executes one CLI invocation and writes its output.
//
// The exit status is returned rather than calling os.Exit, so the caller decides
// how to leave and a test can assert the status without ending the test process.
// A non-zero status accompanies every error code, so a shell script can branch on
// it.
func Run(arguments []string, lookup func(string) string, stdout, stderr io.Writer) int {
	if lookup == nil {
		lookup = func(string) string { return "" }
	}

	options, jsonOutput, err := parseArguments(arguments, lookup)
	if err != nil {
		fmt.Fprintf(stderr, "connector-server cli: %v\n", err)
		return 2
	}

	client := &Client{}
	envelope, err := client.Send(options)
	if err != nil {
		fmt.Fprintf(stderr, "connector-server cli: %v\n", err)
		return 1
	}

	if !envelope.Succeeded() {
		// The code and the message go to stderr and the payload is discarded,
		// because the caller has already been told the request failed. Writing a
		// partial payload to stdout would let a pipeline consume a result that
		// does not exist.
		fmt.Fprintf(stderr, "connector-server cli: %s: %s\n", envelope.Code.Name(), envelope.Message)
		return 1
	}

	if err := writeResult(stdout, stderr, options.Operation, envelope, jsonOutput); err != nil {
		fmt.Fprintf(stderr, "connector-server cli: %v\n", err)
		return 1
	}
	return 0
}

// parseArguments turns the command line and the environment into Options.
//
// Flags take precedence over the environment, because a flag is the more explicit
// statement of intent. The environment is a convenience for scripting, not a
// second configuration system.
func parseArguments(arguments []string, lookup func(string) string) (Options, bool, error) {
	flags := flag.NewFlagSet("cli", flag.ContinueOnError)
	flags.SetOutput(io.Discard)

	server := flags.String("server", "", "Server base URL")
	clientToken := flags.String("client-token", "", "client token the Server issued")
	node := flags.String("node", "", "node-id.node-token pair")
	scope := flags.String("scope", "", "scope name the Node's policy defines")
	path := flags.String("path", "", "relative path inside the scope")
	offset := flags.Int64("offset", 0, "byte offset for file.read")
	length := flags.Int64("length", 0, "byte count for file.read; 0 means up to the cap")
	requestID := flags.String("request-id", "", "correlation id echoed by the Server")
	jsonOutput := flags.Bool("json", false, "print the whole response envelope as JSON")

	if err := flags.Parse(arguments); err != nil {
		return Options{}, false, fmt.Errorf("%w: %v", ErrUsage, err)
	}

	operation, err := parseOperation(flags.Args())
	if err != nil {
		return Options{}, false, err
	}

	options := Options{
		ServerURL:   firstNonEmpty(*server, lookup(EnvServerURL)),
		ClientToken: security.Secret(firstNonEmpty(*clientToken, lookup(EnvClientToken))),
		Pair:        firstNonEmpty(*node, lookup(EnvNode)),
		Operation:   operation,
		Scope:       security.Scope(*scope),
		Path:        *path,
		Offset:      *offset,
		Length:      *length,
		RequestID:   *requestID,
	}

	if options.ServerURL == "" {
		return Options{}, false, fmt.Errorf("%w: --server or %s is required", ErrUsage, EnvServerURL)
	}
	if options.ClientToken == "" {
		return Options{}, false, fmt.Errorf("%w: --client-token or %s is required", ErrUsage, EnvClientToken)
	}
	if options.Pair == "" {
		return Options{}, false, fmt.Errorf("%w: --node or %s is required", ErrUsage, EnvNode)
	}
	if options.Scope == "" {
		return Options{}, false, fmt.Errorf("%w: --scope is required", ErrUsage)
	}
	if options.Offset < 0 {
		return Options{}, false, fmt.Errorf("%w: --offset must not be negative", ErrUsage)
	}
	if options.Length < 0 {
		return Options{}, false, fmt.Errorf("%w: --length must not be negative", ErrUsage)
	}

	return options, *jsonOutput, nil
}

// parseOperation reads the operation name from the positional arguments.
//
// Exactly one positional argument is accepted. A second one is refused rather than
// ignored, because an ignored argument is a command that did something other than
// what it looked like it did.
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
// wraps the whole envelope for scripting. The two are separate because a caller
// that pipes a file does not want a header, and a caller that parses a result does
// not want to guess the shape.
func writeResult(writer, notice io.Writer, operation protocol.Operation, envelope Envelope, jsonOutput bool) error {
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
		return writeReadResult(writer, notice, envelope.Data)
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
// A truncated read is reported on the notice stream, not on the payload stream,
// because a notice written to stdout would corrupt a piped payload. A caller that
// received a truncated file without being told would treat a partial read as a
// complete one.
func writeReadResult(writer, notice io.Writer, data json.RawMessage) error {
	var result readResult
	if err := json.Unmarshal(data, &result); err != nil {
		return fmt.Errorf("decode read result: %w", err)
	}
	if _, err := writer.Write(result.Content); err != nil {
		return err
	}
	if result.Truncated {
		fmt.Fprintf(notice, "connector-server cli: content truncated at %d bytes\n", result.Size)
	}
	return nil
}

// listEntry is one entry in the documented list payload.
//
// The field names follow docs/API.md exactly. A struct that renamed a field would
// decode it as the zero value and print a timestamp of 0, which looks like a file
// modified at the epoch rather than like a bug.
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
// It is exported so a verbose dump and an error message share one implementation.
// A redaction that printed a prefix or a length would still be a value derived from
// the secret, which the design forbids.
func Redact(secret security.Secret) string {
	if secret == "" {
		return ""
	}
	return "<redacted>"
}

// Describe renders one request for a verbose dump, with both secrets redacted.
//
// The node id is printed in full because it is not a secret: it is the public half
// of the pair, and an operator debugging a routing problem needs to see it.
func Describe(options Options) string {
	identity, err := security.ParseNodeIdentity(options.Pair)
	nodeID := "<malformed>"
	if err == nil {
		nodeID = identity.ID
	}

	parts := []string{
		"server=" + options.ServerURL,
		"node=" + nodeID,
		"operation=" + string(options.Operation),
		"scope=" + string(options.Scope),
		"client_token=" + Redact(options.ClientToken),
		"node_token=" + Redact(identity.Token),
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
