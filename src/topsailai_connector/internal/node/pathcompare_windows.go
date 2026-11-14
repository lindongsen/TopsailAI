//go:build windows

package node

import "strings"

// pathEqual compares two cleaned paths the way the Windows filesystem does:
// case-insensitively.
//
// A case-sensitive comparison would refuse a legitimate scope whose configured
// spelling differs from the spelling EvalSymlinks reports, because EvalSymlinks
// rewrites the drive letter and every component to the case stored on disk. The
// refusal would name a symlink that does not exist, which is the worst kind of
// error message: it sends the operator looking for a link instead of a spelling.
func pathEqual(left string, right string) bool {
	return strings.EqualFold(left, right)
}

// pathHasPrefix reports whether path begins with prefix, using the Windows
// filesystem's case rule.
//
// The deny list is compared against the path the caller wrote, before the open,
// so a case-sensitive comparison would let a caller reach a file inside a denied
// directory by changing the spelling: `CONFIG` and `config` are the same
// directory on Windows, and the identity comparison cannot refuse a file inside
// the directory because that file is a different inode from the directory itself.
func pathHasPrefix(path string, prefix string) bool {
	return len(path) >= len(prefix) && strings.EqualFold(path[:len(prefix)], prefix)
}
