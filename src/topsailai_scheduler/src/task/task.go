// Package task discovers scheduled tasks from the tasks folder tree and parses
// their YAML configuration.
//
// A task is a set of files sharing one stem inside the tasks root:
//
//	tasks/data/work.yaml   configuration, the anchor of the task
//	tasks/data/work.md     task content handed to the agent
//	tasks/data/work.lock   runtime lock, created on demand
//
// Folders are free-form grouping and may nest arbitrarily. The task identity is
// the YAML path relative to the tasks root without its extension, so
// tasks/data/work.yaml is the task "data/work".
package task

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/robfig/cron/v3"
	"gopkg.in/yaml.v3"
)

// File extensions that make up a task.
const (
	YAMLExt = ".yaml"
	MDExt   = ".md"
	LockExt = ".lock"
)

// The minimum content length is a parameter, not a constant here.
//
// A task whose content is empty or a bare phrase gives an agent nothing to act
// on, so it is rejected at load time instead of being scheduled and failing
// every time it fires. The floor is supplied by the caller because it is a
// deployment policy: the scheduler reads it from configuration and passes it
// down, so raising it needs no rebuild. The count is runes after trimming
// whitespace, so a whitespace-only file counts as zero and a Chinese phrase
// counts by characters rather than bytes.

// Spec is the parsed content of a task YAML file.
//
// The struct is intentionally a plain data holder: adding a future feature such
// as task dependencies means adding one field here plus its validation, without
// touching discovery, scheduling or execution.
type Spec struct {
	// Schedule is a standard five-field cron expression or an @shortcut.
	Schedule string `yaml:"schedule"`
	// Enabled defaults to true when omitted.
	Enabled *bool `yaml:"enabled"`
	// Launcher selects how the task is started. Empty means "agent".
	Launcher string `yaml:"launcher"`
	// Provider is the executable that runs the task. Empty means the default
	// provider configured at startup. The value is a path, so a task may point
	// at a provider anywhere on disk; a relative path resolves against the
	// scheduler working directory. A provider is an independent executable
	// speaking the protocol in docs/Provider_Contract.md, so it is chosen by
	// path rather than linked in.
	Provider string `yaml:"provider"`
	// Command overrides the default executable for the selected launcher.
	Command string `yaml:"command"`
	// Args are extra arguments appended after the launcher's default arguments.
	Args []string `yaml:"args"`
	// Workspace overrides the default agent workspace.
	Workspace string `yaml:"workspace"`
	// Timeout bounds one run. Zero means the configured default.
	Timeout Duration `yaml:"timeout"`
	// Env holds extra environment variables for this task only.
	Env map[string]string `yaml:"env"`
}

// IsEnabled reports whether the task should be scheduled.
func (s Spec) IsEnabled() bool {
	return s.Enabled == nil || *s.Enabled
}

// Duration is a time.Duration that unmarshals from a YAML string such as "30m".
//
// yaml.v3 has no built-in duration support, so a bare "30m" would otherwise be
// rejected as a type mismatch.
type Duration struct {
	time.Duration
}

// UnmarshalYAML parses a duration string, rejecting a bare number because its
// unit would be ambiguous.
func (d *Duration) UnmarshalYAML(value *yaml.Node) error {
	var text string
	if err := value.Decode(&text); err != nil {
		return fmt.Errorf("timeout must be a duration string such as \"30m\": %w", err)
	}
	parsed, err := time.ParseDuration(strings.TrimSpace(text))
	if err != nil {
		return fmt.Errorf("invalid timeout %q: %w", text, err)
	}
	if parsed <= 0 {
		return fmt.Errorf("invalid timeout %q: must be positive", text)
	}
	d.Duration = parsed
	return nil
}

// Task is one discovered task and the paths of its files.
type Task struct {
	// ID is the YAML path relative to the tasks root without extension.
	ID string
	// Dir is the absolute folder holding the task files.
	Dir string
	// Stem is the shared filename stem, for example "work".
	Stem string
	// YAMLPath is the absolute path of the configuration file.
	YAMLPath string
	// MarkdownPath is the absolute path of the task content file.
	MarkdownPath string
	// LockPath is the absolute path of the runtime lock file.
	LockPath string
	// Spec is the parsed configuration.
	Spec Spec
	// Fingerprint identifies the current content of the task files. It changes
	// when the YAML or the Markdown content changes, which is how the daemon
	// detects that a running task must be rescheduled.
	Fingerprint string
}

