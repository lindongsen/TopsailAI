package node

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"topsailai_connector/internal/protocol"
)

// MaxResponseBytes caps a single response payload. A file that grows without
// bound during a read would otherwise turn one request into an unbounded
// allocation, so the cap is applied to the bytes actually read rather than to
// the size reported by the filesystem.
const MaxResponseBytes = 256 * 1024

// rootSelf is the name that addresses the scope root through an os.Root handle.
// It is used internally when a caller sends the empty path, because the grammar
// refuses a `.` component from a caller while the handle needs one to name the
// directory itself.
const rootSelf = "."

// Error is a fence failure carrying the code the caller should see.
//
// The code is carried rather than derived from the message, because a caller
// must be able to tell a refusal from a missing file and a message string cannot
// express that distinction reliably.
type Error struct {
	Code   protocol.Code
	Detail string
}

// Error implements the error interface. Detail is for the Node's own log and is
// never returned to a caller: it can contain a path, and a path is exactly what
// a refusal must not disclose.
func (e *Error) Error() string {
	return fmt.Sprintf("%s: %s", e.Code.Name(), e.Detail)
}

// newError builds a fence error with a code and a detail for the log.
func newError(code protocol.Code, format string, arguments ...any) *Error {
	return &Error{Code: code, Detail: fmt.Sprintf(format, arguments...)}
}

// CodeOf reports the code a fence error carries. An error that is not a fence
// error is reported as internal, because an unclassified failure must never be
// presented as a policy decision.
func CodeOf(err error) protocol.Code {
	var fenceError *Error
	if errors.As(err, &fenceError) {
		return fenceError.Code
	}
	return protocol.CodeInternal
}

// Entry describes one directory entry or one stated path. It is the shape both
// `file.list` and `file.stat` return, so a caller parses one structure.
type Entry struct {
	Name       string `json:"name"`
	Type       string `json:"type"`
	Size       int64  `json:"size"`
	Mode       string `json:"mode"`
	ModifiedAt int64  `json:"modified_at"`
	IsSymlink  bool   `json:"is_symlink"`
	LinkTarget string `json:"link_target,omitempty"`
}

// Scope is one validated scope: a name, the directory it resolved to at startup
// and the handle every operation goes through.
//
// The handle is opened once and reused. If the directory is moved, the handle
// keeps referencing the original directory in its new location, which is the
// behaviour the fence wants: a scope means the directory that was validated, not
// whatever now occupies that name.
type Scope struct {
	name     string
	root     *os.Root
	resolved string
	denied   []os.FileInfo
}

// Name returns the scope name the policy uses.
func (s *Scope) Name() string {
	return s.name
}

// ResolvedPath returns the absolute path the scope resolved to at startup. It is
// for the Node's own log and startup report; it is never sent to a caller,
// because the Server must not learn the filesystem layout.
func (s *Scope) ResolvedPath() string {
	return s.resolved
}

// Close releases the scope handle.
func (s *Scope) Close() error {
	if s.root == nil {
		return nil
	}
	return s.root.Close()
}

// OpenScope validates a scope mapping and opens its handle.
//
// Every rule here fails startup rather than warning, because a scope that is
// accepted with a caveat is a scope whose blast radius nobody measured. The
// denyPaths are the Node's own files: their identity is recorded now, so a
// request is refused by identity rather than by name and a symlink or a
// different spelling cannot rename them.
func OpenScope(name string, path string, denyPaths []string, configDir string) (*Scope, error) {
	if err := validateScopeMapping(name, path, configDir); err != nil {
		return nil, err
	}

	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		return nil, fmt.Errorf("scope %q: resolve %q: %w", name, path, err)
	}
	if !samePath(resolved, path) {
		return nil, fmt.Errorf("scope %q: %q resolves to %q; a scope root must not be a symlink", name, path, resolved)
	}

	denied, err := collectDenied(denyPaths)
	if err != nil {
		return nil, fmt.Errorf("scope %q: %w", name, err)
	}

	root, err := os.OpenRoot(resolved)
	if err != nil {
		return nil, fmt.Errorf("scope %q: open root %q: %w", name, resolved, err)
	}

	return &Scope{name: name, root: root, resolved: resolved, denied: denied}, nil
}

