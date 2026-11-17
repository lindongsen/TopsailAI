package tui

import (
	"context"
	"fmt"
	"io"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// detailReader is the optional API capability that reads one session's provider
// metadata and runtime document.
//
// It is a separate interface rather than a method on CommandAPI, so a surface
// that cannot read detail still satisfies the command surface, and a client
// without the capability renders the standard fields alone instead of failing
// the whole command.
type detailReader interface {
	GetDetail(context.Context, string, string) (protocol.SessionDetail, error)
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

// sessionDetailSections returns the provider sections to append to the standard
// session fields, or nil when the API cannot read detail.
//
// Returning nil rather than an empty section is deliberate: a client without the
// capability then renders exactly what it rendered before, so a missing seam is
// invisible instead of being reported as a provider that returned nothing.
//
// A failed read is reported as a section that states the failure, because the
// operator asked for provider detail and silence would be indistinguishable from
// a provider that has no detail to give.
func sessionDetailSections(ctx context.Context, api CommandAPI, endpointID, providerSessionID string) []detailSection {
	reader, ok := api.(detailReader)
	if !ok {
		return nil
	}
	if providerSessionID == "" {
		// A session with no provider identifier cannot be addressed by the
		// provider, so there is nothing to read. This is reported rather than
		// silently omitted, because an operator reading info on such a session
		// must not conclude that the provider has no record.
		return []detailSection{{label: "metadata", body: "not addressable: the session has no provider session identifier"}}
	}
	readCtx, cancel := context.WithTimeout(ctx, detailBudget)
	defer cancel()
	detail, err := reader.GetDetail(readCtx, endpointID, providerSessionID)
	if err != nil {
		return []detailSection{{label: "metadata", body: "read failed: " + err.Error()}}
	}
	if detail.ErrorCode != "" {
		return []detailSection{{label: "metadata", body: "read failed: " + detail.ErrorCode}}
	}
	return []detailSection{
		{label: "metadata", body: detailMetadataBody(detail)},
		{label: "runtime", body: detailRuntimeBody(detail)},
	}
}

// detailMetadataBody renders the provider session record.
//
// The record is rendered as readable text through the shared structured renderer,
// which is the same renderer a conversation body uses. It is not re-encoded and
// not curated: the provider's own document is what the operator asked for, and a
// curated subset would silently hide the field that answers the question.
//
// Truncation is labelled, because a shortened provider record must never be
// presented as the complete record.
func detailMetadataBody(detail protocol.SessionDetail) string {
	body := renderStructuredBody(detail.Metadata)
	if strings.TrimSpace(body) == "" {
		body = "not reported"
	}
	if detail.MetadataTruncated {
		body += "\n(truncated: the provider record exceeded the accepted bound)"
	}
	return body
}

// detailRuntimeBody renders the runtime observation.
//
// Runtime is a seam: no source fills it yet, so an empty document is reported as
// not reported rather than as an empty runtime. The distinction matters because
// "the provider reported nothing" and "the cluster has no source for this yet"
// are different facts, and only the second one is true today.
func detailRuntimeBody(detail protocol.SessionDetail) string {
	body := renderStructuredBody(detail.Runtime)
	if strings.TrimSpace(body) == "" {
		return "not reported"
	}
	return body
}

// writeDetailSections appends the provider sections to the standard fields.
//
// Each section is written as a labelled block rather than as more label/value
// lines, because a provider document is multi-line and a single "metadata: {...}"
// line would be unreadable. The label is printed once, then the body indented, so
// the operator can tell where the provider document starts and ends.
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
