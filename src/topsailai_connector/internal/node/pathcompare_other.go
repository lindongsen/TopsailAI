//go:build !windows

package node

import "strings"

// pathEqual compares two cleaned paths byte for byte.
//
// POSIX filesystems are case-sensitive, so two paths that differ in case are two
// different directories. Comparing them case-insensitively would accept a scope
// whose configured spelling names a directory that does not exist.
func pathEqual(left string, right string) bool {
	return left == right
}

// pathHasPrefix reports whether path begins with prefix, using the platform's
// path comparison rule.
//
// The caller supplies the separator boundary in prefix, so this function only
// answers the case question. POSIX compares byte for byte because its filesystem
// does; Windows compares case-insensitively because its filesystem does.
func pathHasPrefix(path string, prefix string) bool {
	return strings.HasPrefix(path, prefix)
}
