//go:build !unix

package node

// nonBlockFlag is zero on platforms where a fifo cannot be opened this way, so
// the open keeps its ordinary blocking semantics. The type check still refuses a
// non-regular file; only the hang it prevents is POSIX-specific.
const nonBlockFlag = 0
