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
	// deniedPrefixes are the deny-listed directories expressed as paths
	// relative to the scope root, in slash form. A request whose path equals one
	// of them or sits inside one is refused before it is opened.
	//
	// The identity comparison in denied covers a file, but it cannot cover a
	// directory's contents: a file created inside a denied directory is a
	// different inode, so it would not match. The prefix rule is what makes a
	// denied directory deny everything beneath it, which is the property the
	// config directory needs once a scope may contain it.
	deniedPrefixes []string
	// deniedDirs are the deny-listed directories by identity. They are what
	// makes the deny list survive an alias: a symlink inside the scope that
	// points at a denied directory is a different written path, so the prefix
	// rule cannot see it, and a file reached through that link is a different
	// inode, so the file comparison cannot see it either. Comparing the identity
	// of every symlinked ancestor is the rule that closes both gaps at once.
	deniedDirs []os.FileInfo
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
//
// This entry point never permits a scope rooted at a filesystem root. The opt-in
// lives in the policy file and is applied by LoadAuthority, so a caller that has
// not read a policy cannot widen the fence by accident.
func OpenScope(name string, path string, denyPaths []string, configDir string) (*Scope, error) {
	return openScope(name, path, denyPaths, configDir, false)
}

// openScope is OpenScope with the policy's filesystem-root opt-in applied.
//
// allowFilesystemRoot is true only when the policy file states
// `allow_filesystem_root: true`. It relaxes exactly two startup refusals: a scope
// rooted at a filesystem root, and a scope that contains the Node's config
// directory. The second follows from the first rather than being a separate
// permission: a scope rooted at `C:\` necessarily contains the config directory,
// so refusing the overlap would make the opt-in unusable.
//
// Relaxing the overlap is safe only because the config directory is itself on the
// deny list, so listing it is refused and its contents are never reported. The
// deny list carries the protection once the startup refusal is gone.
func openScope(name string, path string, denyPaths []string, configDir string, allowFilesystemRoot bool) (*Scope, error) {
	if err := validateScopeMapping(name, path, configDir, allowFilesystemRoot); err != nil {
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

	deniedDirs, err := collectDeniedDirs(denyPaths)
	if err != nil {
		return nil, fmt.Errorf("scope %q: %w", name, err)
	}

	deniedPrefixes, err := collectDeniedPrefixes(denyPaths, resolved)
	if err != nil {
		return nil, fmt.Errorf("scope %q: %w", name, err)
	}

	root, err := os.OpenRoot(resolved)
	if err != nil {
		return nil, fmt.Errorf("scope %q: open root %q: %w", name, resolved, err)
	}

	return &Scope{
		name:           name,
		root:           root,
		resolved:       resolved,
		denied:         denied,
		deniedPrefixes: deniedPrefixes,
		deniedDirs:     deniedDirs,
	}, nil
}

// collectDeniedPrefixes expresses every deny path that is a directory as a path
// relative to the scope root, so a request inside it can be refused before it is
// opened.
//
// A deny path outside the scope root is skipped: it cannot be addressed through
// this scope, so it needs no prefix. A deny path equal to the scope root is
// refused as a startup failure, because a scope whose root is denied is a scope
// that serves nothing and the operator should be told rather than left with a
// Node that denies every request.
func collectDeniedPrefixes(denyPaths []string, scopeRoot string) ([]string, error) {
	prefixes := make([]string, 0, len(denyPaths))
	for _, path := range denyPaths {
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
		if !info.IsDir() {
			continue
		}
		if samePath(path, scopeRoot) {
			return nil, fmt.Errorf("deny path %q is the scope root; a scope whose root is denied serves nothing", path)
		}
		if !isPathInside(path, scopeRoot) {
			continue
		}
		relative, err := filepath.Rel(scopeRoot, path)
		if err != nil {
			return nil, fmt.Errorf("relativise deny path %q: %w", path, err)
		}
		prefixes = append(prefixes, filepath.ToSlash(relative))
	}
	return prefixes, nil
}

// isDeniedPath reports whether a request path names a deny-listed directory or
// something inside one.
//
// The comparison is on cleaned slash-form paths with a separator boundary, so a
// sibling whose name merely starts with the denied directory's name is not
// refused. The path is compared as the caller wrote it, before any open, so a
// denied directory is refused even when the entry inside it does not exist yet.
//
// The case rule is the platform's, through pathHasPrefix and pathEqual, because
// the deny list protects a directory the filesystem treats as one directory. A
// byte-for-byte comparison on Windows would let `CONFIG` reach `config`, which is
// the same bypass the fence refuses elsewhere.
func (s *Scope) isDeniedPath(path string) bool {
	if len(s.deniedPrefixes) == 0 {
		return false
	}
	cleaned := filepath.ToSlash(filepath.Clean(path))
	if cleaned == "." {
		return false
	}
	for _, prefix := range s.deniedPrefixes {
		if pathEqual(cleaned, prefix) {
			return true
		}
		if pathHasPrefix(cleaned, prefix+"/") {
			return true
		}
	}
	return false
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
//
// allowFilesystemRoot relaxes the filesystem-root and config-overlap refusals
// together, because a scope rooted at a volume necessarily contains the config
// directory. Every other rule still applies: the path must be absolute, real, a
// directory and not a symlink, and the fence still refuses every path that leaves
// the root.
func validateScopeMapping(name string, path string, configDir string, allowFilesystemRoot bool) error {
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
	if !allowFilesystemRoot && isFilesystemRoot(path) {
		return fmt.Errorf("scope %q: path %q is a filesystem root; its blast radius is the whole machine", name, path)
	}
	if isHomeDirectory(path) {
		return fmt.Errorf("scope %q: path %q is the home directory; its blast radius is every file the user owns", name, path)
	}
	if isMountPoint(path) {
		return fmt.Errorf("scope %q: path %q is a mount point; a scope that contains a bind mount is readable through the fence", name, path)
	}
	if !allowFilesystemRoot && overlapsConfigDir(path, configDir) {
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

// collectDeniedDirs records the identity of the deny-listed directories. A path
// that is not a directory, or that does not exist, is skipped for the same
// reason collectDenied skips it: a file is already covered by the file
// comparison, and a Node that has not written its config yet must still start.
func collectDeniedDirs(paths []string) ([]os.FileInfo, error) {
	dirs := make([]os.FileInfo, 0, len(paths))
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
		if !info.IsDir() {
			continue
		}
		dirs = append(dirs, info)
	}
	return dirs, nil
}

// isDeniedDir reports whether an object is one of the deny-listed directories.
func (s *Scope) isDeniedDir(info os.FileInfo) bool {
	for _, dir := range s.deniedDirs {
		if os.SameFile(dir, info) {
			return true
		}
	}
	return false
}

// isDeniedAncestor reports whether any directory on the way to path is one of
// the deny-listed directories.
//
// The written-path rule cannot see an alias, because an alias is a different
// written path, and the file rule cannot see a file that is not itself listed.
// Resolving each ancestor and comparing its identity closes both gaps at once: a
// symlink that points at a denied directory resolves to that directory, so every
// path reached through it is refused.
//
// A failure to resolve an ancestor ends the walk rather than being ignored. The
// open that follows resolves the same components, so an ancestor that cannot be
// resolved here cannot be traversed there either, and the open reports the
// refusal.
func (s *Scope) isDeniedAncestor(path string) bool {
	if len(s.deniedDirs) == 0 {
		return false
	}
	cleaned := filepath.ToSlash(filepath.Clean(path))
	if cleaned == "." || cleaned == "" {
		return false
	}
	parts := strings.Split(cleaned, "/")
	for i := 1; i <= len(parts); i++ {
		info, err := s.root.Stat(strings.Join(parts[:i], "/"))
		if err != nil {
			return false
		}
		if s.isDeniedDir(info) {
			return true
		}
	}
	return false
}

// resolvesToDeniedDir reports whether a symlink resolves to a deny-listed
// directory. It is used when listing and when stating one path, where the
// ancestors of the path have already been checked and only the entry itself can
// still be an alias.
//
// The target is resolved outside the scope handle rather than through it. A
// relative target that leaves the root cannot be resolved through the handle,
// because os.Root refuses it, and that refusal is exactly the case this function
// has to answer: an alias pointing at the Node's own directory from inside a
// scope that does not contain it. Resolving it here is a stat, never an open, so
// it answers "is this one of my own directories" without reading anything.
func (s *Scope) resolvesToDeniedDir(path string) bool {
	if len(s.deniedDirs) == 0 {
		return false
	}
	if info, err := s.root.Stat(path); err == nil {
		return s.isDeniedDir(info)
	}
	target, err := s.root.Readlink(path)
	if err != nil {
		return false
	}
	if !filepath.IsAbs(target) {
		target = filepath.Join(filepath.Dir(filepath.Join(s.resolved, path)), target)
	}
	info, err := os.Stat(target)
	if err != nil {
		return false
	}
	return s.isDeniedDir(info)
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
	if s.isDeniedPath(path) {
		return nil, nil, newError(protocol.CodeDenied, "path %q is inside one of the Node's own directories", path)
	}
	if s.isDeniedAncestor(path) {
		return nil, nil, newError(protocol.CodeDenied, "path %q reaches one of the Node's own directories through an alias", path)
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
		if entry.Type == deniedEntryType {
			// A deny-listed entry is omitted rather than reported, so a listing
			// never discloses the name or the size of the Node's own files. The
			// omission is the reason a scope may contain the config directory at
			// all: the startup refusal is gone, so the listing must not leak what
			// the refusal used to hide.
			continue
		}
		entries = append(entries, entry)
	}
	return entries, nil
}

// deniedEntryType marks a listed entry that the deny list covers. It is an
// internal sentinel rather than a wire value: List drops it, so a caller never
// sees it.
const deniedEntryType = "denied"

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
	if s.isDeniedPath(joined) {
		return Entry{Name: name, Type: deniedEntryType}, nil
	}
	if s.isDeniedAncestor(joined) || s.resolvesToDeniedDir(joined) {
		return Entry{Name: name, Type: deniedEntryType}, nil
	}

	info, err := s.root.Lstat(joined)
	if err != nil {
		return Entry{}, err
	}
	if s.isDenied(info) {
		return Entry{Name: name, Type: deniedEntryType}, nil
	}
	return describe(name, info), nil
}

// Stat reports one path without following a symlink.
//
// Lstat is used rather than Stat on purpose: Stat follows the link, and following
// an escaping link is exactly the operation the fence refuses. A symlink must be
// reportable as a link, and reporting it must not reveal whether its target
// exists, because that would be an existence oracle for the whole filesystem.
//
// A link that resolves to one of the Node's own directories is refused rather
// than reported. The deny list answers by identity, so the same directory must
// get the same answer whichever name reaches it: `config` is refused, therefore
// an alias that resolves to `config` is refused too.
//
// Reporting the link with its target withheld was the earlier behaviour, and it
// was wrong twice over. It answered differently depending on whether the alias
// escaped the scope root, because an escaping alias cannot be resolved through
// the handle, so the same alias was refused under a whole-volume scope and
// reported under a subdirectory scope. And it disclosed the layout anyway: a
// symlink's reported size is the length of its target, so withholding the target
// while reporting its length answered the question the withholding was meant to
// refuse.
func (s *Scope) Stat(path string) (Entry, error) {
	if err := ValidateRelativePath(path, false); err != nil {
		return Entry{}, newError(protocol.CodeInvalidArgument, "%v", err)
	}
	if s.isDeniedPath(path) {
		return Entry{}, newError(protocol.CodeDenied, "path %q is inside one of the Node's own directories", path)
	}
	if s.isDeniedAncestor(path) {
		return Entry{}, newError(protocol.CodeDenied, "path %q reaches one of the Node's own directories through an alias", path)
	}
	if s.resolvesToDeniedDir(path) {
		return Entry{}, newError(protocol.CodeDenied, "path %q is an alias to one of the Node's own directories", path)
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
