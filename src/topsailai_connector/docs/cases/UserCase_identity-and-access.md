---
maintainer: AI
author: DawsonLin
---

# User Cases

What a person is trying to accomplish. These are the stories the BDD scenarios
are written from; the technical cases in the other files exist to make these
stories safe.

## UC-1: An operator reads a file on their own machine from a laptop

**Actor:** Operator, holding a `client_token` and a `node-id.node-token` pair.

**Story:** The operator is on a laptop away from home. A file lives on the desktop
machine at home. They want to read it without opening a port on the home router.

**Steps:**

1. The home machine runs `connector-node`, which dials out to the Server.
2. The operator runs `connector-server cli --scope project --path notes.md file.read`.
3. The CLI sends `client_token` and the pair to the Server.
4. The Server compares `client_token`, checks the `node-id`, forwards the
   `node-token`.
5. The Node compares `node-token`, resolves `project`, checks the policy, reads the
   file.
6. The content comes back.

**Acceptance:** The content arrives, and the home machine accepted no inbound
connection at any point.

## UC-2: A stolen `client_token` does not read a file

**Actor:** An attacker who has obtained the `client_token` but not a
`node-id.node-token` pair.

**Story:** The `client_token` leaked, perhaps from a shell history. The attacker can
reach the Server. They must not be able to read anything.

**Steps:**

1. The attacker sends a request with a valid `client_token` and a guessed
   `node-token`.
2. The Server accepts the `client_token` and forwards the request, because it
   cannot check the `node-token`.
3. The Node compares the `node-token`, finds it wrong, refuses.

**Acceptance:** The attacker learns that the request was refused and nothing else.
No file content, no directory listing, no confirmation that the `node-id` exists.

**Why this story matters:** it is the reason the two secrets are separate. If the
Server could authorise an operation, a leaked `client_token` would be enough.

## UC-3: A stolen `node-token` does not open a channel

**Actor:** An attacker who has obtained a `node-id.node-token` pair but not the
`tunnel_token`.

**Story:** The pair leaked, perhaps copied to the wrong machine. The attacker must
not be able to connect as that Node, and must not be able to use the pair to reach
a different Node.

**Steps:**

1. The attacker dials the Server and sends `hello` with a guessed `tunnel_token`.
2. The Server compares `tunnel_token`, finds it wrong, closes the connection.

**Acceptance:** The connection closes before any frame is accepted. The attacker
cannot use the pair at all, because the pair is only ever checked by a Node.

## UC-4: The Node regenerates its identity after a suspected leak

**Actor:** Operator who believes the `node-token` leaked.

**Story:** The pair was pasted into a chat window. The operator wants the old value
to stop working, immediately, without provisioning anything new on the Server.

**Steps:**

1. The operator runs `connector-node regenerate`.
2. The Node writes a new pair, discards the old `node-token`, and drops the live
   channel.
3. The operator copies the new pair to the CLI.
4. A request carrying the old `node-token` is refused.

**Acceptance:** The old `node-token` is refused on the very next request, with no
grace period. The `tunnel_token` and `client_token` are unchanged, so nothing on the
Server needs reconfiguring.

**Why this story matters:** it is the only revocation mechanism the model has, so it
has to be cheap enough to use on suspicion rather than only on proof.

## UC-5: The Server is compromised

**Actor:** An attacker with root on the Server.

**Story:** The Server host is lost. What does the attacker get?

**Steps:**

1. The attacker reads the Server's environment and finds `tunnel_token` and
   `client_token`.
2. The attacker reads the Server's disk and finds no `node-token`, because the
   Server never stored one.
3. The attacker can open a channel as a Node and can call the API as a client.
4. The attacker still cannot read a file, because a `node-token` is required and
   none is stored.

**Acceptance:** The attacker gains the ability to connect and to call, and does not
gain the ability to operate. Reading a file still requires a `node-token` that the
Server never held.

**Why this story matters:** it is the concrete payoff of the "the Server never
stores a Node token" rule. Without it, a compromised Server yields every stored
credential at once.

## UC-6: A Node is offline

**Actor:** Operator whose home machine is asleep.

**Story:** The operator sends a request while the Node is not connected.

**Steps:**

1. The CLI sends the request.
2. The Server compares `client_token`, finds the `node-id` has no live channel.
3. The Server refuses.

**Acceptance:** The refusal is immediate and says the Node is not connected. The
request is not queued, because a queued request would execute later without the
operator knowing, and the operator would have no way to cancel it.

## UC-7: An operator adds a second scope

**Actor:** Operator who wants to expose a scratch directory as well as a project.

**Story:** A second directory should be readable, and the first should stay
read-only.

**Steps:**

1. The operator adds a `scratch` scope to the policy file.
2. The operator sends `SIGHUP`.
3. A request for `scratch` succeeds; a request for `project` with `write` is still
   refused.

**Acceptance:** The new scope works without restarting the Node, and the old scope's
permissions are unchanged. A policy file that fails validation leaves the previous
policy in force.

## UC-8: A Windows machine serves a scope

**Actor:** Operator whose desktop runs Windows.

**Story:** The same story as UC-1, on Windows.

**Steps:**

1. The Node runs on Windows with a scope pointing at `C:\Users\me\project`.
2. The operator reads `notes.md`.
3. The operator tries `..\outside\secret.txt`.

**Acceptance:** The read succeeds and the traversal is refused, with the same error
code as on POSIX. The platform changes the set of rejected names, not the outcome.
