package cli

import (
	"fmt"
	"runtime/debug"
	"strings"
)

// programPlaceholder is replaced with the program name in every help text.
//
// The texts are plain strings with a placeholder rather than `fmt` templates,
// because a help text is full of `%` characters in its examples and every one of
// them would have to be escaped. A missed escape prints `%!s(MISSING)` to the
// person asking for help, which is the worst possible place for that defect.
const programPlaceholder = "{{program}}"

// helpText renders the complete help for the program.
//
// The text is complete on purpose: every flag, every environment variable, the
// precedence between them, where the configuration file is looked for, every
// operation, every error code and every exit status. A help text that lists the
// flags but not the exit statuses leaves a script author guessing, and a help
// text that names an environment variable without saying it is overridden by a
// flag leaves an operator believing a value is in force when it is not.
func helpText(program string) string {
	return replaceProgram(program, `NAME
  {{program}} - call one operation on a Connector Node through the Server

SYNOPSIS
  {{program}} [FLAGS] OPERATION

  {{program}} help [OPERATION]
  {{program}} --help
  {{program}} --version

DESCRIPTION
  The Connector Server never dials a Node, so a Node on a personal computer
  needs no inbound port and no public address. This program is the caller's
  side of that arrangement: it signs one request with a client credential and a
  node credential, names the Node it wants, and prints the result.

  Two credentials are presented on every request, and each is verified by a
  different party:

    client credential   verified by the Server   may this caller use the Server
    node credential     verified by the Node     may this caller use this Node

  Neither credential carries a permission. The Node's own policy file is the
  only place a scope and a permission are granted, so a request for an operation
  the policy does not grant is refused no matter which credential the caller
  holds.

  The Node id is an address, not a credential. It appears in the URL and in
  every log line, and knowing it grants nothing.

OPERATIONS
  file.list    List one directory inside a scope.
               One line per entry: name, type, size.
               Use an empty --path to list the scope root.

  file.stat    Report metadata of one path inside a scope.
               One line per field: name, type, size, mode, modified_at,
               is_symlink, and link_target when the path is a symlink.

  file.read    Read a byte range of one file inside a scope.
               The content is written to stdout as raw bytes, so it can be
               piped. A single response is capped at 256 KiB; pass -o to read
               the whole file, or use --offset and --length to page through it.

  file.write and command.exec are refused by the Node in this version. They are
  not listed as operations because a help text that offers them would be
  offering something that cannot work.

FLAGS
  --server URL
        Base URL of the Server, for example http://192.168.2.3:8743 or
        https://connector.example.com:8443. A trailing slash is tolerated.
        Environment: CONNECTOR_CLI_SERVER_URL

  --node-id ID
        The Node the request is for, for example node_ysj64hfylk2ke3aui65fygln2e.
        Environment: CONNECTOR_CLI_NODE_ID

  --client-credential KEY_ID.SECRET
        The credential the Server verifies, in key_id.secret form.
        Environment: CONNECTOR_CLI_CLIENT_CREDENTIAL

  --node-credential KEY_ID.SECRET
        The credential the Node verifies, in key_id.secret form.
        Environment: CONNECTOR_CLI_NODE_CREDENTIAL

  --scope NAME
        The scope name the Node's policy defines, for example project.
        A scope is a name, never a path. Required.
        Environment: CONNECTOR_CLI_SCOPE

  --path PATH
        A path relative to the scope root. Required for file.stat and file.read;
        use an empty value to address the scope root for file.list.

        The accepted grammar is small, and a rejected path is refused rather
        than normalised:

          not absolute            /etc/passwd and C:\Windows are refused
          no .. component         ../x and a/../../x are refused
          no . component          ./x is refused
          no backslash            a\b is refused
          no colon                a:b is refused
          no NUL byte             a<NUL>b is refused
          no leading or trailing space, no control character
          at most 4096 bytes

        Environment: CONNECTOR_CLI_PATH

  --offset N
        Byte offset for file.read. Default 0. Must not be negative.
        Environment: CONNECTOR_CLI_OFFSET

  --length N
        Byte count for file.read. Default 0, which means up to the cap.
        Must not be negative.
        Environment: CONNECTOR_CLI_LENGTH

  --request-id ID
        Correlation id signed by both proofs. An empty value lets the program
        generate one, which is the ordinary case.
        Environment: CONNECTOR_CLI_REQUEST_ID

  -o PATH, --output PATH
        Write the result to a local file instead of stdout. The path is local,
        so an absolute path and a .. component are both legal here even though
        --path refuses them. Use - for stdout with a whole-file read.

        For file.read this reads the whole file by repeating the request until
        the Node reports end of file, so it is the way to fetch a file larger
        than the 256 KiB response cap.

        The file is written through a temporary file in the same directory and
        renamed into place, so a destination that exists always holds a complete
        result. An existing destination is refused unless --force is given.
        Environment: CONNECTOR_CLI_OUTPUT

  --force
        Permit -o to replace an existing file. Requires -o.
        Environment: CONNECTOR_CLI_FORCE

  --json
        Print the whole response envelope as one JSON object instead of the
        operation's own output. Cannot be combined with -o, because one wraps
        the envelope and the other writes the payload.
        Environment: CONNECTOR_CLI_JSON

  -h, --help
        Print this help and exit 0.

  --version
        Print the build version and exit 0.

  --env-file PATH
        Read KEY=VALUE pairs from this dotenv file instead of .env.local.
        The path must be absolute, because a relative path resolves
        differently per launch. A file named here must exist: a typo would
        otherwise fall through to the environment and look like it worked.
        Environment: CONNECTOR_CLI_ENV_FILE

  --set KEY=VALUE
        Override one configuration value for this launch. Repeatable, so a
        script can supply several values without exporting them. The pair is
        split on the first =, so a secret may contain one.

        The value is never printed. A rejected pair names the key and not the
        value, because a --set argument may carry a credential and a usage
        error that echoed it would write a secret to stderr.

        The order is: --set beats an environment variable, which beats
        --env-file, which beats .env.local. A value that is empty counts as
        unset at every layer, so an exported but empty variable does not
        shadow a value from the file.

  Flags come before the operation name. Go's flag parser stops at the first
  positional argument, so an operation written before a flag turns that flag
  into a positional argument and the command fails with a message about
  positional arguments rather than about order.

CONFIGURATION
  Every value can come from four places. When a value is set in more than one,
  the first of these wins:

    1. --set KEY=VALUE on the command line
    2. an environment variable in the process environment
    3. a KEY=VALUE pair in the configuration file
    4. the built-in default, where one exists

  --set wins over the environment because it is typed for this one launch, while
  an environment variable is ambient and inherited by every process the shell
  starts. The environment wins over the file because the file is a default for
  this installation, and a caller who exported a value meant it for this one
  command. A value that is empty counts as unset at every layer, so an exported
  but empty variable does not shadow a value from the file.

  A dedicated flag such as --server or --node-id is the same layer as --set and
  is read first, so --server wins over --set CONNECTOR_CLI_SERVER_URL. Use the
  dedicated flag when one exists; --set is for a value that has no flag, and for
  a script that already holds its configuration as KEY=VALUE pairs.

  The configuration file is named .env.local and is read from the directory that
  holds this executable. It is optional: when it is absent the program runs on
  the process environment alone. When it is present and malformed, the program
  refuses to run rather than ignoring the bad line, because a configuration that
  is half-read is a configuration nobody can reason about.

  The file holds one KEY=VALUE per line. A line starting with # is a comment, an
  optional export prefix is accepted, and one matching pair of surrounding
  quotes is removed. Nothing is expanded, so a value is exactly the bytes
  written after the =.

  Set CONNECTOR_CLI_ENV_FILE, or pass --env-file PATH, to read a different file
  instead. This is useful when the executable lives somewhere its configuration
  must not, and it is the way to keep credentials outside a directory that a
  build step deletes. A file named by --env-file must exist, because a typo
  would otherwise fall through to the environment and look like it worked. The
  default .env.local may be absent, which is the ordinary case.

  The file holds credentials, so it must not be readable by other accounts. The
  program warns when it is readable by group or others.

EXIT STATUS
  0   The operation succeeded.
  1   The request failed: a refusal from the Server or the Node, a transport
      failure, or a local write failure.
  2   The command line was rejected before anything was sent.

  A message beginning "usage:" always accompanies status 2, so a script can tell
  a rejected command line from a refused request without parsing the text.

ERROR CODES
  A failed request prints the code and the message to stderr. The code is stable
  and is what a script should match on.

  invalid_argument        the request is malformed
  unauthenticated         the caller is not authenticated
  node_offline            the Node is not connected
  node_timeout            the Node did not answer in time
  denied                  the Node refused the operation
  not_found               the path does not exist inside the scope
  unsupported_operation   the operation is not enabled
  too_large               the request or the response is too large
  overloaded              the Server is at its admission limit and refused the
                          request instead of queueing it
  internal                the Node or the Server failed

  node_offline, node_timeout, overloaded and internal are worth retrying. The
  others are refusals, and retrying a refusal turns a policy decision into a
  load problem.

EXAMPLES
  Read a file, using the configuration file for every credential:

    {{program}} --scope project --path notes.md file.read

  List the root of a scope:

    {{program}} --scope project --path "" file.list

  Report one path:

    {{program}} --scope project --path data.txt file.stat

  Fetch a file larger than the response cap:

    {{program}} --scope project --path big.log -o ./big.log file.read

  Page through a file by hand:

    {{program}} --scope project --path big.log --offset 0 --length 65536 file.read

  Override one value for a single call:

    {{program}} --server http://192.168.2.3:8743 --scope project --path notes.md file.read

  Print the envelope for a script:

    {{program}} --scope project --path data.txt --json file.stat

  Ask for help about one operation:

    {{program}} help file.read

SEE ALSO
  docs/API.md in the Connector repository describes the HTTP API this program
  calls, including both proof headers and the response envelope.
`)
}