// validateScopeMapping checks the rules that do not need a handle: the name is
// an identifier, the path is absolute, it exists, it is a directory, it is not a
// symlink, it is not a filesystem root, and it does not overlap the Node's own
// config directory.
//
// The config-directory rule is a startup refusal rather than a per-request deny
// because the deny list protects the contents of the Node's own files while a
// listing of the directory still reports their names and sizes. Refusing the
// overlap removes the metadata leak as well as the contents, which is why the
// design requires the check instead of treating it as redundant with the deny
// list.
func validateScopeMapping(name string, path string, configDir string) error {
	if err := validateScopeIdentifier(name); err != nil {
		return err
	}
	if path == "" {
		return fmt.Errorf("scope %q: path is empty", name)
	}
	if !filepath.IsAbs(path) {
		return fmt.Errorf("scope %q: path %q is relative; a relative path resolves differently per launch", name, path)
	}

	info, err := os.Lstat(path)
	if err != nil {
		return fmt.Errorf("scope %q: stat %q: %w", name, path, err)
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return fmt.Errorf("scope %q: path %q is a symlink; a scope root must be a real directory", name, path)
	}
	if !info.IsDir() {
		return fmt.Errorf("scope %q: path %q is not a directory", name, path)
	}
	if isFilesystemRoot(path) {
		return fmt.Errorf("scope %q: path %q is a filesystem root; its blast radius is the whole machine", name, path)
	}
	if isHomeDirectory(path) {
		return fmt.Errorf("scope %q: path %q is the home directory; its blast radius is every file the user owns", name, path)
	}
	if isMountPoint(path) {
		return fmt.Errorf("scope %q: path %q is a mount point; a scope that contains a bind mount is readable through the fence", name, path)
	}
	if overlapsConfigDir(path, configDir) {
		return fmt.Errorf("scope %q: path %q overlaps the Node's config directory %q; a scope that can list its own credentials is a configuration mistake", name, path, configDir)
	}
	return nil
}

// overlapsConfigDir reports whether a scope root and the Node's config directory
// overlap in either direction: the scope contains the config directory, the
// scope is inside it, or the two name the same directory.
//
// All three are refused because all three expose the Node's own credential files.
// A scope that contains the config directory can list it, which reports the names
// and sizes of the identity and policy files even though reading them is denied.
// A scope inside the config directory is a directory whose parent holds the
// credentials, and a scope equal to it is the same directory under another name.
//
// The comparison goes through samePath so the Windows case rule applies: a
// deny-list entry for `config` must not be bypassed by `CONFIG`, and a scope
// spelled with a different drive-letter case must still be recognised as the
// config directory.
//
// An empty configDir disables the check. That is not a relaxation: it is how a
// caller that has no config directory states that it has none, and the Node's own
// startup path always supplies one.
func overlapsConfigDir(path string, configDir string) bool {
	if configDir == "" {
		return false
	}
	cleanedScope := filepath.Clean(path)
	cleanedConfig := filepath.Clean(configDir)

	if samePath(cleanedScope, cleanedConfig) {
		return true
	}
	if isPathInside(cleanedScope, cleanedConfig) {
		return true
	}
	return isPathInside(cleanedConfig, cleanedScope)
}

// isPathInside reports whether child is inside parent, using the platform's path
// comparison rule.
//
// The check is done on cleaned paths with a separator boundary rather than with a
// string prefix, because a prefix test would treat `/home/me/project-secret` as
// inside `/home/me/project`. The boundary is what makes the answer correct; the
// prefix is only how the boundary is found.
func isPathInside(child string, parent string) bool {
	relative, err := filepath.Rel(parent, child)
	if err != nil {
		// A relative path cannot be computed across volumes on Windows, which
		// means the two paths are on different volumes and neither contains the
		// other.
		return false
	}
	if relative == "." {
		return true
	}
	if relative == ".." {
		return false
	}
	return !strings.HasPrefix(relative, ".."+string(filepath.Separator))
}

// validateScopeIdentifier checks that a scope name is an identifier. The rule is
// a whitelist rather than a blacklist, so a character nobody thought to forbid
// is still refused.
func validateScopeIdentifier(name string) error {
	if name == "" {
		return fmt.Errorf("scope name is empty")
	}
	if len(name) > 64 {
		return fmt.Errorf("scope name %q is %d bytes, want at most 64", name, len(name))
	}
	for index := 0; index < len(name); index++ {
		character := name[index]
		isLetter := character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z'
		isDigit := character >= '0' && character <= '9'
		isSeparator := character == '-' || character == '_'
		if !isLetter && !isDigit && !isSeparator {
			return fmt.Errorf("scope name %q contains %q at byte %d; a scope name is an identifier", name, character, index)
		}
	}
	first := name[0]
	if first == '-' || first == '_' {
		return fmt.Errorf("scope name %q starts with %q; a name that looks like a flag is a name that gets parsed as one", name, first)
	}
	return nil
}

