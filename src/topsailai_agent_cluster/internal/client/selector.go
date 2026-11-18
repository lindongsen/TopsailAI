// Package client provides clients for latest-state Server APIs.
package client

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// readinessPath is the route a candidate Server is probed on.
//
// It is the Server's own readiness route, which answers whether the process is up
// and its storage is available. That is exactly the condition that makes a request
// worth sending, so the probe asks the same question the walk needs and nothing
// more.
const readinessPath = "/readyz"

// DefaultProbeTimeout bounds one candidate probe.
//
// Without a bound, an address that accepts a connection and then never answers
// would hold the probe open until the caller's context expired, so the remaining
// candidates would never be tried. A bounded probe is what makes "try the next
// Server" a real behaviour rather than a comment.
const DefaultProbeTimeout = 5 * time.Second

// ServerCandidate is one configured Server the CLI may use.
type ServerCandidate struct {
	// Profile is the configured name that selected this Server. It is empty for
	// an invocation that selected no profile, because such an invocation has one
	// unnamed Server and nothing to choose between.
	Profile string
	URL     string
	Token   string
}

// Selection is the outcome of choosing one Server from an ordered candidate list.
type Selection struct {
	// Candidate is the Server the caller must use.
	Candidate ServerCandidate
	// Skipped records every candidate that was probed and rejected, in the order
	// they were tried. It exists because a successful walk is otherwise silent:
	// the caller would see a working CLI and could not tell "the first Server is
	// down" from "the first Server was never configured".
	Skipped []SkippedCandidate
}

// SkippedCandidate records one candidate that was not used and why.
type SkippedCandidate struct {
	Profile string
	URL     string
	Reason  string
}

// Selector chooses one Server from an ordered candidate list.
//
// It is a value rather than a package function so the probe budget and the HTTP
// client are injected, which keeps a test from depending on a real network or on
// process-wide state.
type Selector struct {
	// HTTPClient performs the probe. A nil value uses http.DefaultClient.
	HTTPClient *http.Client
	// ProbeTimeout bounds one candidate probe. A non-positive value uses
	// DefaultProbeTimeout.
	ProbeTimeout time.Duration
}

// Select returns the first candidate that reports ready, in the order given.
//
// Only unreachability causes a switch. The three answer classes are deliberately
// separated, because collapsing them is how a credential problem or a real
// business answer gets disguised as a reachability problem:
//
//   - A transport failure, a probe timeout, or an explicit not-ready answer means
//     this Server cannot serve the request, so the walk continues.
//   - An authentication or authorization failure means this Server is healthy and
//     rejected this credential. The walk stops, because trying the next Server
//     would present a second credential to a Server that already refused the
//     first, and the operator would never learn that the credential is wrong.
//   - Any other non-success answer means this Server is healthy and answered. The
//     walk stops, because replacing a real answer with a second, equally real
//     answer hides what the first Server said.
//
// A single candidate is probed like any other. That is not a behaviour change for
// an existing deployment: one candidate has nothing to fall back to, so a probe
// that fails produces the same failure the request would have produced, reported
// with the same address.
//
// The probe carries no credential. HMAC is the default presentation mode, so
// probing with a credential would sign a request with one Server's key and present
// it to a Server that has not been selected. The readiness route bypasses
// authentication, so the probe can be credential-free without any Server change.
func (s Selector) Select(ctx context.Context, candidates []ServerCandidate) (Selection, error) {
	if len(candidates) == 0 {
		return Selection{}, errors.New("no Server is configured")
	}
	timeout := s.ProbeTimeout
	if timeout <= 0 {
		timeout = DefaultProbeTimeout
	}
	skipped := make([]SkippedCandidate, 0, len(candidates))
	for _, candidate := range candidates {
		if err := ctx.Err(); err != nil {
			return Selection{}, err
		}
		reason, err := s.probe(ctx, candidate, timeout)
		if err != nil {
			return Selection{}, err
		}
		if reason == "" {
			return Selection{Candidate: candidate, Skipped: skipped}, nil
		}
		skipped = append(skipped, SkippedCandidate{Profile: candidate.Profile, URL: candidate.URL, Reason: reason})
	}
	return Selection{Skipped: skipped}, unreachableError(skipped)
}

