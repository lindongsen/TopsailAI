package main

import (
	"context"
	"fmt"
	"io"

	"topsailai_agent_cluster/internal/client"
)

// selectServerTarget chooses the Server one invocation uses and reports the choice.
//
// It returns the selected target, so the caller builds its client from one
// resolved pair and never from a partially resolved one.
//
// A group of one is returned without probing. That is what keeps an existing
// deployment unchanged: one candidate has nothing to fall back to, so a probe
// could only add a failure mode and a diagnostic line to a configuration that
// already works. It also means the single-profile path never writes sticky state,
// because there is no choice to remember.
//
// Every skip and the final choice are written to diagnostics, never to output.
// A successful walk is otherwise silent, and the operator could not tell "the
// first Server is down" from "the first Server was never configured". Writing to
// diagnostics rather than output keeps a --json document machine-readable.
func selectServerTarget(ctx context.Context, candidates []ServerTarget, stickyPath string, selector client.Selector, diagnostics io.Writer) (ServerTarget, error) {
	if len(candidates) == 0 {
		return ServerTarget{}, fmt.Errorf("no Server is configured")
	}
	if len(candidates) == 1 {
		return candidates[0], nil
	}
	remembered := readStickyProfile(stickyPath)
	ordered := preferSticky(candidates, remembered)
	selection, err := selector.Select(ctx, toServerCandidates(ordered))
	if err != nil {
		return ServerTarget{}, err
	}
	reportSelection(diagnostics, selection, remembered)
	// The remembered Server is recorded only after it answered, so a failed
	// invocation never moves the preference to a Server that was never reached.
	if err := writeStickyProfile(stickyPath, selection.Candidate.Profile); err != nil {
		// A failed write is a diagnostic, not a failure: the request already
		// succeeded, and refusing to report that because a preference file could
		// not be written would turn a working command into a failure.
		if diagnostics != nil {
			_, _ = fmt.Fprintf(diagnostics, "warning: %v\n", err)
		}
	}
	return ServerTarget{Profile: selection.Candidate.Profile, URL: selection.Candidate.URL, Token: selection.Candidate.Token}, nil
}

// toServerCandidates converts the CLI's resolved targets into the selector's
// input type.
//
// The two types are separate because the CLI owns profile resolution and the
// client package owns reachability. Keeping them apart means the client package
// never learns what a profile is, and the CLI never learns how a probe works.
func toServerCandidates(targets []ServerTarget) []client.ServerCandidate {
	candidates := make([]client.ServerCandidate, 0, len(targets))
	for _, target := range targets {
		candidates = append(candidates, client.ServerCandidate{Profile: target.Profile, URL: target.URL, Token: target.Token})
	}
	return candidates
}

// reportSelection names every Server that was skipped and the one that was used.
//
// The skipped entries come first so the operator reads the reason before the
// result. A remembered Server that is no longer configured is reported too,
// because silently ignoring it would leave the operator believing a preference is
// in force when it is not.
func reportSelection(diagnostics io.Writer, selection client.Selection, remembered string) {
	if diagnostics == nil {
		return
	}
	for _, skipped := range selection.Skipped {
		_, _ = fmt.Fprintf(diagnostics, "server %q skipped: %s\n", skipped.Profile, skipped.Reason)
	}
	if remembered != "" && remembered != selection.Candidate.Profile {
		_, _ = fmt.Fprintf(diagnostics, "server profile %q is no longer configured; using %q\n", remembered, selection.Candidate.Profile)
	}
	_, _ = fmt.Fprintf(diagnostics, "using server profile %q (%s)\n", selection.Candidate.Profile, selection.Candidate.URL)
}
