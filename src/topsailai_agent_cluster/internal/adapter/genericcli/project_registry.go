package genericcli

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// projectError carries the standard refusal code for one project registration
// refusal.
//
// The code travels with the error because the receipt must name the same code the
// contract defines. Deriving it later from the message would make the code a
// second spelling of the message, and the two would drift the first time a
// message was reworded.
type projectError struct {
	code string
	err  error
}

func (e *projectError) Error() string { return e.err.Error() }

func (e *projectError) Unwrap() error { return e.err }

// projectRefusalCode returns the standard code for one project refusal.
//
// A refusal that carries no code is a payload defect rather than a confinement
// decision, so it reports the payload code. That keeps every refusal named
// instead of falling back to a generic failure the operator cannot act on.
func projectRefusalCode(err error) string {
	var coded *projectError
	if errors.As(err, &coded) {
		return coded.code
	}
	return protocol.ProjectFolderInvalid
}

// confineProjectFolder resolves one requested folder and proves it is inside the
// configured project root.
//
// The decision is made on the resolved path, never on the text the operator
// typed, so a parent traversal, an absolute escape and a symlink that points
// outside the root are all refused by the same comparison. The folder must
// already exist and be a directory, because registering a path that does not
// resolve would create a registry entry that can never be launched.
//
// This is the Endpoint-side check. The Provider re-applies the identical rule in
// the same execution path that builds its argv, so the two cannot disagree about
// which folder is registered and no time-of-check window is left open between
// them.
func confineProjectFolder(root, folder string) (string, error) {
	if strings.TrimSpace(root) == "" {
		return "", &projectError{code: protocol.ProjectRootUnconfigured, err: fmt.Errorf("AGENT_CLUSTER_ENDPOINT_PROJECT_ROOT is not configured, so remote project registration is disabled")}
	}
	if strings.TrimSpace(folder) == "" {
		return "", &projectError{code: protocol.ProjectFolderInvalid, err: errors.New("project folder is required")}
	}
	if strings.TrimSpace(folder) != folder {
		return "", &projectError{code: protocol.ProjectFolderInvalid, err: errors.New("project folder must not have leading or trailing whitespace")}
	}
	if !filepath.IsAbs(folder) {
		return "", &projectError{code: protocol.ProjectFolderInvalid, err: fmt.Errorf("project folder %q must be an absolute path", folder)}
	}
	resolved, err := filepath.EvalSymlinks(folder)
	if err != nil {
		return "", &projectError{code: protocol.ProjectPathNotDirectory, err: fmt.Errorf("project folder %q does not resolve: %v", folder, err)}
	}
	info, err := os.Stat(resolved)
	if err != nil || !info.IsDir() {
		return "", &projectError{code: protocol.ProjectPathNotDirectory, err: fmt.Errorf("project folder %q is not a directory", folder)}
	}
	relative, err := filepath.Rel(root, resolved)
	if err != nil {
		return "", &projectError{code: protocol.ProjectPathOutsideRoot, err: fmt.Errorf("project folder %q is outside the configured project root", folder)}
	}
	// A relative path that starts with ".." leaves the root, and the root itself
	// resolves to "." which is inside it. Both cases are decided here so the rule
	// has one spelling.
	if relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return "", &projectError{code: protocol.ProjectPathOutsideRoot, err: fmt.Errorf("project folder %q is outside the configured project root", folder)}
	}
	return resolved, nil
}

