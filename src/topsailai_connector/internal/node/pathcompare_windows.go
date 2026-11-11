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
