// Package server holds the cloud-side implementation: the listener, the
// connection registry and the operation dispatch toward connected Nodes.
//
// It may import internal/protocol and internal/security. It must never import
// internal/node, because the Node binary must not carry server code and the
// Server binary must not carry node code.
//
// The Server is a pipe, not an authority. It authenticates the caller with its
// own client token, finds the live channel for the requested node id and
// forwards the request unchanged. It does not decide whether an operation is
// allowed, because the policy that answers that question lives on the Node and
// the Server never sees it.
//
// Two rules shape every type in this package:
//
//   - The Server never stores a Node token. A node token exists only as a field
//     of the request being forwarded. No field, map, log line, audit record or
//     derived value such as a hash or prefix may hold it.
//   - The Server never stores a scope table or a permission table. It has no
//     opinion about which scope exists or which permission is granted, so it
//     cannot widen a caller's authority even if it is compromised.
package server
