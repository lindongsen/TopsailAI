// Command connector-node is the personal-computer entry point. It dials the Server,
// keeps the link open and serves the operations its policy allows.
//
// The process loads the configuration, loads the policy, opens every scope the policy
// defines, prepares the node identity and its credentials, and then dials the Server.
// It never listens: the Node is the side that initiates, so a personal computer needs
// no inbound port, no public address and no firewall change.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"topsailai_connector/internal/helpdispatch"
	"topsailai_connector/internal/node"
	"topsailai_connector/internal/nodehelp"
	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

func main() {
	os.Exit(exitStatus(run(os.Args[1:])))
}

// exitStatus maps the result of run to a process exit status.
//
// The mapping lives here rather than inside run so run can stay a function that returns
// an error, which is what makes it testable. The three statuses are the ones the help
// text promises: 0 for success, 1 for a failure, 2 for a command line that was rejected
// before anything was done. A usage error must be 2 and not 1, because the message
// begins with "usage:" and a script branches on the status rather than on the text.
func exitStatus(err error) int {
	if err == nil {
		return 0
	}

	// A refusal that already wrote its own message carries only a status, so it must not
	// be printed again. Printing it twice would show the operator the same sentence in
	// two places and make the second copy look like a second failure.
	var printed *helpdispatch.PrintedError
	if errors.As(err, &printed) {
		return printed.Status
	}

	fmt.Fprintf(os.Stderr, "connector-node: %v\n", err)
	if helpdispatch.IsUsage(err) {
		return 2
	}
	return 1
}

// run is the whole process, separated from main so a test can call it and so every
// failure returns an error instead of calling os.Exit in the middle.
func run(arguments []string) error {
	// The informational forms are answered before the subcommand is split, because
	// `--help` is not a flag of any subcommand: it is a request about the program. Doing
	// it first also means `connector-node --help` works without naming `run`, which is
	// what an operator types when they do not yet know that `run` exists.
	if result := helpdispatch.Resolve(programName, arguments, catalog()); result.Handled {
		if result.Stdout != "" {
			fmt.Fprint(os.Stdout, result.Stdout)
		}
		if result.Stderr != "" {
			fmt.Fprint(os.Stderr, result.Stderr)
		}
		if result.Status != 0 {
			return &helpdispatch.PrintedError{Status: result.Status}
		}
		return nil
	}

	command, rest := splitCommand(arguments)

	switch command {
	case "", "run":
		return runNode(rest)
	case "id":
		return runID(rest)
	case "regenerate":
		return runRegenerate(rest)
	case "credential":
		return runCredential(rest)
	case "scope":
		return runScope(rest)
	default:
		return helpdispatch.Usagef("unknown command %q; want run, id, regenerate, credential or scope", command)
	}
}

// programName is the name used as the prefix of every message and in the help text.
//
// It is a constant rather than the executable's base name, because the help text names
// the program in every synopsis line and a renamed copy would then print a synopsis the
// operator cannot type. The CLI reads its own base name because it is meant to be copied
// and renamed; this binary is installed under one name.
const programName = "connector-node"

// catalog is the set of pages this binary can print.
//
// The command list is the same set splitCommand accepts, and the page keys are the words
// an operator types. Keeping both here means a new subcommand that is added to
// splitCommand without a page is visible in one place rather than discovered by a user
// who asked for help and received the main page.
func catalog() helpdispatch.Catalog {
	return helpdispatch.Catalog{
		Main:    nodehelp.Main(programName),
		Version: helpdispatch.Version(programName),
		Pages: map[string]string{
			"run":               nodehelp.Run(programName),
			"id":                nodehelp.ID(programName),
			"regenerate":        nodehelp.Regenerate(programName),
			"credential":        nodehelp.Credential(programName),
			"credential add":    nodehelp.Credential(programName),
			"credential list":   nodehelp.Credential(programName),
			"credential remove": nodehelp.Credential(programName),
			"scope":             nodehelp.Scope(programName),
			"scope list":        nodehelp.Scope(programName),
		},
		Commands:   []string{"run", "id", "regenerate", "credential", "scope"},
		ValueFlags: []string{"--key-id"},
	}
}

