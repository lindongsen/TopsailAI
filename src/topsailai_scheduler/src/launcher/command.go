package launcher

import (
	"fmt"
	"strings"

	"topsailai_scheduler/provider"
	"topsailai_scheduler/task"
)

// Command runs the executable the task names.
//
// This is the launcher that lets the scheduler drive any tool, not only an
// agent. The task YAML supplies the executable and its arguments, and the
// supported placeholders are expanded from the task itself, so one task
// definition stays valid when the tasks folder moves.
//
// Example task configuration:
//
//	launcher: command
//	command: /usr/local/bin/my-tool
//	args: ["--input", "{task}", "--out", "{task_dir}/result.json"]
type Command struct{}

// Name returns the launcher name used in a task's YAML.
func (Command) Name() string { return NameCommand }

// Build returns the provider request for the task.
func (Command) Build(item task.Task, defaults Defaults) (provider.Request, error) {
	command := strings.TrimSpace(item.Spec.Command)
	if command == "" {
		return provider.Request{}, fmt.Errorf("launcher %q requires a command", NameCommand)
	}

	workspace := resolveWorkspace(item, defaults)

	return provider.Request{
		TaskID:    item.ID,
		TaskPath:  item.MarkdownPath,
		TaskDir:   item.Dir,
		Workspace: workspace,
		Command:   command,
		Args:      ExpandAll(item.Spec.Args, item, workspace),
		Env:       taskEnv(item),
		Timeout:   resolveTimeout(item, defaults),
	}, nil
}
