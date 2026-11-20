package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// projectRootEnvironment names the Endpoint-local project root the Provider
// confines registration to.
//
// The value is read once at the process boundary and passed down, exactly like the
// control catalog and the task directory. An empty value disables project.add
// entirely: the Provider refuses with project_root_unconfigured rather than
// falling back to any default directory, because a default would silently grant a
// remote caller the right to register folders nobody approved.
const projectRootEnvironment = "AGENT_CLUSTER_ENDPOINT_PROJECT_ROOT"

// projectAddPayload is the Provider-side shape of one project.add payload.
//
// It mirrors protocol.ProjectAddPayload. This executable is an independent module
// and cannot import the Cluster package, so the shape is repeated here and the
// rules are re-applied rather than trusted.
type projectAddPayload struct {
	Folder string `json:"folder"`
	Name   string `json:"name,omitempty"`
}

// resolveProjectRoot reads the configured project root once at startup.
//
// The value is resolved to a real path here so every later confinement decision
// compares two resolved paths. A configured root that does not resolve to an
// existing directory yields an empty value, which disables project.add: a root the
// Provider cannot resolve is a root it cannot confine anything to.
func resolveProjectRoot(environment []string) string {
	configured := strings.TrimSpace(environmentValue(environment, projectRootEnvironment))
	if configured == "" {
		return ""
	}
	if !filepath.IsAbs(configured) {
		return ""
	}
	resolved, err := filepath.EvalSymlinks(configured)
	if err != nil {
		return ""
	}
	info, err := os.Stat(resolved)
	if err != nil || !info.IsDir() {
		return ""
	}
	return resolved
}

// confineProjectFolder resolves one requested folder and proves it is inside root.
//
// The decision is made on the resolved path, never on the text the operator typed,
// so a parent traversal, an absolute escape and a symlink that points outside the
// root are all refused by the same comparison. The folder must already exist and be
// a directory, because registering a path that does not resolve would create a
// registry entry that can never be launched.
func confineProjectFolder(root, folder string) (string, error) {
	if root == "" {
		return "", fmt.Errorf("%w: %s is not configured", errProjectRootUnconfigured, projectRootEnvironment)
	}
	if strings.TrimSpace(folder) == "" {
		return "", fmt.Errorf("%w: project.add folder is required", errInvalidRequest)
	}
	if strings.TrimSpace(folder) != folder {
		return "", fmt.Errorf("%w: project.add folder must not have leading or trailing whitespace", errInvalidRequest)
	}
	if !filepath.IsAbs(folder) {
		return "", fmt.Errorf("%w: project.add folder must be an absolute path", errInvalidRequest)
	}
	resolved, err := filepath.EvalSymlinks(folder)
	if err != nil {
		return "", fmt.Errorf("%w: %s", errProjectPathNotDirectory, folder)
	}
	info, err := os.Stat(resolved)
	if err != nil || !info.IsDir() {
		return "", fmt.Errorf("%w: %s", errProjectPathNotDirectory, folder)
	}
	relative, err := filepath.Rel(root, resolved)
	if err != nil {
		return "", fmt.Errorf("%w: %s", errProjectPathOutsideRoot, folder)
	}
	// A relative path that starts with ".." leaves the root, and the root itself
	// resolves to "." which is inside it. Both cases are decided here so the rule
	// has one spelling.
	if relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("%w: %s", errProjectPathOutsideRoot, folder)
	}
	return resolved, nil
}

// projectAddArgs builds the provider argv for one registration.
//
// The folder is passed as one argv element, so no shell parses it and no
// operator-supplied text can become a command. The name is passed in the same
// assignment form agent.start uses for its task, because the provider parser
// classifies a separate dash-leading element as an option.
func projectAddArgs(payload json.RawMessage, root string) ([]string, error) {
	var value projectAddPayload
	if err := decodeStrict(payload, &value); err != nil {
		return nil, fmt.Errorf("%w: decode project.add payload: %v", errInvalidRequest, err)
	}
	if strings.TrimSpace(value.Name) != value.Name {
		return nil, fmt.Errorf("%w: project.add name must not have leading or trailing whitespace", errInvalidRequest)
	}
	folder, err := confineProjectFolder(root, value.Folder)
	if err != nil {
		return nil, err
	}
	args := []string{"project", "add", folder}
	if value.Name != "" {
		args = append(args, value.Name)
	}
	return args, nil
}

