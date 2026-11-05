package topsailai

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// Projects reads one provider-managed project list without scanning directories.
func (a *Adapter) Projects(ctx context.Context) ([]protocol.Project, error) {
	output, err := a.run(ctx, []string{"project", "list", "--json"}, nil)
	if err != nil {
		return nil, err
	}
	if len(output) > protocol.MaxProjectBytes {
		return nil, fmt.Errorf("project response exceeds byte limit")
	}
	var projects []protocol.Project
	if err := json.Unmarshal(output, &projects); err != nil {
		return nil, fmt.Errorf("decode projects: %w", err)
	}
	if projects == nil || len(projects) > protocol.MaxProjects {
		return nil, fmt.Errorf("invalid or oversized project list")
	}
	for _, project := range projects {
		if project.Path == "" || protocol.ValidateFolder(project.Path) != nil {
			return nil, fmt.Errorf("invalid project path")
		}
	}
	return projects, nil
}

// initialTask validates the optional literal task before any provider invocation.
func initialTask(payload json.RawMessage) (string, bool, error) {
	if len(payload) == 0 {
		return "", false, nil
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(payload, &fields); err != nil || fields == nil {
		return "", false, fmt.Errorf("start payload must be an object")
	}
	raw, ok := fields["task"]
	if !ok {
		return "", false, nil
	}
	var task string
	if string(raw) == "null" || json.Unmarshal(raw, &task) != nil || !utf8.Valid(raw) || strings.TrimSpace(task) == "" || strings.ContainsRune(task, 0) || len(task) > protocol.MaxInitialTaskBytes {
		return "", false, fmt.Errorf("task must be nonblank UTF-8 without NUL and at most %d bytes", protocol.MaxInitialTaskBytes)
	}
	return task, true, nil
}