// collectDenied records the identity of the Node's own files. A file that does
// not exist is skipped rather than refused, because a Node that has not written
// its identity file yet must still be able to start.
func collectDenied(paths []string) ([]os.FileInfo, error) {
	denied := make([]os.FileInfo, 0, len(paths))
	for _, path := range paths {
		if path == "" {
			continue
		}
		info, err := os.Stat(path)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			return nil, fmt.Errorf("stat deny path %q: %w", path, err)
		}
		denied = append(denied, info)
	}
	return denied, nil
}

// isDenied reports whether an opened object is one of the Node's own files. The
// comparison is by identity, so a symlink, a hard link, a different spelling and
// a case difference all resolve to the same answer.
func (s *Scope) isDenied(info os.FileInfo) bool {
	for _, denied := range s.denied {
		if os.SameFile(denied, info) {
			return true
		}
	}
	return false
}

// openValidated checks the grammar and opens the path through the scope handle.
// The open is the fence: there is no window between a check and a use, because
// the kernel refuses a name whose resolution leaves the root.
//
// The open is non-blocking on purpose. A fifo opened for reading with no writer
// blocks inside open(2), before any type check could run, so a blocking open
// would turn one request into a hang. Opening non-blocking lets the handle be
// inspected and refused, which keeps the type check reachable.
func (s *Scope) openValidated(path string, allowRoot bool) (*os.File, os.FileInfo, error) {
	if err := ValidateRelativePath(path, allowRoot); err != nil {
		return nil, nil, newError(protocol.CodeInvalidArgument, "%v", err)
	}

	name := path
	if name == "" {
		name = rootSelf
	}

	file, err := s.root.OpenFile(name, os.O_RDONLY|nonBlockFlag, 0)
	if err != nil {
		return nil, nil, classifyOpenError(err)
	}

	info, err := file.Stat()
	if err != nil {
		file.Close()
		return nil, nil, newError(protocol.CodeInternal, "stat opened %q: %v", path, err)
	}
	if s.isDenied(info) {
		file.Close()
		return nil, nil, newError(protocol.CodeDenied, "path %q is one of the Node's own files", path)
	}
	return file, info, nil
}

// classifyOpenError maps an os.Root failure to a code.
//
// Only a missing file becomes not_found. Every other failure becomes denied,
// including an escape, a symlink loop and a permission error, because the
// distinction between "the fence refused" and "the kernel refused" is not
// something a caller may probe for. The mapping is fail-closed: an error nobody
// classified is a refusal, never a success.
func classifyOpenError(err error) *Error {
	if errors.Is(err, os.ErrNotExist) {
		return newError(protocol.CodeNotFound, "open: %v", err)
	}
	return newError(protocol.CodeDenied, "open refused: %v", err)
}

// Read returns a byte range of one regular file.
//
// A non-regular file is refused rather than read, because a fifo blocks forever
// and a device file never ends: both turn one request into a hang, which is a
// denial of service with no exploit beyond the path itself.
func (s *Scope) Read(path string, offset int64, length int64) ([]byte, bool, error) {
	if offset < 0 {
		return nil, false, newError(protocol.CodeInvalidArgument, "offset %d is negative", offset)
	}
	if length < 0 {
		return nil, false, newError(protocol.CodeInvalidArgument, "length %d is negative", length)
	}

	file, info, err := s.openValidated(path, false)
	if err != nil {
		return nil, false, err
	}
	defer file.Close()

	if !info.Mode().IsRegular() {
		return nil, false, newError(protocol.CodeInvalidArgument, "path %q is not a regular file", path)
	}

	limit := int64(MaxResponseBytes)
	if length > 0 && length < limit {
		limit = length
	}

	if offset > 0 {
		if _, err := file.Seek(offset, io.SeekStart); err != nil {
			return nil, false, newError(protocol.CodeInternal, "seek %q: %v", path, err)
		}
	}

	buffer := make([]byte, limit)
	read, err := io.ReadFull(file, buffer)
	if err != nil && !errors.Is(err, io.ErrUnexpectedEOF) && !errors.Is(err, io.EOF) {
		return nil, false, newError(protocol.CodeInternal, "read %q: %v", path, err)
	}

	truncated := int64(read) == limit && limit == MaxResponseBytes
	return buffer[:read], truncated, nil
}