// LoadError reports one task file that could not be loaded. Discovery keeps
// going after a failure so one broken task cannot hide every other task.
type LoadError struct {
	// Path is the file that failed.
	Path string
	// Err is the underlying reason.
	Err error
}

// Error implements the error interface.
func (e LoadError) Error() string {
	return fmt.Sprintf("%s: %v", e.Path, e.Err)
}

// Unwrap exposes the underlying error.
func (e LoadError) Unwrap() error { return e.Err }

// Load walks root and returns every valid task sorted by ID, plus one error per
// task file that could not be loaded.
//
// minRunes is the shortest accepted content, counted in runes after trimming
// whitespace. It is passed in rather than read from a constant so the caller
// owns the policy and a deployment can change it without a rebuild.
//
// A missing root is not an error: an empty scheduler is a valid state, and
// reporting it as a failure would make an empty tasks folder look broken.
func Load(root string, minRunes int) ([]Task, []LoadError, error) {
	absoluteRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, nil, fmt.Errorf("resolve tasks root %q: %w", root, err)
	}

	info, err := os.Stat(absoluteRoot)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil, nil
		}
		return nil, nil, fmt.Errorf("stat tasks root %q: %w", absoluteRoot, err)
	}
	if !info.IsDir() {
		return nil, nil, fmt.Errorf("tasks root %q is not a directory", absoluteRoot)
	}

	var tasks []Task
	var failures []LoadError

	walkErr := filepath.WalkDir(absoluteRoot, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			// A folder that cannot be read is reported but does not abort the
			// scan, so the remaining tasks still load.
			failures = append(failures, LoadError{Path: path, Err: err})
			if entry != nil && entry.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if entry.IsDir() {
			if path != absoluteRoot && strings.HasPrefix(entry.Name(), ".") {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.EqualFold(filepath.Ext(entry.Name()), YAMLExt) {
			return nil
		}

		loaded, loadErr := loadOne(absoluteRoot, path, minRunes)
		if loadErr != nil {
			failures = append(failures, LoadError{Path: path, Err: loadErr})
			return nil
		}
		tasks = append(tasks, loaded)
		return nil
	})
	if walkErr != nil {
		return nil, failures, fmt.Errorf("walk tasks root %q: %w", absoluteRoot, walkErr)
	}

	sort.Slice(tasks, func(i, j int) bool { return tasks[i].ID < tasks[j].ID })
	return tasks, failures, nil
}

// LoadOne parses one task file without scanning the tree.
//
// It exists so a caller can validate a single task. The whole-tree Load is the
// wrong tool when the question is about one file, and reimplementing the checks
// at the call site would let the two paths disagree about what a valid task is.
//
// yamlPath must name a .yaml file. A file outside root has no task id, so it is
// rejected rather than reported under a name the daemon would never use.
func LoadOne(root, yamlPath string, minRunes int) (Task, error) {
	absoluteRoot, err := filepath.Abs(root)
	if err != nil {
		return Task{}, fmt.Errorf("resolve tasks root %q: %w", root, err)
	}
	absolutePath, err := filepath.Abs(yamlPath)
	if err != nil {
		return Task{}, fmt.Errorf("resolve task file %q: %w", yamlPath, err)
	}
	if !strings.EqualFold(filepath.Ext(absolutePath), YAMLExt) {
		return Task{}, fmt.Errorf("%s is not a task configuration file: expected a %s file",
			absolutePath, YAMLExt)
	}
	return loadOne(absoluteRoot, absolutePath, minRunes)
}

// loadOne parses a single YAML file and resolves its sibling paths.
//
// minRunes is the shortest accepted content, supplied by the caller.
func loadOne(root, yamlPath string, minRunes int) (Task, error) {
	content, err := os.ReadFile(yamlPath)
	if err != nil {
		return Task{}, fmt.Errorf("read task file: %w", err)
	}

	spec, err := ParseSpec(content)
	if err != nil {
		return Task{}, err
	}

	dir := filepath.Dir(yamlPath)
	stem := strings.TrimSuffix(filepath.Base(yamlPath), filepath.Ext(yamlPath))
	markdownPath := filepath.Join(dir, stem+MDExt)

	markdownContent, err := os.ReadFile(markdownPath)
	if err != nil {
		if os.IsNotExist(err) {
			return Task{}, fmt.Errorf("missing task content file %s", filepath.Base(markdownPath))
		}
		return Task{}, fmt.Errorf("read task content file: %w", err)
	}

	// An empty or near-empty content file leaves the agent nothing to act on.
	// Rejecting it here keeps the task out of the schedule instead of letting it
	// fire and fail on every trigger.
	if count := utf8.RuneCountInString(strings.TrimSpace(string(markdownContent))); count < minRunes {
		return Task{}, fmt.Errorf("task content %s has %d characters, at least %d are required",
			filepath.Base(markdownPath), count, minRunes)
	}

	id, err := IDFor(root, yamlPath)
	if err != nil {
		return Task{}, err
	}

	return Task{
		ID:           id,
		Dir:          dir,
		Stem:         stem,
		YAMLPath:     yamlPath,
		MarkdownPath: markdownPath,
		LockPath:     filepath.Join(dir, stem+LockExt),
		Spec:         spec,
		Fingerprint:  fingerprint(content, markdownContent),
	}, nil
}

