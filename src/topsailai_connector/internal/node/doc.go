// Package node holds the personal-computer implementation: the outbound dialer,
// the reconnect loop and the operation handlers that enforce the local policy.
//
// It may import internal/protocol and internal/security. It must never import
// internal/server, because the Server binary must not carry node code.
//
// The path fence lives here. A Scope wraps an os.Root handle, so the kernel
// refuses any name whose resolution leaves the scope directory; there is no
// window between a check and a use, because the check and the use are the same
// open. The grammar in path.go runs first and refuses traversal, absolute paths,
// NUL bytes, backslashes, colons, control characters, trailing dots and spaces,
// and the Windows device names, so the value that is checked is the value that
// is opened.
package node