// unreachableError names every candidate that was tried.
//
// The names are the only evidence that distinguishes "no Server is reachable" from
// "this Server refused me", and they are what lets an operator tell a single-Server
// outage from a fleet-wide one.
func unreachableError(skipped []SkippedCandidate) error {
	parts := make([]string, 0, len(skipped))
	for _, candidate := range skipped {
		parts = append(parts, fmt.Sprintf("%s: %s", candidateLabel(candidate.Profile, candidate.URL), candidate.Reason))
	}
	return fmt.Errorf("no configured Server is reachable: %s", strings.Join(parts, "; "))
}

// candidateLabel names a candidate the way the operator configured it.
//
// The profile name is preferred because it is what the operator wrote. The URL is
// the fallback for an unnamed candidate, which is the one an invocation that
// selected no profile uses.
func candidateLabel(profile, address string) string {
	if profile != "" {
		return fmt.Sprintf("profile %q (%s)", profile, address)
	}
	return address
}

// probe asks one candidate whether it can serve requests.
//
// It returns an empty reason when the candidate is usable, and a human-readable
// reason when it is not. A non-nil error is a local configuration defect that no
// other candidate can fix, so the walk must stop rather than continue.
func (s Selector) probe(ctx context.Context, candidate ServerCandidate, timeout time.Duration) (string, error) {
	address, err := url.Parse(candidate.URL)
	if err != nil {
		return "", fmt.Errorf("%s is not a valid Server URL: %w", candidateLabel(candidate.Profile, candidate.URL), err)
	}
	if address.Scheme != "http" && address.Scheme != "https" {
		return "", fmt.Errorf("%s must use http or https, not %q", candidateLabel(candidate.Profile, candidate.URL), address.Scheme)
	}
	probeCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	req, err := http.NewRequestWithContext(probeCtx, http.MethodGet, strings.TrimRight(candidate.URL, "/")+readinessPath, nil)
	if err != nil {
		return "", fmt.Errorf("%s readiness request could not be built: %w", candidateLabel(candidate.Profile, candidate.URL), err)
	}
	// No credential is attached, deliberately. See Select.
	httpClient := s.HTTPClient
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		// A transport failure is the one class that means "try the next Server".
		// The caller's own cancellation is not a property of this candidate, so it
		// is reported as an error instead of being recorded as a skip.
		if ctx.Err() != nil {
			return "", ctx.Err()
		}
		return fmt.Sprintf("unreachable: %v", err), nil
	}
	defer resp.Body.Close()
	// The body is drained so the connection can be reused, and bounded so a
	// misbehaving endpoint cannot make the probe read an unbounded document.
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4<<10))
	switch {
	case resp.StatusCode >= 200 && resp.StatusCode < 300:
		return "", nil
	case resp.StatusCode == http.StatusServiceUnavailable:
		// The readiness route answers 503 when the Server is up but its storage is
		// unavailable. That Server cannot serve a request, so the walk continues.
		return fmt.Sprintf("not ready (%d)", resp.StatusCode), nil
	case resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden:
		// A healthy Server refused this credential. Trying the next Server would
		// present a second credential to a Server that already refused the first,
		// and would hide the real cause behind a successful-looking fallback.
		return "", fmt.Errorf("%s refused the credential (%d); fix the credential instead of falling back", candidateLabel(candidate.Profile, candidate.URL), resp.StatusCode)
	default:
		// Any other answer means the Server is healthy and answered. Replacing it
		// with a second answer would hide what this Server said.
		return "", fmt.Errorf("%s answered %d; the Server is reachable, so the walk stops", candidateLabel(candidate.Profile, candidate.URL), resp.StatusCode)
	}
}