// projectAddExecutionPayload confines one project.add payload before dispatch.
//
// The payload is re-encoded with the resolved folder so the Provider receives the
// exact path the Endpoint approved rather than the text the operator typed. That
// keeps one value in force: a folder that reached the root through a symlink is
// registered under its real location, which is the location the confinement
// decision was made on.
func (a *Adapter) projectAddExecutionPayload(intent protocol.ImmutableIntent) (json.RawMessage, error) {
	var payload protocol.ProjectAddPayload
	if err := json.Unmarshal(intent.Payload, &payload); err != nil {
		return nil, &projectError{code: protocol.ProjectFolderInvalid, err: fmt.Errorf("decode project.add payload: %v", err)}
	}
	if err := payload.Validate(); err != nil {
		return nil, &projectError{code: protocol.ProjectFolderInvalid, err: err}
	}
	resolved, err := confineProjectFolder(a.config.ProjectRoot, payload.Folder)
	if err != nil {
		return nil, err
	}
	return json.Marshal(protocol.ProjectAddPayload{Folder: resolved, Name: payload.Name})
}

// resolveProjectRemoveTarget proves one project.remove addresses the exact mapped
// registry entry before dispatch, and returns the target with its opaque slot
// rewritten to the resolved folder.
//
// The target carries the opaque Cluster project ID, which resolves to a durable
// mapping, and the caller supplies the folder it read from the catalog in the
// opaque provider_target slot. Both must name the same entry, so the slot is
// required and its folder is confined to the same root as registration. The
// Provider re-derives the mapping key from that folder and refuses a mismatch, so
// a caller cannot address one project ID while naming a different folder.
//
// The slot is rewritten rather than merely checked, so the Provider receives the
// exact path the Endpoint approved instead of the text the operator typed. One
// value stays in force: a folder that reached the root through a symlink is
// addressed by its real location, which is the location the confinement decision
// was made on.
func (a *Adapter) resolveProjectRemoveTarget(target protocol.CommandTarget) (protocol.CommandTarget, error) {
	if strings.TrimSpace(target.ProviderTarget) == "" {
		return target, &projectError{code: protocol.ProjectFolderInvalid, err: errors.New("project.remove requires the exact project path")}
	}
	var slot struct {
		ProjectPath string `json:"project_path"`
	}
	decoder := json.NewDecoder(strings.NewReader(target.ProviderTarget))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&slot); err != nil {
		return target, &projectError{code: protocol.ProjectFolderInvalid, err: fmt.Errorf("invalid project provider_target: %v", err)}
	}
	resolved, err := confineProjectFolder(a.config.ProjectRoot, slot.ProjectPath)
	if err != nil {
		return target, err
	}
	rewritten, err := json.Marshal(struct {
		ProjectPath string `json:"project_path"`
	}{ProjectPath: resolved})
	if err != nil {
		return target, &projectError{code: protocol.ProjectFolderInvalid, err: fmt.Errorf("encode project provider_target: %v", err)}
	}
	target.ProviderTarget = string(rewritten)
	return target, nil
}

// projectRefusalReceipt builds the receipt for a project registration refused
// before any Provider call.
//
// The effect is provably not applied, because the refusal happens before the
// Provider process starts. Reporting unknown here would send an operator to
// investigate a registration that provably did nothing, and unknown is also the
// value that forbids automatic retry.
func projectRefusalReceipt(intent protocol.ImmutableIntent, code string) protocol.ExecutionReceipt {
	return protocol.ExecutionReceipt{
		CommandID:       intent.CommandID,
		Phase:           protocol.PhaseReceiptRecorded,
		EffectCertainty: protocol.EffectNotApplied,
		Outcome:         "failed",
		ErrorCode:       code,
	}
}

// projectRefusalResult builds the refusal result for one pre-dispatch failure.
//
// A project refusal carries a standard code, so the receipt names it and the
// operator learns which rule refused the request. Any other failure keeps the
// previous behaviour of an empty result, because the executor already fills in
// the generic outcome for an adapter error and inventing a project code for an
// unrelated defect would misdirect the investigation.
func projectRefusalResult(intent protocol.ImmutableIntent, err error) adapter.ExecuteResult {
	var coded *projectError
	if !errors.As(err, &coded) {
		return adapter.ExecuteResult{}
	}
	return adapter.ExecuteResult{Receipt: projectRefusalReceipt(intent, coded.code)}
}
