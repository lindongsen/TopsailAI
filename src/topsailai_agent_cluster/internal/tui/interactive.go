package tui

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// InteractiveAPI is defined as the shared CommandAPI alias in commands.go.

// InteractiveOptions controls bounded REPL behavior.
type InteractiveOptions struct {
	MaxBytes      int
	WaitTimeoutMS int64
	LineLimit     int
	Color         ColorPolicy
}

type reportLoad struct {
	endpoints []protocol.Endpoint
	reports   map[string]protocol.InventoryReport
	errors    map[string]error
}

type interactiveState struct {
	interactiveSelection
	commandID string
}

// RunInteractive executes the stream-driven operator REPL.
func RunInteractive(parent context.Context, api InteractiveAPI, input io.Reader, output, errors io.Writer, options InteractiveOptions) error {
	if api == nil {
		return fmt.Errorf("interactive API is unavailable")
	}
	if input == nil || output == nil || errors == nil {
		return fmt.Errorf("interactive streams are unavailable")
	}
	if options.MaxBytes <= 0 {
		options.MaxBytes = 64 << 10
	}
	if options.LineLimit <= 0 {
		options.LineLimit = 64 << 10
	}
	out := newSafeWriter(output)
	errOut := newSafeWriter(errors)
	reader := bufio.NewReaderSize(input, options.LineLimit+1)
	state := interactiveState{}
	for {
		if err := writePrompt(output, state, options.Color); err != nil {
			return err
		}
		line, overflow, err := readLine(reader, options.LineLimit)
		if err != nil {
			if err == io.EOF {
				if line == "" {
					return nil
				}
			} else {
				return err
			}
		}
		if overflow {
			if _, writeErr := fmt.Fprintln(errOut, "input line exceeds the maximum length"); writeErr != nil {
				return writeErr
			}
			continue
		}
		line = strings.TrimSpace(strings.TrimSuffix(line, "\r"))
		if line == "" {
			if err == io.EOF {
				return nil
			}
			continue
		}
		exit, execErr := executeInteractiveLine(parent, api, &state, line, reader, out, output, errOut, options)
		if execErr != nil {
			if _, writeErr := fmt.Fprintln(errOut, "error:", execErr); writeErr != nil {
				return writeErr
			}
		}
		if exit {
			return nil
		}
		if err == io.EOF {
			return nil
		}
	}
}

func executeInteractiveLine(ctx context.Context, api InteractiveAPI, state *interactiveState, line string, reader *bufio.Reader, out, trustedOut, errOut io.Writer, options InteractiveOptions) (bool, error) {
	name, rest := splitCommand(line)
	switch name {
	case "help", "?":
		return false, printHelp(out)
	case "quit", "exit":
		if strings.TrimSpace(rest) != "" {
			return false, fmt.Errorf("usage: %s", name)
		}
		return true, nil
	case "list":
		return false, interactiveList(ctx, api, strings.TrimSpace(rest), out)
	case "table":
		return false, interactiveTable(ctx, api, strings.TrimSpace(rest), trustedOut, errOut, options.Color)
	case "use":
		return false, interactiveUse(ctx, api, state, rest)
	case "show":
		return false, interactiveShow(ctx, api, state, strings.TrimSpace(rest), out)
	case "logs":
		return false, interactiveLogs(ctx, api, state, strings.TrimSpace(rest), options.MaxBytes, out)
	case "status":
		return false, interactiveStatus(ctx, api, state, strings.TrimSpace(rest), out)
	case "refresh":
		return false, interactiveRefresh(ctx, api, state, out)
	case "send":
		return false, interactiveSend(ctx, api, state, rest, reader, out, options)
	default:
		return false, fmt.Errorf("unknown command %q (try help)", name)
	}
}

func splitCommand(line string) (string, string) {
	parts := strings.SplitN(strings.TrimSpace(line), " ", 2)
	name := parts[0]
	if len(parts) == 1 {
		return name, ""
	}
	return name, parts[1]
}

func readLine(reader *bufio.Reader, limit int) (string, bool, error) {
	line, err := reader.ReadString('\n')
	if len(line) > limit {
		for err == nil && !strings.HasSuffix(line, "\n") {
			var discarded string
			discarded, err = reader.ReadString('\n')
			if strings.HasSuffix(discarded, "\n") {
				break
			}
		}
		return "", true, nil
	}
	return strings.TrimSuffix(line, "\n"), false, err
}

func writePrompt(out io.Writer, state interactiveState, policy ColorPolicy) error {
	return RenderPrompt(out, state.EndpointID, state.SessionID, state.Invalidated, policy)
}

func printHelp(out io.Writer) error {
	_, err := fmt.Fprintln(out, "commands: list [endpoint], table [endpoint], use <endpoint> <session>, show, logs, send <json>, status, refresh, help, quit")
	return err
}

