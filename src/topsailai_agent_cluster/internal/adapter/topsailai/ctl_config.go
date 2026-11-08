package topsailai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"

	"topsailai_agent_cluster/internal/security"
)

// Placeholders a configured command template may use.
//
// A template is a token array, never a shell string: the Endpoint substitutes
// these tokens and executes the result directly, so no shell parses it and no
// operator-supplied text can become a command. A token that is not one of these
// placeholders is passed through literally.
const (
	// controlSessionPlaceholder is replaced by the provider session key the
	// Endpoint resolved from the revalidated target.
	controlSessionPlaceholder = "{session}"
	// controlPayloadPlaceholder is replaced by the operator payload, encoded as
	// one JSON object argument.
	controlPayloadPlaceholder = "{payload}"
)

// ControlAction is one enabled provider control action.
//
// Every field comes from the Endpoint-local catalog. Nothing about an action is
// declared in code, so adding, renaming or retiring an action is a configuration
// edit and never a rebuild.
type ControlAction struct {
	// Name is the action name, appended to the ctl. operation prefix.
	Name string
	// Permission is the operator scope required to invoke the action.
	Permission string
	// PayloadSchema is the JSON Schema document describing the action payload, or
	// an empty string when the action takes no documented parameters. It is
	// forwarded verbatim into the advertised capability and is never interpreted
	// by the Server.
	PayloadSchema string
	// Command is the provider argv template. It must contain at most one
	// {session} and at most one {payload} placeholder.
	Command []string
	// PayloadSessionField names a payload field that must carry the provider
	// session key. It is empty for an action that does not need the selector in
	// its payload, which is the common case.
	PayloadSessionField string
	// PayloadConstants are payload fields this action fixes itself. They are
	// merged into the payload before dispatch, so a shortcut can name one
	// instruction without asking the operator to choose it again. The values are
	// literals, never templates.
	PayloadConstants map[string]string
	// AliasOf names the action this entry is a shortcut for, or is empty for a
	// real action. A shortcut is resolved into a full copy of its target at load
	// time, so execution never follows a second lookup; the field is kept so a
	// diagnostic can tell a shortcut from the action it points at.
	AliasOf string
}