// List returns the entries of one directory, sorted by name so the result is
// stable across runs and a caller can diff two listings.
func (s *Scope) List(path string) ([]Entry, error) {
	file, info, err := s.openValidated(path, true)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	if !info.IsDir() {
		return nil, newError(protocol.CodeInvalidArgument, "path %q is not a directory", path)
	}

	names, err := file.Readdirnames(-1)
	if err != nil {
		return nil, newError(protocol.CodeInternal, "list %q: %v", path, err)
	}
	sort.Strings(names)

	entries := make([]Entry, 0, len(names))
	for _, name := range names {
		entry, err := s.statEntry(path, name)
		if err != nil {
			// An entry that vanished between the listing and the stat is
			// skipped rather than failing the whole listing: a directory that
			// is being written to is a normal directory.
			continue
		}
		entries = append(entries, entry)
	}
	return entries, nil
}

// statEntry describes one entry of a listed directory. The name is joined with
// the listed path so the grammar is applied to the same form a caller would send.
func (s *Scope) statEntry(parent string, name string) (Entry, error) {
	joined := name
	if parent != "" {
		joined = parent + "/" + name
	}
	if err := ValidateRelativePath(joined, false); err != nil {
		// A name the grammar refuses is reported as an entry with an unknown
		// type rather than omitted, so a listing never hides the existence of a
		// file whose name the grammar dislikes.
		return Entry{Name: name, Type: "unknown"}, nil
	}

	info, err := s.root.Lstat(joined)
	if err != nil {
		return Entry{}, err
	}
	return describe(name, info), nil
}

// Stat reports one path without following a symlink.
//
// Lstat is used rather than Stat on purpose: Stat follows the link, and following
// an escaping link is exactly the operation the fence refuses. A symlink must be
// reportable as a link, and reporting it must not reveal whether its target
// exists, because that would be an existence oracle for the whole filesystem.
func (s *Scope) Stat(path string) (Entry, error) {
	if err := ValidateRelativePath(path, false); err != nil {
		return Entry{}, newError(protocol.CodeInvalidArgument, "%v", err)
	}

	info, err := s.root.Lstat(path)
	if err != nil {
		return Entry{}, classifyOpenError(err)
	}
	if s.isDenied(info) {
		return Entry{}, newError(protocol.CodeDenied, "path %q is one of the Node's own files", path)
	}

	entry := describe(filepath.Base(path), info)
	if info.Mode()&os.ModeSymlink != 0 {
		// The target is reported as the raw link text. It is not resolved,
		// because resolving it would answer whether the target exists.
		if target, err := s.root.Readlink(path); err == nil {
			entry.LinkTarget = target
		}
	}
	return entry, nil
}

// describe converts file metadata into the wire shape.
func describe(name string, info os.FileInfo) Entry {
	return Entry{
		Name:       name,
		Type:       typeOf(info),
		Size:       info.Size(),
		Mode:       info.Mode().String(),
		ModifiedAt: info.ModTime().UTC().UnixMilli(),
		IsSymlink:  info.Mode()&os.ModeSymlink != 0,
	}
}

// typeOf names the kind of a file. The vocabulary is small and stable so a
// caller can branch on it without parsing a mode string.
func typeOf(info os.FileInfo) string {
	mode := info.Mode()
	switch {
	case mode.IsRegular():
		return "file"
	case mode.IsDir():
		return "dir"
	case mode&os.ModeSymlink != 0:
		return "symlink"
	case mode&os.ModeNamedPipe != 0:
		return "fifo"
	case mode&os.ModeSocket != 0:
		return "socket"
	case mode&os.ModeDevice != 0:
		return "device"
	default:
		return "unknown"
	}
}

// isHomeDirectory reports whether a path is the current user's home directory.
func isHomeDirectory(path string) bool {
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return false
	}
	resolvedHome, err := filepath.EvalSymlinks(home)
	if err != nil {
		resolvedHome = home
	}
	return samePath(path, resolvedHome)
}

// ModifiedAtOf is a helper for tests and callers that need the timestamp of an
// entry as a time value.
func ModifiedAtOf(entry Entry) time.Time {
	return time.UnixMilli(entry.ModifiedAt).UTC()
}
