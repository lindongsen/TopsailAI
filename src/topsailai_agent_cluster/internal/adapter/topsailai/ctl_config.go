package topsailai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"sync"
	"syscall"
)

// ControlAction is one enabled provider control action.
//
// Permission is carried explicitly so an operator reading the file can see which
// scope each action needs. It must equal the reviewed permission for that action:
// the file selects actions, it never widens what an action requires.
type ControlAction struct {
	// Name is the provider action name, appended to the ctl. operation prefix.
	Name string
	// Permission is the operator scope required to invoke the action.
	Permission string
	// PayloadSchema is the JSON Schema document describing the action payload, or
	// an empty string when the action takes no documented parameters. It is
	// forwarded verbatim into the advertised capability and is never interpreted
	// by the Server.
	PayloadSchema string
}

// ControlActionSet is the Endpoint-local set of enabled ctl. actions.
//
// The set is safe for concurrent use and can be replaced atomically, which is what
// makes reload possible without restarting the Endpoint. A nil set means the file
// was not configured, so the reviewed default set stays in force; a non-nil set
// with no actions disables the whole ctl. family.
type ControlActionSet struct {
	// Path is the file this set was loaded from, used by ReloadFromDisk. It is
	// empty for a set built directly from bytes.
	Path    string
	mu      sync.RWMutex
	actions map[string]ControlAction
	order   []string
}

// controlActionFile is the on-disk document shape.
type controlActionFile struct {
	Actions []controlActionEntry `json:"actions"`
}

// controlActionEntry is one configured action before validation.
type controlActionEntry struct {
	Name          string          `json:"name"`
	Permission    string          `json:"permission"`
	PayloadSchema json.RawMessage `json:"payload_schema"`
}

// LoadControlActionSet reads and validates the control action file at path.
func LoadControlActionSet(path string) (*ControlActionSet, error) {
	if path == "" {
		return nil, fmt.Errorf("control action file path is required")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read control action file %q: %w", path, err)
	}
	set, err := ParseControlActionSet(data)
	if err != nil {
		return nil, fmt.Errorf("parse control action file %q: %w", path, err)
	}
	set.Path = path
	return set, nil
}

// ParseControlActionSet parses and validates a control action document.
//
// Every name must be a reviewed provider action, so a typo fails at load time
// instead of at the first command. Every permission must equal the reviewed
// permission, so the file cannot widen what an action requires. An empty action
// list is accepted and disables the whole ctl. family, because a security default
// must fail closed once an operator has explicitly configured the file.
func ParseControlActionSet(data []byte) (*ControlActionSet, error) {
	var document controlActionFile
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&document); err != nil {
		return nil, fmt.Errorf("decode control action document: %w", err)
	}
	set := &ControlActionSet{actions: make(map[string]ControlAction, len(document.Actions))}
	for index, entry := range document.Actions {
		action, err := validateControlActionEntry(entry)
		if err != nil {
			return nil, fmt.Errorf("action %d: %w", index, err)
		}
		if _, exists := set.actions[action.Name]; exists {
			return nil, fmt.Errorf("action %d: %q is listed more than once", index, action.Name)
		}
		set.actions[action.Name] = action
		set.order = append(set.order, action.Name)
	}
	return set, nil
}

// validateControlActionEntry checks one configured action against the reviewed set.
func validateControlActionEntry(entry controlActionEntry) (ControlAction, error) {
	if entry.Name == "" {
		return ControlAction{}, fmt.Errorf("name is required")
	}
	reviewed, ok := controlActionPermission(entry.Name)
	if !ok {
		return ControlAction{}, fmt.Errorf("%q is not a reviewed provider control action", entry.Name)
	}
	if entry.Permission == "" {
		return ControlAction{}, fmt.Errorf("%q: permission is required", entry.Name)
	}
	if entry.Permission != reviewed {
		return ControlAction{}, fmt.Errorf("%q: permission %q does not match the reviewed permission %q", entry.Name, entry.Permission, reviewed)
	}
	schema, err := normalizePayloadSchema(entry.PayloadSchema)
	if err != nil {
		return ControlAction{}, fmt.Errorf("%q: %w", entry.Name, err)
	}
	return ControlAction{Name: entry.Name, Permission: entry.Permission, PayloadSchema: schema}, nil
}

