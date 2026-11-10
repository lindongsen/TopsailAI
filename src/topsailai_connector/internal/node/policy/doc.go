// Package policy loads and evaluates the Node's policy file.
//
// The policy file is the only place a scope is defined and the only place a
// permission is granted. A secret proves a caller may talk to the Node; the
// policy decides what the caller may do once it has been admitted. There is no
// second source of authority, so there is no "which one wins" question.
//
// Everything here fails closed. A missing file, an unknown key, an undefined
// scope in a grant and an unknown permission are all startup failures rather
// than warnings, because a security configuration that is silently ignored is
// worse than one that refuses to start.
package policy
