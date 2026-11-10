// Package node holds the personal-computer implementation: the outbound dialer,
// the reconnect loop and the operation handlers that enforce the local policy.
//
// It may import internal/protocol and internal/security. It must never import
// internal/server, because the Server binary must not carry node code.
package node