func commandContext(parent context.Context) (context.Context, context.CancelFunc) {
	return context.WithTimeout(parent, 10*time.Second)
}

func loadReports(ctx context.Context, api InteractiveAPI, endpointFilter string) (reportLoad, error) {
	endpoints, err := api.ListEndpoints(ctx)
	if err != nil {
		return reportLoad{}, err
	}
	loaded := reportLoad{endpoints: endpoints, reports: make(map[string]protocol.InventoryReport), errors: make(map[string]error)}
	for _, endpoint := range endpoints {
		if endpointFilter != "" && endpoint.EndpointID != endpointFilter {
			continue
		}
		report, fetchErr := api.GetInventory(ctx, endpoint.EndpointID)
		if fetchErr != nil {
			loaded.errors[endpoint.EndpointID] = fetchErr
			continue
		}
		loaded.reports[endpoint.EndpointID] = report
	}
	return loaded, nil
}

func interactiveTable(parent context.Context, api InteractiveAPI, filter string, out, errors io.Writer, color ColorPolicy) error {
	ctx, cancel := commandContext(parent)
	defer cancel()
	return (CommandRunner{API: api, Policy: InteractivePolicy}).Table(ctx, out, errors, filter, false, TableOptions{Color: color})
}

func interactiveList(parent context.Context, api InteractiveAPI, filter string, out io.Writer) error {
	ctx, cancel := commandContext(parent)
	defer cancel()
	return (CommandRunner{API: api, Policy: InteractivePolicy}).List(ctx, out, filter, false)
}

func findSelected(ctx context.Context, api InteractiveAPI, state *interactiveState) (protocol.Endpoint, protocol.InventoryReport, *protocol.Session, error) {
	if err := state.requireUsable(); err != nil {
		return protocol.Endpoint{}, protocol.InventoryReport{}, nil, err
	}
	loaded, err := loadReports(ctx, api, state.EndpointID)
	if err != nil {
		return protocol.Endpoint{}, protocol.InventoryReport{}, nil, err
	}
	for _, endpoint := range loaded.endpoints {
		if endpoint.EndpointID != state.EndpointID {
			continue
		}
		report, ok := loaded.reports[endpoint.EndpointID]
		if !ok || !report.ReportComplete || report.CollectionStatus != protocol.CollectionSucceeded {
			return protocol.Endpoint{}, protocol.InventoryReport{}, nil, fmt.Errorf("endpoint %q inventory is unavailable", state.EndpointID)
		}
		for index := range report.Sessions {
			if report.Sessions[index].SessionID != state.SessionID {
				continue
			}
			session := &report.Sessions[index]
			if session.Generation == "" || session.Generation != state.Generation {
				state.invalidate("selected session generation changed")
				return protocol.Endpoint{}, protocol.InventoryReport{}, nil, fmt.Errorf("selected session generation changed; use the session again")
			}
			return endpoint, report, session, nil
		}
	}
	return protocol.Endpoint{}, protocol.InventoryReport{}, nil, fmt.Errorf("selected session %q was not found", state.SessionID)
}

func interactiveUse(parent context.Context, api InteractiveAPI, state *interactiveState, rest string) error {
	args := strings.Fields(rest)
	if len(args) == 1 && args[0] == "clear" {
		*state = interactiveState{}
		return nil
	}
	if len(args) != 2 {
		return fmt.Errorf("usage: use <endpoint> <session>")
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	loaded, err := loadReports(ctx, api, args[0])
	if err != nil {
		return err
	}
	for _, endpoint := range loaded.endpoints {
		report, ok := loaded.reports[endpoint.EndpointID]
		if endpoint.EndpointID != args[0] || !ok || !report.ReportComplete || report.CollectionStatus != protocol.CollectionSucceeded {
			continue
		}
		for _, session := range report.Sessions {
			if session.SessionID == args[1] && session.Generation != "" {
				state.reset(args[0], args[1], session.Generation)
				return nil
			}
		}
	}
	return fmt.Errorf("session %q was not found on endpoint %q", args[1], args[0])
}

func interactiveRefresh(parent context.Context, api InteractiveAPI, state *interactiveState, out io.Writer) error {
	if state.EndpointID == "" {
		return interactiveList(parent, api, "", out)
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	_, _, session, err := findSelected(ctx, api, state)
	if err != nil {
		return err
	}
	_ = session
	return nil
}

func interactiveShow(parent context.Context, api InteractiveAPI, state *interactiveState, id string, out io.Writer) error {
	if state.Invalidated {
		return state.requireUsable()
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	if id == "" {
		if err := state.requireUsable(); err != nil {
			return err
		}
		_, _, session, err := findSelected(ctx, api, state)
		if err != nil {
			return err
		}
		id = session.SessionID
	}
	return (CommandRunner{API: api, Policy: InteractivePolicy}).Show(ctx, out, id, false)
}
