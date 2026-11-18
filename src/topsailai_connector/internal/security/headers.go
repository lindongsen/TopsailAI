package security

// NodeAuthHeader carries the caller's Node proof on the CLI-to-Server request.
//
// The header name lives here rather than in the Server package because the CLI builds
// the header and the Server reads it, and neither may import the other. A second
// spelling in one of them would be a request the other refuses, and the failure would
// look like a credential problem rather than a header problem.
//
// The proof is a signature over the logical operation, not a secret, so the Server can
// forward it byte for byte without learning anything it could reuse. It travels in its
// own header rather than in the body so the client proof can bind the exact transmitted
// bytes.
const NodeAuthHeader = "X-Connector-Node-Auth"

// ClientAuthHeader carries the caller's client proof.
//
// The standard Authorization header is used rather than a custom name, because a proxy
// or a log redactor already knows to treat Authorization as sensitive. The value is a
// proof, not a bearer secret, so a redactor that hides it hides a value that could not
// be reused anyway.
const ClientAuthHeader = "Authorization"

// RequestIDHeader carries the caller's correlation id.
//
// The id is signed by both proofs, so it must be the same value the CLI signed. A
// Server that generated its own id would make every Node proof fail.
const RequestIDHeader = "X-Request-Id"
