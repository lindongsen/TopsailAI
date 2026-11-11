//go:build !windows

package node

// pathEqual compares two cleaned paths byte for byte.
//
// POSIX filesystems are case-sensitive, so two paths that differ in case are two
// different directories. Comparing them case-insensitively would accept a scope
// whose configured spelling names a directory that does not exist.
func pathEqual(left string, right string) bool {
	return left == right
}
