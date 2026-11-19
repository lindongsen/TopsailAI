package tui

import (
	"context"
	"fmt"
	"io"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// detailReader is the optional API capability that reads one session's two
// provider documents.
//
// It is a separate interface rather than a method on CommandAPI, so a surface
// that cannot read detail still satisfies the command surface, and a client
// without the capability renders the standard fields alone instead of failing
// the whole command.
type detailReader interface {
	GetDetail(context.Context, string, string) (protocol.SessionDetail, error)
}

// exactDetailReader preserves opaque Provider addressing evidence.
type exactDetailReader interface {
	GetDetailQuery(context.Context, string, protocol.SessionDetailQuery) (protocol.SessionDetail, error)
}

// detailBudget bounds one detail read. It is longer than a metrics read because
// the document is larger and the operator asked for it explicitly, and shorter
// than the command budget so a slow provider reports its own failure first.
const detailBudget = 10 * time.Second

// detailSection is one labelled block of provider text in the info output.
type detailSection struct {
	label string
	body  string
}

// detailRead is the outcome of one detail read.
//
// Both surfaces consume this one value, so the text form and the machine-readable
// form can never disagree about what the provider reported. Reading twice would
// let them diverge, and a caller comparing the two would have no way to tell which
// one was current.
type detailRead struct {
	// Available is false when the API cannot read detail at all. A surface then
	// renders exactly what it rendered before the seam existed, so a missing
	// capability stays invisible instead of being reported as an empty provider
	// document.
	Available bool
	// Detail holds the provider documents. It is meaningful only when Failure is
	// empty.
	Detail protocol.SessionDetail
	// Failure states, in operator terms, why no document is available. It is
	// reported rather than swallowed because the operator asked for provider
	// detail, and silence would be indistinguishable from a provider that has
	// nothing to report.
	Failure string
}

// readSessionDetail performs the one detail read both surfaces share.
func readSessionDetail(ctx context.Context, api CommandAPI, endpointID, providerSessionID string, providerTargets ...string) detailRead {
	providerTarget := ""
	if len(providerTargets) > 0 {
		providerTarget = providerTargets[0]
	}
	reader, ok := api.(detailReader)
	if !ok {
		return detailRead{}
	}
	if providerSessionID == "" {
		// A session with no provider identifier cannot be addressed by the
		// provider, so there is nothing to read. This is reported rather than
		// silently omitted, because an operator reading info on such a session
		// must not conclude that the provider has no record.
		return detailRead{Available: true, Failure: "not addressable: the session has no provider session identifier"}
	}
	readCtx, cancel := context.WithTimeout(ctx, detailBudget)
	defer cancel()
	var detail protocol.SessionDetail
	var err error
	if exact, ok := api.(exactDetailReader); ok {
		detail, err = exact.GetDetailQuery(readCtx, endpointID, protocol.SessionDetailQuery{ProviderSessionID: providerSessionID, ProviderTarget: providerTarget})
	} else {
		detail, err = reader.GetDetail(readCtx, endpointID, providerSessionID)
	}
	if err != nil {
		return detailRead{Available: true, Failure: "read failed: " + err.Error()}
	}
	if detail.ErrorCode != "" {
		return detailRead{Available: true, Failure: "read failed: " + detail.ErrorCode}
	}
	return detailRead{Available: true, Detail: detail}
}

// sessionDetailSections renders the provider sections to append to the standard
// session fields, or nil when the API cannot read detail.
//
// Returning nil rather than an empty section is deliberate: a client without the
// capability then renders exactly what it rendered before, so a missing seam is
// invisible instead of being reported as a provider that returned nothing.
func sessionDetailSections(read detailRead) []detailSection {
	if !read.Available {
		return nil
	}
	if read.Failure != "" {
		return []detailSection{{label: "provider_metadata", body: read.Failure}}
	}
	return []detailSection{
		{label: "provider_metadata", body: detailProviderMetadataBody(read.Detail)},
		{label: "provider_runtime", body: detailProviderRuntimeBody(read.Detail)},
	}
}

// detailProviderMetadataBody renders the provider session record.
//
// The record is rendered as readable text through the shared structured renderer,
// which is the same renderer a conversation body uses. It is not re-encoded and
// not curated: the provider's own document is what the operator asked for, and a
// curated subset would silently hide the field that answers the question.
//
// There is no truncation label, because the contract rejects an oversized
// document instead of shortening it. A shortened record presented as the whole
// record would leave the operator unable to tell which fields were dropped, so
// the read fails visibly and this function never receives a partial document.
func detailProviderMetadataBody(detail protocol.SessionDetail) string {
	body := renderStructuredBody(detail.ProviderMetadata)
	if strings.TrimSpace(body) == "" {
		return "not reported"
	}
	return body
}

// detailProviderRuntimeBody renders the provider runtime observation.
//
// The runtime document is a seam: the cluster fixes the position and the bound,
// and the provider decides the content. A provider that reports nothing leaves it
// empty, and an empty document is reported as not reported rather than as an
// empty runtime. The distinction matters because "the provider reported nothing"
// and "the cluster has no source for this yet" are different facts, and only the
// first one is a statement about the provider.
func detailProviderRuntimeBody(detail protocol.SessionDetail) string {
	body := renderStructuredBody(detail.ProviderRuntime)
	if strings.TrimSpace(body) == "" {
		return "not reported"
	}
	return body
}

// writeDetailSections appends the provider sections to the standard fields.
//
// Each section is written as a labelled block rather than as more label/value
// lines, because a provider document is multi-line and a single
// "provider_metadata: {...}" line would be unreadable. The label is printed once,
// then the body indented, so the operator can tell where the provider document
// starts and ends.
func writeDetailSections(w io.Writer, sections []detailSection) error {
	for _, section := range sections {
		if _, err := fmt.Fprintf(w, "%s:\n", section.label); err != nil {
			return err
		}
		for _, line := range strings.Split(section.body, "\n") {
			if _, err := fmt.Fprintf(w, "  %s\n", escapeCell(line)); err != nil {
				return err
			}
		}
	}
	return nil
}