// normalizePayloadSchema validates a payload schema and returns it as a compact
// JSON string. An absent schema is allowed and yields an empty string, so a
// minimal file still works and the interactive surface falls back to its generic
// parameter prompt.
func normalizePayloadSchema(raw json.RawMessage) (string, error) {
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 || bytes.Equal(trimmed, []byte("null")) {
		return "", nil
	}
	var document map[string]json.RawMessage
	if err := json.Unmarshal(trimmed, &document); err != nil {
		return "", fmt.Errorf("payload_schema must be a JSON object: %w", err)
	}
	if document == nil {
		return "", fmt.Errorf("payload_schema must be a JSON object")
	}
	compact, err := json.Marshal(document)
	if err != nil {
		return "", fmt.Errorf("encode payload_schema: %w", err)
	}
	return string(compact), nil
}

// ReloadFromDisk re-reads the file this set was loaded from and swaps the
// actions atomically. A read or parse failure keeps the previous set in force and
// returns the error, so a broken edit cannot widen or disable the policy.
func (s *ControlActionSet) ReloadFromDisk() error {
	if s == nil {
		return fmt.Errorf("control action set is not configured")
	}
	s.mu.RLock()
	path := s.Path
	s.mu.RUnlock()
	if path == "" {
		return fmt.Errorf("control action set has no source path")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read control action file %q: %w", path, err)
	}
	if err := s.Reload(data); err != nil {
		return fmt.Errorf("parse control action file %q: %w", path, err)
	}
	return nil
}

// Reload replaces the enabled actions atomically. A parse failure keeps the
// previous set in force and returns the error, so a broken edit cannot widen or
// disable the policy.
func (s *ControlActionSet) Reload(data []byte) error {
	replacement, err := ParseControlActionSet(data)
	if err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.actions = replacement.actions
	s.order = replacement.order
	return nil
}

// Actions returns the enabled actions in file order.
func (s *ControlActionSet) Actions() []ControlAction {
	if s == nil {
		return nil
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := make([]ControlAction, 0, len(s.order))
	for _, name := range s.order {
		result = append(result, s.actions[name])
	}
	return result
}

// Get returns one enabled action by name.
func (s *ControlActionSet) Get(name string) (ControlAction, bool) {
	if s == nil {
		return ControlAction{}, false
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	action, ok := s.actions[name]
	return action, ok
}

// Len returns the number of enabled actions.
func (s *ControlActionSet) Len() int {
	if s == nil {
		return 0
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.order)
}

// Names returns the enabled action names in file order, for startup logging.
func (s *ControlActionSet) Names() []string {
	if s == nil {
		return nil
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	return append([]string(nil), s.order...)
}

// WatchReload reloads the control action file on SIGHUP until the returned stop
// function is called or the context is cancelled.
//
// SIGHUP is registered explicitly because Go terminates a process on SIGHUP by
// default, so without this handler the reload signal would kill the Endpoint. The
// reload parses the new document completely before swapping it, so a parse failure
// keeps the previous set in force and never leaves an empty set enabled.
func (s *ControlActionSet) WatchReload(ctx context.Context, onReload func(error)) (func(), error) {
	if s == nil {
		return nil, fmt.Errorf("control action set is not configured")
	}
	watchCtx, cancel := context.WithCancel(ctx)
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGHUP)
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			select {
			case <-watchCtx.Done():
				return
			case <-signals:
				if onReload != nil {
					onReload(s.ReloadFromDisk())
				}
			}
		}
	}()
	var once sync.Once
	stop := func() {
		once.Do(func() {
			signal.Stop(signals)
			cancel()
			<-done
		})
	}
	return stop, nil
}
