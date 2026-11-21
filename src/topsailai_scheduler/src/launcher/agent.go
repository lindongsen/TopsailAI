package launcher

import (
	"topsailai_scheduler/provider"
	"topsailai_scheduler/task"
)

// Agent lets the provider decide how the task is run.
//
// This is the default launcher. The scheduler does not know the agent's command
// line: that belongs to the provider, which is an independent project. The
// launcher therefore supplies only the facts the scheduler owns, the task
// identity, its content path, the workspace and the timeout, and leaves the
// invocation to the provider.
type Agent struct{}

// Name returns the launcher name used in a task's YAML.
func (Agent) Name() string { return NameAgent }

// Build returns the provider request for the task.
func (Agent) Build(item task.Task, defaults Defaults) (provider.Request, error) {
	return provider.Request{
		TaskID:    item.ID,
		TaskPath:  item.MarkdownPath,
		TaskDir:   item.Dir,
		Workspace: resolveWorkspace(item, defaults),
		Args:      item.Spec.Args,
		Env:       taskEnv(item),
		Timeout:   resolveTimeout(item, defaults),
	}, nil
}