// decodeProjectTarget reads the exact project path from the opaque slot.
//
// An absent slot is a refusal rather than a fallback: recovering the path by
// scanning the registry would make the Provider guess which entry the operator
// meant, and a guess is exactly what an exact-target operation must not do.
func decodeProjectTarget(value string) (string, error) {
	if strings.TrimSpace(value) == "" {
		return "", fmt.Errorf("%w: project.remove requires the exact project path", errInvalidRequest)
	}
	if len(value) > maxProviderTargetBytes {
		return "", fmt.Errorf("%w: provider_target exceeds contract limit", errInvalidRequest)
	}
	var slot projectTargetSlot
	if err := decodeStrict(json.RawMessage(value), &slot); err != nil {
		return "", fmt.Errorf("%w: invalid project provider_target", errInvalidRequest)
	}
	if strings.TrimSpace(slot.ProjectPath) == "" {
		return "", fmt.Errorf("%w: project provider_target carries no project path", errInvalidRequest)
	}
	return slot.ProjectPath, nil
}

// projectTargetSlot is the Provider-owned exact-project address carried through
// the Cluster opaque provider_target seam.
//
// A project has no session identifier and no PID, so it cannot use the session
// slot. It carries only the folder the Endpoint already holds in its durable
// mapping, which is why removal never has to reverse-scan the registry.
type projectTargetSlot struct {
	ProjectPath string `json:"project_path"`
}

// projectRemoveArgs builds the argv that removes one registry entry.
//
// The folder on disk is never deleted: the Provider's own `project del` command
// removes the registration only, and this Provider passes no flag that could
// change that. The doc comment states it because the argv alone does not.
//
// The caller carries the exact folder in the opaque provider_target slot, because
// the Cluster mapping key is a digest and cannot be reversed. That slot is
// therefore evidence supplied by the caller, so it is bound to the durable
// mapping key before any argv exists: the key is recomputed from the folder and
// compared with the key the Cluster addressed. A slot that names a different
// folder is refused, which keeps the operation addressing exactly the resource
// the operator selected instead of whatever path the slot happens to contain.
func projectRemoveArgs(providerTarget, providerResourceKey, root string) ([]string, error) {
	folder := strings.TrimSpace(providerTarget)
	if folder == "" {
		return nil, fmt.Errorf("%w: project.remove requires the exact project path", errInvalidRequest)
	}
	// Removal is confined to the same root as registration. A registry entry that
	// names a folder outside the root cannot be removed through this operation,
	// because the operation exists to manage the folders this Endpoint approved.
	resolved, err := confineProjectFolder(root, folder)
	if err != nil {
		return nil, err
	}
	if err := requireProjectKeyBinding(resolved, providerResourceKey); err != nil {
		return nil, err
	}
	return []string{"project", "del", resolved}, nil
}

// requireProjectKeyBinding proves the caller's exact-target slot names the same
// project the Cluster addressed.
//
// The mapping key is the digest of the folder, so recomputing it from the slot is
// the only way to compare the two without a registry read. A mismatch is refused
// rather than resolved to the slot, because the slot is caller-supplied evidence
// and the key is the durable identity: preferring the slot would let a caller
// remove a registry entry it never addressed.
func requireProjectKeyBinding(folder, providerResourceKey string) error {
	if strings.TrimSpace(providerResourceKey) == "" {
		return fmt.Errorf("%w: project.remove requires the addressed project key", errInvalidRequest)
	}
	digest := sha256.Sum256([]byte(folder))
	expected := fmt.Sprintf("project:v1:%x", digest)
	if providerResourceKey != expected {
		return fmt.Errorf("%w: project provider_target does not match the addressed project", errInvalidRequest)
	}
	return nil
}