// ControlActionSet is the Endpoint-local set of enabled ctl. actions.
//
// The set is safe for concurrent use and can be replaced atomically, which is what
// makes reload possible without restarting the Endpoint. A nil set, or a set with
// no actions, disables the whole ctl. family: the catalog is the only source of
// actions, so an Endpoint without one advertises none and refuses every ctl.
// operation.
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
//
// An entry is either a real action or a shortcut. A real action declares its own
// permission, schema and command. A shortcut declares only `name` and `alias_of`,
// and inherits everything else from the action it names, so a shortcut can never
// widen a permission or change what runs.
type controlActionEntry struct {
	Name                string            `json:"name"`
	Permission          string            `json:"permission"`
	PayloadSchema       json.RawMessage   `json:"payload_schema"`
	Command             []string          `json:"command"`
	PayloadSessionField string            `json:"payload_session_field"`
	PayloadConstants    map[string]string `json:"payload_constants"`
	AliasOf             string            `json:"alias_of"`
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
// The catalog is the only source of actions, so every entry is validated here and
// a mistake fails at load time instead of at the first command. An empty action
// list is accepted and disables the whole ctl. family, because a security default
// must fail closed.
//
// An entry is either a real action or a shortcut. A shortcut is resolved into a
// full copy of the action it names, so the advertised capability, the payload
// schema and the provider argv all come from one place and a shortcut can never
// drift from its target.
//
// A line whose first non-space character is '#' is dropped before decoding, so the
// shipped example can explain itself in place. Only whole lines are dropped: a
// JSON string cannot span lines, so this rule cannot corrupt a value, and a '#'
// inside a string is preserved.
func ParseControlActionSet(data []byte) (*ControlActionSet, error) {
	var document controlActionFile
	decoder := json.NewDecoder(bytes.NewReader(stripControlActionComments(data)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&document); err != nil {
		return nil, fmt.Errorf("decode control action document: %w", err)
	}
	set := &ControlActionSet{actions: make(map[string]ControlAction, len(document.Actions))}
	// The first pass validates every name and collects the real actions. A
	// shortcut is resolved afterwards, because it may name an action declared
	// later in the file and a forward reference must not depend on file order.
	shortcuts := make([]controlActionEntry, 0, len(document.Actions))
	names := make(map[string]bool, len(document.Actions))
	for index, entry := range document.Actions {
		name, err := validateControlActionName(entry.Name)
		if err != nil {
			return nil, fmt.Errorf("action %d: %w", index, err)
		}
		if names[name] {
			return nil, fmt.Errorf("action %d: %q is listed more than once", index, name)
		}
		names[name] = true
		if strings.TrimSpace(entry.AliasOf) != "" {
			shortcuts = append(shortcuts, entry)
			continue
		}
		action, err := validateControlActionEntry(entry)
		if err != nil {
			return nil, fmt.Errorf("action %d: %w", index, err)
		}
		set.actions[action.Name] = action
	}
	// The second pass expands every shortcut into a copy of its target, so
	// execution never follows a second lookup and a reload cannot leave a
	// shortcut pointing at a stale definition.
	for index, entry := range shortcuts {
		action, err := resolveControlActionShortcut(entry, set.actions)
		if err != nil {
			return nil, fmt.Errorf("shortcut %d: %w", index, err)
		}
		set.actions[action.Name] = action
	}
	// The rendered order follows the file, so the menu matches what the operator
	// reads in the catalog.
	for _, entry := range document.Actions {
		set.order = append(set.order, strings.TrimSpace(entry.Name))
	}
	return set, nil
}

// resolveControlActionShortcut expands one shortcut into a copy of its target.
//
// A shortcut declares only its own name and the action it points at. Everything
// else is inherited, so a shortcut can never widen a permission, change the
// payload schema or run a different command than the action it names. Declaring
// any of those fields on a shortcut is rejected instead of being ignored, because
// an operator who wrote them would otherwise believe they took effect.
//
// A shortcut may not point at another shortcut. A chain would make the effective
// permission depend on resolution order, and one indirection is enough for a
// typing shortcut.
func resolveControlActionShortcut(entry controlActionEntry, actions map[string]ControlAction) (ControlAction, error) {
	name, err := validateControlActionName(entry.Name)
	if err != nil {
		return ControlAction{}, err
	}
	target := strings.TrimSpace(entry.AliasOf)
	if target == "" {
		return ControlAction{}, fmt.Errorf("%q: alias_of is required", name)
	}
	if target == name {
		return ControlAction{}, fmt.Errorf("%q: alias_of must not name itself", name)
	}
	if entry.Permission != "" || len(entry.Command) > 0 || len(bytes.TrimSpace(entry.PayloadSchema)) > 0 || strings.TrimSpace(entry.PayloadSessionField) != "" || len(entry.PayloadConstants) > 0 {
		return ControlAction{}, fmt.Errorf("%q: a shortcut inherits permission, payload_schema, command, payload_session_field and payload_constants from %q and must not declare them", name, target)
	}
	action, ok := actions[target]
	if !ok {
		return ControlAction{}, fmt.Errorf("%q: alias_of names %q, which is not a configured action", name, target)
	}
	if action.AliasOf != "" {
		return ControlAction{}, fmt.Errorf("%q: alias_of must name a real action, not the shortcut %q", name, target)
	}
	return ControlAction{
		Name:                name,
		Permission:          action.Permission,
		PayloadSchema:       action.PayloadSchema,
		Command:             append([]string(nil), action.Command...),
		PayloadSessionField: action.PayloadSessionField,
		PayloadConstants:    copyPayloadConstants(action.PayloadConstants),
		AliasOf:             target,
	}, nil
}

// copyPayloadConstants returns an independent copy of an action's constants.
//
// A shortcut shares its target's constants, so the copy keeps a later reload from
// mutating a set that is already in force.
func copyPayloadConstants(source map[string]string) map[string]string {
	if len(source) == 0 {
		return nil
	}
	copied := make(map[string]string, len(source))
	for field, value := range source {
		copied[field] = value
	}
	return copied
}

// stripControlActionComments removes whole-line '#' comments from a catalog.
//
// Only a line whose first non-space character is '#' is removed. A trailing
// comment is deliberately not supported, because deciding whether a '#' sits
// inside a string would require parsing JSON, and a wrong guess would silently
// change a value.
func stripControlActionComments(data []byte) []byte {
	lines := bytes.Split(data, []byte("\n"))
	kept := make([][]byte, 0, len(lines))
	for _, line := range lines {
		if bytes.HasPrefix(bytes.TrimSpace(line), []byte("#")) {
			continue
		}
		kept = append(kept, line)
	}
	return bytes.Join(kept, []byte("\n"))
}

// validateControlActionEntry checks one configured action.
func validateControlActionEntry(entry controlActionEntry) (ControlAction, error) {
	name, err := validateControlActionName(entry.Name)
	if err != nil {
		return ControlAction{}, err
	}
	if entry.Permission == "" {
		return ControlAction{}, fmt.Errorf("%q: permission is required", name)
	}
	if !security.KnownScope(entry.Permission) {
		return ControlAction{}, fmt.Errorf("%q: permission %q is not a defined operator scope", name, entry.Permission)
	}
	schema, err := normalizePayloadSchema(entry.PayloadSchema)
	if err != nil {
		return ControlAction{}, fmt.Errorf("%q: %w", name, err)
	}
	command, err := validateControlActionCommand(name, entry.Command)
	if err != nil {
		return ControlAction{}, err
	}
	field, err := validatePayloadSessionField(name, entry.PayloadSessionField, command)
	if err != nil {
		return ControlAction{}, err
	}
	constants, err := validatePayloadConstants(name, entry.PayloadConstants, command, field)
	if err != nil {
		return ControlAction{}, err
	}
	return ControlAction{
		Name:                name,
		Permission:          entry.Permission,
		PayloadSchema:       schema,
		Command:             command,
		PayloadSessionField: field,
		PayloadConstants:    constants,
	}, nil
}

// validateControlActionName checks the action name.
//
// The name becomes the suffix of a ctl. operation, so it must not be empty, must
// not contain whitespace, and must not repeat the ctl. prefix. Dots are allowed
// because the operation is split only on the prefix, so a dotted name such as
// pause.request stays one action.
func validateControlActionName(raw string) (string, error) {
	name := strings.TrimSpace(raw)
	if name == "" {
		return "", fmt.Errorf("name is required")
	}
	if strings.ContainsAny(name, " \t\r\n") {
		return "", fmt.Errorf("%q: name must not contain whitespace", name)
	}
	if strings.HasPrefix(name, security.ProviderControlPrefix) {
		return "", fmt.Errorf("%q: name must not repeat the %q prefix", name, security.ProviderControlPrefix)
	}
	return name, nil
}

// validateControlActionCommand checks the provider argv template.
//
// The template is a token array, so it cannot express a shell pipeline, a
// redirection or a command substitution. Each placeholder may appear at most once,
// and an unknown placeholder is rejected rather than passed through, because a
// misspelled placeholder would otherwise reach the provider as literal text.
func validateControlActionCommand(name string, raw []string) ([]string, error) {
	if len(raw) == 0 {
		return nil, fmt.Errorf("%q: command is required", name)
	}
	command := make([]string, 0, len(raw))
	sessionCount := 0
	payloadCount := 0
	for index, token := range raw {
		if token == "" {
			return nil, fmt.Errorf("%q: command token %d is empty", name, index)
		}
		if err := validateCommandPlaceholders(name, token); err != nil {
			return nil, err
		}
		sessionCount += strings.Count(token, controlSessionPlaceholder)
		payloadCount += strings.Count(token, controlPayloadPlaceholder)
		command = append(command, token)
	}
	if sessionCount > 1 {
		return nil, fmt.Errorf("%q: command uses %s more than once", name, controlSessionPlaceholder)
	}
	if payloadCount > 1 {
		return nil, fmt.Errorf("%q: command uses %s more than once", name, controlPayloadPlaceholder)
	}
	return command, nil
}

// validateCommandPlaceholders rejects an unknown placeholder in one token.
func validateCommandPlaceholders(name, token string) error {
	remaining := token
	for {
		start := strings.Index(remaining, "{")
		if start < 0 {
			return nil
		}
		end := strings.Index(remaining[start:], "}")
		if end < 0 {
			return fmt.Errorf("%q: command token %q has an unterminated placeholder", name, token)
		}
		placeholder := remaining[start : start+end+1]
		if placeholder != controlSessionPlaceholder && placeholder != controlPayloadPlaceholder {
			return fmt.Errorf("%q: command token %q uses unknown placeholder %q", name, token, placeholder)
		}
		remaining = remaining[start+end+1:]
	}
}

// validatePayloadSessionField checks the payload field that carries the selector.
//
// Injecting the selector into the payload only makes sense when the command also
// forwards the payload, so a field without a {payload} placeholder is rejected
// instead of being silently ignored.
func validatePayloadSessionField(name, raw string, command []string) (string, error) {
	field := strings.TrimSpace(raw)
	if field == "" {
		return "", nil
	}
	if strings.ContainsAny(field, " \t\r\n") {
		return "", fmt.Errorf("%q: payload_session_field must not contain whitespace", name)
	}
	for _, token := range command {
		if strings.Contains(token, controlPayloadPlaceholder) {
			return field, nil
		}
	}
	return "", fmt.Errorf("%q: payload_session_field requires a %s placeholder in command", name, controlPayloadPlaceholder)
}

// validatePayloadConstants checks the payload fields an action fixes itself.
//
// A constant lets one catalog entry pin a payload field, so a shortcut such as
// ctl.git.status submits the instruction it names without asking the operator to
// choose it again. The value is a literal string, never a template, because a
// constant that could expand would reintroduce the operator-controlled command
// this catalog exists to prevent.
func validatePayloadConstants(name string, raw map[string]string, command []string, sessionField string) (map[string]string, error) {
	if len(raw) == 0 {
		return nil, nil
	}
	constants := make(map[string]string, len(raw))
	for field, value := range raw {
		trimmed := strings.TrimSpace(field)
		if trimmed == "" {
			return nil, fmt.Errorf("%q: payload_constants has an empty field name", name)
		}
		if strings.ContainsAny(trimmed, " \t\r\n") {
			return nil, fmt.Errorf("%q: payload_constants field %q must not contain whitespace", name, trimmed)
		}
		if trimmed == sessionField {
			return nil, fmt.Errorf("%q: payload_constants field %q is also the payload_session_field", name, trimmed)
		}
		if strings.Contains(value, "{") {
			return nil, fmt.Errorf("%q: payload_constants field %q must be a literal value, not a template", name, trimmed)
		}
		constants[trimmed] = value
	}
	for _, token := range command {
		if strings.Contains(token, controlPayloadPlaceholder) {
			return constants, nil
		}
	}
	return nil, fmt.Errorf("%q: payload_constants requires a %s placeholder in command", name, controlPayloadPlaceholder)
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
