---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-10
resolved: 2026-11-10
---

# The API document requires a comparison the Server cannot perform

## Symptom

`docs/API.md` states that a request whose `node-id` half differs from the
`node_id` in the URL path is refused with `unauthenticated`.

The Server never receives the pair. The CLI splits `node-id.node-token` locally
and sends the halves to two different places: the identifier in the URL path, the
token in `X-Connector-Node-Token`. There is no second copy of the identifier for
the Server to compare against, so the documented check has nothing to compare.

## Impact

The document describes a defence that does not exist. A reader implementing from
the document would look for a comparison that cannot be written, and a reviewer
checking the enforcement list would tick an item no code path satisfies.

The check is also unnecessary as written. The identifier in the URL is the only
identifier the Server has, so "the two disagree" cannot happen. What the Server
actually needs to guarantee is narrower: the token it forwards must be the token
the caller supplied, and it must reach the Node the URL names. Both hold by
construction, because the Server forwards the header unchanged to the connection
registered under the path identifier.

## Root cause

The sentence was written when the CLI was expected to send the whole pair in one
header, so the Server would have held both halves and could compare them. The
transport changed to two channels and the sentence was not revisited.

## Proposed fix

Replace the sentence with what the Server actually guarantees:

- The identifier in the path selects the connection; a request for an unknown
  identifier is `node_offline`.
- The token in the header is forwarded unchanged to that connection and is never
  validated, stored or compared by the Server.
- A caller that supplies a token belonging to a different Node is refused by the
  Node it reached, not by the Server, because only the Node knows its own token.

Add a note that the Server cannot detect a mismatched pair, and that this is a
consequence of the Server never holding both halves, which is the property the
design wants.

## Detection failure

The gap was found by reading the document against the implemented handler, not by
a failing test. No test asserts a behaviour the document describes but the code
does not implement, because the behaviour is unimplementable rather than missing.

## Resolution

Fixed in `docs/API.md` under "Routing". The sentence now states what the Server
actually guarantees: the path identifier selects the connection, the header token
is forwarded unchanged and never validated, and a mismatched pair is refused by the
Node rather than by the Server. The note that the Server cannot detect a mismatched
pair is included, together with the reason it cannot: the Server never holds both
halves, which is the property the design wants.
