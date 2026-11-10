// Package server holds the cloud-side implementation: the listener, the
// connection registry and the operation dispatch toward connected Nodes.
//
// It may import internal/protocol and internal/security. It must never import
// internal/node, because the Node binary must not carry server code.
package server