// splitCommand separates the subcommand from its flags.
//
// A leading flag means the default subcommand, so `connector-node --help` works without
// naming `run`. A leading word that is not a known command is returned as the command,
// so `run` reports it as unknown instead of starting the Node: a typo that silently
// starts the default subcommand is a typo an operator never learns about.
func splitCommand(arguments []string) (string, []string) {
	if len(arguments) == 0 {
		return "", nil
	}
	switch arguments[0] {
	case "run", "id", "regenerate", "credential", "scope":
		return arguments[0], arguments[1:]
	}
	if strings.HasPrefix(arguments[0], "-") {
		return "", arguments
	}
	return arguments[0], arguments[1:]
}

// rejectStrayArguments refuses a positional argument that no flag consumed.
//
// flag.Parse accepts a positional argument and leaves it in Args(), so a word that is
// not a flag is silently dropped by a caller that never checks. That is how
// `connector-node run serve` used to start the Node: `serve` was parsed as a positional
// argument, ignored, and the default subcommand ran. A word the operator typed must
// either be a flag or be refused, because a silently ignored word is a typo the operator
// never learns about.
func rejectStrayArguments(flags *flag.FlagSet) error {
	if flags.NArg() == 0 {
		return nil
	}
	return helpdispatch.Usagef("unexpected argument %q; want flags only", flags.Arg(0))
}

// runNode starts the Node: configuration, identity, credentials, policy, scopes, then
// dial.
//
// The order is deliberate. The runtime is opened first, because it loads the identity,
// the credentials and the policy and refuses to start when any of them is unusable; a
// dialer built before that would connect to the Server and then discover it has nothing
// to serve. The dialer is built last, so a Node that cannot serve never appears
// connected.
func runNode(arguments []string) error {
	// The signal channel is created here rather than inside runNodeWithSignals, so the
	// whole process can be tested without sending a signal to the test binary.
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)

	return runNodeWithSignals(arguments, signals)
}

// runNodeWithSignals is runNode with the signal channel supplied by the caller.
//
// The channel is a parameter so a test can drive the complete process, including the
// dial, without signalling the test binary: a real signal would make the test depend on
// the order in which two handlers register, and a mistake there would kill the test
// binary instead of failing the test.
//
// The terminal question is answered here, at the process boundary, because it is a
// property of where stdout points rather than of the Node. A library that decided it
// would be a library that prints a secret when a test happens to run it in a terminal.
func runNodeWithSignals(arguments []string, signals <-chan os.Signal) error {
	return runNodeWithOutput(arguments, signals, os.Stdout, isTerminal(os.Stdout))
}