// fingerprint hashes the task files so a content change is detectable without
// comparing whole files on every rescan.
func fingerprint(parts ...[]byte) string {
	hash := sha256.New()
	for _, part := range parts {
		// A length prefix keeps the boundary between files unambiguous, so
		// moving bytes from one file to the next always changes the hash.
		hash.Write([]byte(strconv.Itoa(len(part))))
		hash.Write([]byte{0})
		hash.Write(part)
	}
	return hex.EncodeToString(hash.Sum(nil))
}

// ParseSpec decodes and validates a task configuration.
//
// Decoding is strict: an unknown key is an error. A silently ignored typo such
// as "schedul:" would leave the task unscheduled with no visible reason.
func ParseSpec(content []byte) (Spec, error) {
	var spec Spec

	decoder := yaml.NewDecoder(strings.NewReader(string(content)))
	decoder.KnownFields(true)
	if err := decoder.Decode(&spec); err != nil {
		if err.Error() == "EOF" {
			return Spec{}, fmt.Errorf("task configuration is empty")
		}
		return Spec{}, fmt.Errorf("parse task configuration: %w", err)
	}

	if err := spec.Validate(); err != nil {
		return Spec{}, err
	}
	return spec, nil
}

// Validate checks the fields that must be present regardless of defaults.
func (s Spec) Validate() error {
	if strings.TrimSpace(s.Schedule) == "" {
		return fmt.Errorf("schedule is required")
	}
	if err := ValidateSchedule(s.Schedule); err != nil {
		return err
	}
	for key := range s.Env {
		if strings.TrimSpace(key) == "" {
			return fmt.Errorf("env contains an empty variable name")
		}
	}
	return nil
}

// scheduleParser matches the parser the daemon's cron instance uses, so a
// schedule accepted here is one the daemon can register and vice versa.
//
// The daemon creates its cron with cron.WithSeconds(), which is this same
// option set. Keeping the two in step is the reason this parser is defined once
// here rather than rebuilt at each call site.
var scheduleParser = cron.NewParser(
	cron.Second | cron.Minute | cron.Hour | cron.Dom | cron.Month | cron.Dow | cron.Descriptor,
)

// NormalizeSchedule returns the expression in the six-field form the daemon's
// cron instance expects.
//
// A five-field expression is the familiar cron form. Because the cron runs with
// seconds enabled, a five-field expression is prefixed with a zero second field
// rather than rejected. Every caller that registers a schedule must use this
// function, so the expression that was validated is the same one that is
// registered.
func NormalizeSchedule(expression string) string {
	trimmed := strings.TrimSpace(expression)
	if len(strings.Fields(trimmed)) == 5 {
		return "0 " + trimmed
	}
	return trimmed
}

// ValidateSchedule reports whether a cron expression can be registered.
//
// Validating the expression at load time is what keeps a task with an
// unparseable schedule from being reported as healthy: without this check the
// task loads, appears idle, and is silently never registered.
func ValidateSchedule(expression string) error {
	trimmed := strings.TrimSpace(expression)
	if trimmed == "" {
		return fmt.Errorf("schedule is required")
	}
	if _, err := scheduleParser.Parse(NormalizeSchedule(trimmed)); err != nil {
		return fmt.Errorf("invalid schedule %q: %w", expression, err)
	}
	return nil
}

// IDFor derives the task id from a YAML path and the tasks root.
//
// Both a successfully loaded task and a rejected file use this one function, so
// a broken task keeps the same identity it will have once fixed. Reporting an
// absolute path for a rejected file and a relative id for a valid one would make
// the same task appear under two names.
func IDFor(root, yamlPath string) (string, error) {
	relative, err := filepath.Rel(root, yamlPath)
	if err != nil {
		return "", fmt.Errorf("compute task id: %w", err)
	}
	return strings.TrimSuffix(filepath.ToSlash(relative), filepath.Ext(relative)), nil
}
