package tui

// The endpoint table's CAPABILITY_REVISION column shows the revision the
// Provider declares for its own implementation. It is not a fingerprint of the
// capability set, and no admission path compares it against a command's revision.
//
// The help text is the only place an operator learns what the column means, and
// nothing in the code can notice when it drifts: the renderer prints whatever
// string the Server stored, so a help entry describing a fingerprint would keep
// rendering correctly while telling the operator something false. Only reading
// the text can assert that the documented meaning matches the implementation.
//
// The two claims this guard rejects are the ones the help text used to make:
// that the revision describes "the effective capability set", and that a changed
// revision implies the served operations changed and an older command may be
// refused. Neither is true: `internal/adapter/genericcli/adapter.go` builds the
// descriptor as `protocol.CapabilityDescriptor{Revision: descriptor.DescriptorRevision}`,
// and `supports()` in `internal/endpoint/executor.go` matches on operation name
// and version only.

import (
	"strings"
	"testing"
)

// capabilityRevisionHeader returns the header the endpoint table prints for the
// capability revision column, read from the real column slice so a renamed
// header is covered without editing this guard.
func capabilityRevisionHeader(t *testing.T) string {
	t.Helper()
	for _, column := range endpointColumns {
		if column.key == columnCapabilityRevision {
			return column.header
		}
	}
	t.Fatalf("the endpoint table no longer prints a %q column, so this guard has nothing to check", columnCapabilityRevision)
	return ""
}

// capabilityRevisionHelpEntry returns the field help entry for the endpoint
// table's capability revision column.
func capabilityRevisionHelpEntry(t *testing.T) string {
	t.Helper()
	header := capabilityRevisionHeader(t)
	for _, entry := range endpointFieldHelp {
		name, _, found := strings.Cut(entry, ":")
		if found && strings.TrimSpace(name) == header {
			return entry
		}
	}
	t.Fatalf("the endpoint field help has no %q entry, so the column is undocumented", header)
	return ""
}

// TestCapabilityRevisionHelpDoesNotClaimAFingerprint rejects the statements that
// describe a mechanism the code does not implement.
func TestCapabilityRevisionHelpDoesNotClaimAFingerprint(t *testing.T) {
	entry := capabilityRevisionHelpEntry(t)
	header := capabilityRevisionHeader(t)

	// "the revision of the effective capability set" claims the value is derived
	// from the set. It is copied from the Adapter configuration instead.
	if strings.Contains(entry, "revision of the effective capability set") {
		t.Errorf("the %s help claims the revision describes the capability set, but it is the configured revision string copied through unchanged: %q", header, entry)
	}

	// "A changed revision means the endpoint's served operations changed" claims
	// the revision tracks the served surface. It does not: editing ADAPTERS
	// changes the surface and leaves the revision untouched.
	if strings.Contains(entry, "served operations changed") {
		t.Errorf("the %s help claims a changed revision means the served operations changed, but the revision is the configured string and does not track the capability set: %q", header, entry)
	}

	// "a command admitted against an older revision may be refused" claims
	// revalidation. No admission path compares the revision; an operation is
	// served when its name and version are still advertised.
	if strings.Contains(entry, "may be refused") {
		t.Errorf("the %s help claims an older revision may cause refusal, but no admission path compares the revision against the endpoint's current value: %q", header, entry)
	}
}

// TestCapabilityRevisionHelpStatesTheProviderMeaning is the other half:
// rejecting the false claims is not enough, because an entry that says nothing
// would also pass. The entry must state what the value actually is.
func TestCapabilityRevisionHelpStatesTheProviderMeaning(t *testing.T) {
	entry := capabilityRevisionHelpEntry(t)
	header := capabilityRevisionHeader(t)

	if !strings.Contains(entry, "Provider declares") {
		t.Errorf("the %s help does not state that the value is the revision the Provider declares: %q", header, entry)
	}
	if !strings.Contains(entry, "not derived from the capability set") {
		t.Errorf("the %s help does not state that the value is not derived from the capability set: %q", header, entry)
	}
	// The configured string must not be named as the source. It is still a
	// configuration field, so an entry that names it as the origin would
	// describe the behaviour this change removed.
	if strings.Contains(entry, "Adapter configuration declares") {
		t.Errorf("the %s help still names the Adapter configuration as the source, but the published value is the Provider's descriptor revision: %q", header, entry)
	}
}
