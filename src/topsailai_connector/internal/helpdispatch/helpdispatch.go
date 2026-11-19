// Package helpdispatch answers the informational forms of a command line:
// `--help`, `-h`, `--version` and the `help` subcommand.
//
// It exists because connector-node and connector-server need the same rule, and two
// copies of one rule drift apart. The package is IO-free: it returns the text and the
// status, and the caller decides which stream to write to. That keeps it usable from
// both binaries without either of them importing the other's code.
package helpdispatch

import "strings"

// Catalog is the set of pages one binary can print.
type Catalog struct {
	// Main is the text printed for a bare help request.
	Main string
	// Version is the text printed for --version.
	Version string
	// Pages maps a subcommand path to its text. A path is the words a caller types,
	// joined by a single space, so "credential add" is one key.
	Pages map[string]string
	// Commands lists the subcommand paths this binary accepts, in the order they
	// should be offered in a refusal. It is separate from Pages because a command may
	// have no page of its own while still being a command.
	Commands []string
	// ValueFlags names the flags that consume the following token. A help token
	// directly after one of these is that flag's value, not a help request, so
	// `credential add --key-id --help` names a key id rather than asking for help.
	ValueFlags []string
}

// Result is the answer to an informational request.
type Result struct {
	// Handled reports whether the command line was an informational request. When it
	// is false the caller must parse the arguments and run the subcommand.
	Handled bool
	// Status is the exit status to return when Handled is true.
	Status int
	// Stdout is the text to write to standard output.
	Stdout string
	// Stderr is the text to write to standard error.
	Stderr string
}

// Resolve answers an informational request, or reports that there is none.
//
// The order of the checks is the order of explicitness. A flag is the more explicit
// form, so `--help help` prints the main help rather than the help for `help`. The
// `help` subcommand is checked second because it is a positional form.
//
// A help request is answered with status 0, because it succeeded at what it asked for.
// A `help` naming something this binary does not offer is status 2, because the request
// named something that does not exist, and a caller that received 0 would believe the
// name was valid.
func Resolve(program string, arguments []string, catalog Catalog) Result {
	if flag, found := informationalFlag(arguments, catalog.ValueFlags); found {
		switch flag {
		case "version":
			return Result{Handled: true, Status: 0, Stdout: catalog.Version}
		default:
			return Result{Handled: true, Status: 0, Stdout: pageFor(program, arguments, catalog)}
		}
	}

	if len(arguments) == 0 || arguments[0] != "help" {
		return Result{}
	}

	rest := arguments[1:]
	if len(rest) == 0 {
		return Result{Handled: true, Status: 0, Stdout: catalog.Main}
	}
	if len(rest) > 1 {
		return Result{
			Handled: true,
			Status:  2,
			Stderr:  usageLine(program, catalog),
		}
	}

	name := rest[0]
	if name == "help" {
		return Result{Handled: true, Status: 0, Stdout: catalog.Main}
	}
	if text, ok := catalog.Pages[name]; ok {
		return Result{Handled: true, Status: 0, Stdout: text}
	}
	return Result{
		Handled: true,
		Status:  2,
		Stderr:  unknownCommandLine(program, name, catalog),
	}
}

// informationalFlag reports which informational flag was written, if any.
//
// A token is a flag only when it is not the value of the flag before it. Without that
// check, `credential add --key-id --help` would print the help instead of naming a key
// id, which is the same defect the CLI had with `--path --help`: a scan of the argument
// text cannot tell a flag from a value, and the answer then comes from a string
// comparison rather than from the grammar.
func informationalFlag(arguments []string, valueFlags []string) (string, bool) {
	for index, argument := range arguments {
		if index > 0 && takesValue(arguments[index-1], valueFlags) {
			continue
		}
		switch argument {
		case "-h", "--help":
			return "help", true
		case "--version":
			return "version", true
		}
	}
	return "", false
}

// takesValue reports whether a token consumes the token after it.
func takesValue(token string, valueFlags []string) bool {
	for _, name := range valueFlags {
		if token == name {
			return true
		}
	}
	return false
}

// pageFor returns the most specific page the arguments name.
//
// The subcommand path is read from the leading positional words, so `run --help` prints
// the page for `run` and a bare `--help` prints the main page. The longest matching
// path wins, so `credential add --help` prints the page for `credential add` rather than
// the page for `credential`.
func pageFor(program string, arguments []string, catalog Catalog) string {
	words := positionalWords(arguments, catalog.ValueFlags)
	for length := len(words); length > 0; length-- {
		key := strings.Join(words[:length], " ")
		if text, ok := catalog.Pages[key]; ok {
			return text
		}
	}
	return catalog.Main
}

// positionalWords returns the leading words that are neither flags nor flag values.
//
// Only the leading run is returned, because a subcommand path is a prefix of the
// command line. A word after the first flag is not part of a path, so `run --help` and
// `--help run` both resolve to `run` only when `run` is the leading word.
func positionalWords(arguments []string, valueFlags []string) []string {
	words := make([]string, 0, len(arguments))
	for index := 0; index < len(arguments); index++ {
		argument := arguments[index]
		if strings.HasPrefix(argument, "-") {
			if takesValue(argument, valueFlags) {
				index++
			}
			continue
		}
		words = append(words, argument)
	}
	return words
}

// usageLine is the refusal for a `help` with too many words.
func usageLine(program string, catalog Catalog) string {
	return program + ": usage: " + program + " help [" + strings.Join(catalog.Commands, "|") + "]\n"
}

// unknownCommandLine is the refusal for a `help` naming something that does not exist.
func unknownCommandLine(program string, name string, catalog Catalog) string {
	return program + ": usage: " + program + " has no subcommand " + quote(name) +
		"; want " + strings.Join(catalog.Commands, ", ") + "\n"
}

// quote wraps a value in double quotes, so a name containing a space is visible.
func quote(value string) string {
	return "\"" + value + "\""
}