// runNodeWithOutput is the whole run subcommand with its output stream and its terminal
// status supplied by the caller.
//
// Both are parameters so a test can assert the two forms of the summary without a
// pseudo-terminal: the withheld form is the one that protects a redirected log, and a
// test that could only exercise the terminal form would leave the protective branch
// unmeasured.
func runNodeWithOutput(arguments []string, signals <-chan os.Signal, stdout io.Writer, terminal bool) error {
	flags := flag.NewFlagSet("run", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	// The console is opt-in on a file-backed Node and on by default in stateless mode,
	// because a stateless Node has no file to edit: without a console, `regenerate` and
	// the `credential` subcommands are refused and the operator has no way to change the
	// address or revoke a caller without restarting the process.
	//
	// It is a flag rather than an environment variable because it decides whether the
	// process reads its own stdin, which is a property of how the process was launched
	// rather than of the machine it runs on.
	consoleFlag := flags.Bool("console", false, "read commands from stdin while the node serves")
	// The two configuration sources are flags as well as variables, because the
	// argument layer is the most specific statement an operator can make: it is typed
	// for this one launch, while an environment variable is inherited by every process
	// the shell starts. A source reachable only through the environment would be
	// unreachable for the operator who wants to override the environment.
	envFileFlag := flags.String("env-file", "", "read KEY=VALUE pairs from this dotenv file")
	overrides := overrideFlag{}
	flags.Var(&overrides, "set", "override one configuration value; repeatable, KEY=VALUE")
	// The --set pairs are validated before the flag package sees them, because the
	// package echoes a rejected value verbatim and a --set argument may carry a
	// tunnel token. See validateOverrideArguments.
	if err := validateOverrideArguments(arguments); err != nil {
		return helpdispatch.Usagef("%v", err)
	}
	if err := flags.Parse(arguments); err != nil {
		return helpdispatch.Usagef("%v", err)
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	logger := slog.New(slog.NewTextHandler(os.Stderr, nil))

	// The precedence is decided in one place, before LoadConfig is called, so the order
	// is visible in one function rather than scattered through the resolvers.
	envFilePath, err := resolveEnvFile(*envFileFlag, os.Getenv)
	if err != nil {
		return err
	}
	fileValues, err := loadEnvFile(envFilePath)
	if err != nil {
		return err
	}
	lookup := layeredLookup(overrides, os.Getenv, fileValues)

	config, err := node.LoadConfig(lookup)
	if err != nil {
		return err
	}

	runtime, err := node.Open(config, logger)
	if err != nil {
		return err
	}
	defer runtime.Close()

	logger.Info("connector-node starting", "protocol", protocol.Version)

	// The summary is printed on every start, not only the first, because an operator who
	// restarts a Node has the same question as one who started it: what do I put in the
	// CLI. It goes to stdout rather than to the log, so a log file does not accumulate
	// credentials, and the secret inside it is printed in full only when a human is
	// watching the terminal.
	//
	// The wording is "written", not "generated", because a build that embedded an
	// identity and a credential seeds them instead of generating them. Claiming a
	// random generation would be false for exactly the build whose operator most needs
	// to know where the values came from: the one that shipped the artifact.
	//
	// A stateless Node writes nothing, so the same sentence would be false in the other
	// direction: it would tell the operator to look for a file the mode exists to avoid
	// creating. The mode is named instead, and the sentence says where the value lives.
	// The distinction is not cosmetic. "Written" is a claim about the filesystem, and a
	// claim about the filesystem has to be true on the machine it is printed on.
	if _, created := runtime.NewIdentity(); created {
		if config.Stateless {
			fmt.Fprintln(stdout, "a new node id was created in memory by this start")
		} else {
			fmt.Fprintln(stdout, "a new node id was written by this start")
		}
	}
	if credential := runtime.NewCredential(); credential != nil {
		if config.Stateless {
			fmt.Fprintln(stdout, "a new credential was created in memory by this start")
		} else {
			fmt.Fprintln(stdout, "a new credential was written by this start")
		}
	}
	if err := printStartupSummary(stdout, runtime, terminal); err != nil {
		return err
	}
	runtime.Report()

	ctx, stop := contextFromSignals(signals)
	defer stop()
	// A stateless Node turns the console on by itself, because it has no file to edit and
	// the file-backed subcommands are refused in that mode. A file-backed Node keeps the
	// behaviour it had before the console existed: no console unless the operator asked
	// for one.
	console := consoleFor(runtime, stdout, *consoleFlag, terminal)
	return serveNodeWithConsole(ctx, runtime, logger, console)
}

// consoleFor builds the console the run subcommand should attach, or nil for none.
//
// The prompt is written only when stdout is a terminal. A prompt in a redirected log is
// noise that reads like output, and a log that mixes prompts with the startup summary is
// a log an operator cannot paste into a ticket without editing it first.
//
// The console is attached when the operator asked for it, or when the Node is stateless
// and stdin is a terminal. The second condition is what makes a stateless Node usable at
// all: it has no file to edit, so a console is the only way to change its address or
// revoke a caller. It is conditioned on a terminal because a stateless Node started by a
// service manager has no stdin to read, and a console that consumed a pipe would be a
// console that ate the launcher's input.
func consoleFor(runtime *node.Runtime, stdout io.Writer, requested bool, terminal bool) *node.Console {
	if !requested && !(runtime.Config().Stateless && terminal) {
		return nil
	}
	console := node.NewConsole(runtime, stdout, nil, nil)
	if terminal {
		console.Prompt = "connector-node> "
	}
	return console
}

// serveNode builds the dispatcher and the dialer and serves until the context ends.
//
// The context is a parameter so a test can drive the whole tail of the process without
// signalling the test binary.
//
// The identity comes from the runtime's holder rather than from a second read of the
// file, so the value the dialer validates is the value the deny list was built from. The
// holder is shared with the dispatcher, so an identifier regenerated while the Node runs
// is adopted by both components at once: the dialer announces the new identity and the
// dispatcher checks requests against it.
func serveNode(ctx context.Context, runtime *node.Runtime, logger *slog.Logger) error {
	return serveNodeWithConsole(ctx, runtime, logger, nil)
}

// serveNodeWithConsole is serveNode with an optional console attached.
//
// The console is a parameter rather than a field on the runtime because it is a process
// concern: a library that started reading a terminal would be a library that consumes
// the caller's input. A nil console means the Node serves without one, which is the
// behaviour every existing deployment has.
//
// The console is given the dialer's RequestIdentityChange, so `regenerate id` drops the
// live channel exactly as a file-backed regeneration does. A stateless Node has no
// identity file for the watcher to poll, so this is the only path by which a new address
// reaches the dialer.
func serveNodeWithConsole(ctx context.Context, runtime *node.Runtime, logger *slog.Logger, console *node.Console) error {
	holder := runtime.IdentityHolder()
	config := runtime.Config()

	dispatcher, err := node.NewDispatcher(runtime.Authority(), holder, config.ReplayWindow, config.ReplayCapacity, logger)
	if err != nil {
		return err
	}

	dialer, err := node.NewDialerWithHolder(config, holder, dispatcher, logger)
	if err != nil {
		return err
	}

	if console != nil {
		// The callback is installed here rather than passed to NewConsole, because the
		// dialer does not exist when the console is built. Without it `regenerate id`
		// would change the identity in memory and leave the live channel authenticated
		// under the retired one, which is the state the file-backed path avoids by
		// dropping the channel.
		console.SetIdentityChangeRequest(dialer.RequestIdentityChange)

		// The console runs beside the dialer rather than before it, so a Node that is
		// serving can still be inspected and re-addressed. It stops when the context
		// ends, which is the same signal that stops the dialer.
		go func() {
			if err := console.Run(ctx, os.Stdin); err != nil {
				logger.Warn("console ended", "error", err)
			}
		}()
	}

	return dialer.Run(ctx)
}

// contextFromSignals returns a context cancelled when a signal arrives on the channel,
// plus the cancel function that releases the watcher.
//
// The channel is a parameter so a test can deliver a signal without signalling the test
// process: a real signal would make the test depend on the order in which two handlers
// register, and a mistake there would kill the test binary instead of failing the test.
func contextFromSignals(signals <-chan os.Signal) (context.Context, context.CancelFunc) {
	ctx, cancel := context.WithCancel(context.Background())

	go func() {
		select {
		case <-signals:
			cancel()
		case <-ctx.Done():
		}
	}()

	return ctx, cancel
}

// refuseInStatelessMode stops a subcommand that would write a file.
//
// `id`, `regenerate` and the three `credential` subcommands all work by reading or
// rewriting the identity file and the credential file. A stateless Node has neither, so
// the commands have nothing to act on. They are refused rather than silently turned into
// in-memory operations, because a command whose meaning depends on an environment
// variable is the hardest kind of defect to diagnose: the same command would change the
// address of a file-backed Node and change nothing on a stateless one, and the operator
// would have no way to tell which happened.
//
// The refusal runs before the config directory is resolved, because resolving one
// creates it. A check placed after that call would have created the directory the mode
// exists to avoid, and the refusal would arrive after the damage.
func refuseInStatelessMode(command string) error {
	stateless, err := node.StatelessRequested(os.Getenv)
	if err != nil {
		return err
	}
	if !stateless {
		return nil
	}
	return fmt.Errorf("%s writes the node's identity and credential files, and CONNECTOR_NODE_STATELESS=1 means this node has neither; use the interactive console instead, which changes the node id and the credentials in memory", command)
}

// runID prints the node id and nothing else, so it can be copied into a script.
//
// Only the config directory is resolved, not the whole configuration. `id` never dials,
// so requiring a dial target or a tunnel token would make the documented first-run order
// impossible: the operator is told to run `id` before the tunnel token is configured,
// and a full configuration load refuses that order. The dial path keeps its own strict
// load, because a Node that started without a secret would be a Node whose operator
// believes it is serving something it is not.
func runID(arguments []string) error {
	flags := flag.NewFlagSet("id", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	if err := flags.Parse(arguments); err != nil {
		return helpdispatch.Usagef("%v", err)
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	if err := refuseInStatelessMode("id"); err != nil {
		return err
	}

	configDir, err := node.ResolveConfigDir(os.Getenv)
	if err != nil {
		return err
	}

	nodeID, _, err := node.EnsureIdentity(node.IdentityPath(configDir))
	if err != nil {
		return err
	}

	fmt.Println(nodeID)
	return nil
}

// runRegenerate replaces the identity file with a fresh node id and prints it.
//
// Regeneration changes the address, not the credential. The credentials the Node accepts
// live in a separate file, so regenerating the identifier does not revoke a caller, and
// revoking a caller does not change the address. Regeneration is local and
// operator-initiated: the Server cannot trigger it, because a Server that could force
// regeneration could also force a denial of service.
func runRegenerate(arguments []string) error {
	flags := flag.NewFlagSet("regenerate", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	if err := flags.Parse(arguments); err != nil {
		return helpdispatch.Usagef("%v", err)
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	if err := refuseInStatelessMode("regenerate"); err != nil {
		return err
	}

	// Only the config directory is resolved, for the same reason as `id`: regeneration
	// rewrites the identity file and never dials, so requiring a dial target or a tunnel
	// token would make a local address change depend on a Server the operator may not
	// have configured yet.
	configDir, err := node.ResolveConfigDir(os.Getenv)
	if err != nil {
		return err
	}

	nodeID, err := node.RegenerateIdentity(node.IdentityPath(configDir))
	if err != nil {
		return err
	}

	fmt.Println(nodeID)
	return nil
}

// runCredential manages the credentials this Node accepts.
//
// The subcommand exists because the credential file is the only place a caller is
// authorized to talk to this Node, and an operator who must hand-edit a YAML file to add
// a caller will eventually hand-edit it wrong. The commands are deliberately small: add
// one credential, list the public key identifiers, and remove one. Rotation is
// add-then-remove, which is the only order that does not lock a caller out between two
// commands.
func runCredential(arguments []string) error {
	if len(arguments) == 0 {
		return helpdispatch.Usagef("credential needs a subcommand: add, list or remove")
	}
	subcommand := arguments[0]
	rest := arguments[1:]

	switch subcommand {
	case "add":
		return runCredentialAdd(rest)
	case "list":
		return runCredentialList(rest)
	case "remove":
		return runCredentialRemove(rest)
	default:
		return helpdispatch.Usagef("unknown credential subcommand %q; want add, list or remove", subcommand)
	}
}

// runCredentialAdd generates a credential and appends it to the file.
//
// The generated credential is printed once. It is the only moment the secret exists
// outside the file, so the operator must copy it into the CLI before the command's output
// is lost.
func runCredentialAdd(arguments []string) error {
	flags := flag.NewFlagSet("credential add", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	keyID := flags.String("key-id", "", "public key id to name the credential; empty generates one")
	if err := flags.Parse(arguments); err != nil {
		return helpdispatch.Usagef("%v", err)
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	if err := refuseInStatelessMode("credential add"); err != nil {
		return err
	}

	configDir, err := node.ResolveConfigDir(os.Getenv)
	if err != nil {
		return err
	}
	path := node.CredentialsPath(configDir)

	credentials, err := node.LoadCredentialList(path)
	if err != nil && !errors.Is(err, node.ErrCredentialsMissing) {
		return err
	}

	var created security.Credential
	if *keyID == "" {
		created, err = security.NewCredential()
	} else {
		created, err = security.NewCredentialWithKeyID(*keyID)
	}
	if err != nil {
		return err
	}
	credentials = append(credentials, created)

	if err := node.SaveCredentials(path, credentials); err != nil {
		return err
	}

	fmt.Println(created.String())
	return nil
}

// runCredentialList prints the public key identifiers.
//
// It never prints a secret. An operator who needs the secret has lost it, and the answer
// is to add a new credential rather than to recover the old one: a file that could print
// a secret is a file that can leak one.
func runCredentialList(arguments []string) error {
	flags := flag.NewFlagSet("credential list", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	if err := flags.Parse(arguments); err != nil {
		return helpdispatch.Usagef("%v", err)
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	if err := refuseInStatelessMode("credential list"); err != nil {
		return err
	}

	configDir, err := node.ResolveConfigDir(os.Getenv)
	if err != nil {
		return err
	}

	credentials, err := node.LoadCredentials(node.CredentialsPath(configDir))
	if err != nil {
		return err
	}
	for _, keyID := range credentials.KeyIDs() {
		fmt.Println(keyID)
	}
	return nil
}

// runScope dispatches the scope subcommand.
//
// There is one subcommand today, and it is still a subcommand rather than a bare
// `scope` command because the word names a noun: an operator who types `scope` is
// asking about scopes, not asking for a listing, and a future `scope show` would
// have nowhere to go if `scope` itself printed the list.
func runScope(arguments []string) error {
	if len(arguments) == 0 {
		return helpdispatch.Usagef("scope needs a subcommand: list")
	}
	subcommand := arguments[0]
	rest := arguments[1:]

	switch subcommand {
	case "list":
		return runScopeList(rest)
	default:
		return helpdispatch.Usagef("unknown scope subcommand %q; want list", subcommand)
	}
}

// runScopeList prints the scope names the policy defines, one per line.
//
// It exists because `--scope` is a required argument on every CLI request and the
// only way to learn a scope name was to open the policy file or read a log. The
// caller cannot ask the Node: the Node answers `denied` for an undefined scope and
// for a scope without a grant alike, so a caller cannot probe for names. The
// operator, who owns the policy file, can read the names here instead of opening
// the file by hand.
//
// It prints names and never paths. A name is public and already appears in the
// Node's startup log; a path is the Node's filesystem layout, which the design
// keeps off the wire.
//
// It does not dial the Server and does not need the tunnel token, so it works
// before the first start. It does not open a scope either, so a policy naming a
// directory that does not exist still lists: the names are what the operator
// wrote, and refusing to show them because a directory is absent would hide the
// one thing this command is for.
func runScopeList(arguments []string) error {
	flags := flag.NewFlagSet("scope list", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	if err := flags.Parse(arguments); err != nil {
		return helpdispatch.Usagef("%v", err)
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}

	names, err := node.ListScopeNames(os.Getenv)
	if err != nil {
		return err
	}
	for _, name := range names {
		fmt.Println(name)
	}
	return nil
}

// runCredentialRemove removes one credential by key identifier.
//
// The removal is a rewrite of the file rather than an in-place edit, so a failure leaves
// the previous set in force instead of a half-written file. Removing the last credential
// is refused: a Node with no credential accepts nothing, which looks exactly like a Node
// whose policy denies everything, and an operator who did that by accident would debug
// the policy instead of the credential file.
func runCredentialRemove(arguments []string) error {
	flags := flag.NewFlagSet("credential remove", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	keyID := flags.String("key-id", "", "public key id to remove")
	if err := flags.Parse(arguments); err != nil {
		return helpdispatch.Usagef("%v", err)
	}
	if err := rejectStrayArguments(flags); err != nil {
		return err
	}
	if *keyID == "" {
		return helpdispatch.Usagef("--key-id is required")
	}

	if err := refuseInStatelessMode("credential remove"); err != nil {
		return err
	}

	configDir, err := node.ResolveConfigDir(os.Getenv)
	if err != nil {
		return err
	}
	path := node.CredentialsPath(configDir)

	existing, err := node.LoadCredentialList(path)
	if err != nil {
		return err
	}

	remaining := make([]security.Credential, 0, len(existing))
	found := false
	for _, candidate := range existing {
		if candidate.KeyID == *keyID {
			found = true
			continue
		}
		remaining = append(remaining, candidate)
	}
	if !found {
		return fmt.Errorf("no credential with key id %q", *keyID)
	}
	if len(remaining) == 0 {
		return fmt.Errorf("refusing to remove the last credential; a node with no credential accepts nothing")
	}

	return node.SaveCredentials(path, remaining)
}