// operationHelpText renders the help for one operation.
//
// It exists because the full help is long, and a caller who already knows the
// flags wants the grammar of one operation rather than all of them. An unknown
// operation is refused with the list of accepted names, so a typo is answered
// with the correct spelling instead of with a generic usage line.
func operationHelpText(program string, operation string) string {
	switch operation {
	case "file.list":
		return replaceProgram(program, `NAME
  {{program}} file.list - list one directory inside a scope

SYNOPSIS
  {{program}} [FLAGS] --scope NAME --path PATH file.list

DESCRIPTION
  Lists the immediate entries of one directory inside a scope. It does not
  recurse, so each deeper level must be named explicitly.

  The output is one line per entry, with the name, the type and the size
  separated by tabs:

    data.txt	file	16
    notes.md	file	48

  A directory is reported with the type directory. A symlink is reported as a
  link and is not followed.

  Use an empty --path to list the scope root:

    {{program}} --scope project --path "" file.list

  A dot is not accepted as a path component, so --path . is refused rather than
  normalised. The empty value is the documented way to address the root.

  An entry that resolves to the Node's own configuration directory is omitted
  rather than reported, so the names and sizes of the credential files are not
  disclosed.

  Requires the list permission on the scope. Without it the Node answers denied.

EXIT STATUS
  0   The directory was listed. An empty directory prints nothing and exits 0.
  1   The request failed. See the error codes in {{program}} --help.
  2   The command line was rejected.

EXAMPLE
  {{program}} --scope project --path "" file.list
  {{program}} --scope project --path subdir file.list
`)
	case "file.stat":
		return replaceProgram(program, `NAME
  {{program}} file.stat - report metadata of one path inside a scope

SYNOPSIS
  {{program}} [FLAGS] --scope NAME --path PATH file.stat

DESCRIPTION
  Reports the metadata of one path without reading its content. The output is
  one line per field, with the field name and the value separated by a tab:

    name	data.txt
    type	file
    size	16
    mode	-rw-rw-rw-
    modified_at	1795009284259
    is_symlink	false

  link_target is printed only when the path is a symlink.

  A symlink is reported without being followed, so a link that points outside
  the scope is still reportable. Following it is the operation the fence
  refuses, and this operation does not perform it.

  A symlink that resolves to the Node's own configuration directory is refused
  rather than reported. Reporting it would disclose the length of its target,
  which answers the question the refusal is meant to refuse.

  modified_at is a Unix timestamp in milliseconds.

  Requires the stat permission on the scope.

EXIT STATUS
  0   The metadata was reported.
  1   The request failed. See the error codes in {{program}} --help.
  2   The command line was rejected.

EXAMPLE
  {{program}} --scope project --path data.txt file.stat
  {{program}} --scope project --path data.txt --json file.stat
`)
	case "file.read":
		return replaceProgram(program, `NAME
  {{program}} file.read - read a byte range of one file inside a scope

SYNOPSIS
  {{program}} [FLAGS] --scope NAME --path PATH [--offset N] [--length N] file.read
  {{program}} [FLAGS] --scope NAME --path PATH -o DEST [--force] file.read

DESCRIPTION
  Reads a file and writes its content to stdout as raw bytes, so the output can
  be piped or redirected without any text conversion.

  A single response is capped at 256 KiB. Without -o the program sends exactly
  one request, so a file larger than the cap is returned in part and a notice is
  written to stderr:

    content truncated at 262144 bytes

  The notice goes to stderr rather than stdout so it cannot corrupt a piped
  payload. A caller that redirected stdout to a file and ignored stderr would
  keep a partial file, which is why -o exists.

  With -o the program repeats the request until the Node reports end of file, so
  the whole file is fetched however large it is. Each chunk is a separately
  signed request with its own nonce and timestamp, so the loop needs no protocol
  change.

  --offset and --length select a byte range. Both count bytes, not characters.
  --length 0 means up to the cap. An offset past the end of the file returns
  empty output and exits 0.

  Only a regular file can be read. A directory, a fifo or a device file is
  refused with invalid_argument, because reading one either fails or blocks.

  Requires the read permission on the scope.

EXIT STATUS
  0   The content was read.
  1   The request failed, or the local write was refused. See the error codes in
      {{program}} --help.
  2   The command line was rejected.

EXAMPLE
  {{program}} --scope project --path notes.md file.read
  {{program}} --scope project --path big.log -o ./big.log file.read
  {{program}} --scope project --path big.log --offset 0 --length 65536 file.read
  {{program}} --scope project --path notes.md -o - file.read
`)
	default:
		return replaceProgram(program, `NAME
  {{program}} help - print help for this program or for one operation

SYNOPSIS
  {{program}} help
  {{program}} help OPERATION

DESCRIPTION
  With no argument, prints the complete help: every flag, every environment
  variable, the precedence between them, where the configuration file is looked
  for, every operation, every error code and every exit status.

  With an operation name, prints the help for that operation only.

  The accepted operation names are file.list, file.stat and file.read.

EXIT STATUS
  0   The help was printed.
  2   The named operation is not one this program accepts.

EXAMPLE
  {{program}} help
  {{program}} help file.read
`)
	}
}

// versionText renders the build version.
//
// The value comes from the module build information rather than from a constant,
// so it describes the binary that is running. A hand-maintained constant drifts
// from the build the first time someone forgets to bump it, and a version that
// is wrong is worse than no version at all.
func versionText(program string) string {
	version := "(unknown)"
	if info, ok := debug.ReadBuildInfo(); ok {
		if info.Main.Version != "" && info.Main.Version != "(devel)" {
			version = info.Main.Version
		} else {
			version = "devel"
		}
		for _, setting := range info.Settings {
			if setting.Key == "vcs.revision" && setting.Value != "" {
				revision := setting.Value
				if len(revision) > 12 {
					revision = revision[:12]
				}
				version += " (" + revision + ")"
				break
			}
		}
	}
	return fmt.Sprintf("%s %s\n", program, version)
}

// replaceProgram substitutes the program name into a help text.
func replaceProgram(program string, text string) string {
	return strings.ReplaceAll(text, programPlaceholder, program)
}
