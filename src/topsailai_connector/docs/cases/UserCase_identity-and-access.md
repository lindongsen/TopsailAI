---
maintainer: AI
author: DawsonLin
---

# User Cases

What a person is trying to accomplish. These are the stories the BDD scenarios
are written from; the technical cases in the other files exist to make these
stories safe.

A caller holds two credentials, one per gate. A client credential proves the caller
may use the Server; a node credential proves the caller may talk to one Node.
Neither is transmitted: the caller signs a proof, and the verifier looks the secret
up by a public `key_id`. Neither carries a permission; the Node's policy file is
the only place a permission is granted.

## UC-1: An operator reads a file on their own machine from a laptop

**Actor:** Operator, holding a client credential and a node credential.

**Story:** The operator is on a laptop away from home. A file lives on the desktop
machine at home. They want to read it without opening a port on the home router.

**Steps:**

1. The home machine runs `connector-node`, which dials out to the Server.
2. The operator runs
   `connector-server cli --scope project --path notes.md file.read`.
3. The CLI signs a client proof with the client credential and a node proof with
   the node credential, then sends both.
4. The Server verifies the client proof, checks that the `node-id` in the URL
   matches the one the caller addressed, and forwards the node proof unchanged.
5. The Node verifies the node proof, resolves `project`, checks the policy, reads
   the file.
6. The content comes back.

**Acceptance:** The content arrives, and the home machine accepted no inbound
connection at any point. Neither secret crossed the network.

## UC-2: A stolen client credential does not read a file

**Actor:** An attacker who has obtained the client credential but not a node
credential.

**Story:** The client credential leaked, perhaps from a shell history. The attacker
can reach the Server. They must not be able to read anything.

**Steps:**

1. The attacker signs a valid client proof and a node proof with a guessed secret.
2. The Server verifies the client proof and forwards the request, because it cannot
   verify the node proof.
3. The Node verifies the node proof, finds the signature wrong, refuses with
   `unauthenticated`.

**Acceptance:** The attacker learns that the request was refused and nothing else.
No file content, no directory listing, no confirmation that the `node-id` exists.

**Why this story matters:** it is the reason the two credentials are separate. If
the Server could authorise an operation, a leaked client credential would be enough.

## UC-3: A stolen node credential does not open a channel

**Actor:** An attacker who has obtained a node credential but not the
`tunnel_token`.

**Story:** The credential leaked, perhaps copied to the wrong machine. The attacker
must not be able to connect as that Node, and must not be able to use the credential
to reach a different Node.

**Steps:**

1. The attacker dials the Server and sends `hello` with a guessed `tunnel_token`.
2. The Server compares `tunnel_token`, finds it wrong, closes the connection.

**Acceptance:** The connection closes before any frame is accepted. The attacker
cannot use the credential at all, because a node credential is only ever verified by
a Node, and only on an operation.

## UC-4: The operator retires a leaked node credential

**Actor:** Operator who believes a node credential leaked.

**Story:** The credential was pasted into a chat window. The operator wants it to
stop working, immediately, without provisioning anything new on the Server and
without disturbing the other callers.

**Steps:**

1. The operator runs
   `connector-node credential add --key-id replacement-caller`.
2. The operator copies the new credential to the CLI and confirms a request works.
3. The operator runs
   `connector-node credential remove --key-id leaked-caller`.
4. A request signed with the removed credential is refused.

**Acceptance:** The removed credential is refused on the next request, with no grace
period. The other credentials keep working, so retiring one caller does not retire
the rest. The `tunnel_token` and the client credentials are unchanged, so nothing on
the Server needs reconfiguring.

**Why this story matters:** add-then-remove is the only order that does not lock a
caller out between two commands. A rotation that removed first would leave a window
in which nobody could reach the Node.

## UC-5: The Server is compromised

**Actor:** An attacker with root on the Server.

**Story:** The Server host is lost. What does the attacker get?

**Steps:**

1. The attacker reads the Server's environment and finds `tunnel_token`, and reads
   the client credential file.
2. The attacker reads the Server's disk and memory and finds no node secret,
   because the Server never received one.
3. The attacker can open a channel as a Node and can call the API as a client.
4. The attacker still cannot read a file, because a node proof is required and the
   Server cannot produce one.

**Acceptance:** The attacker gains the ability to connect and to call, and does not
gain the ability to operate. Reading a file still requires a node secret the Server
never held.

**Why this story matters:** it is the concrete payoff of the "the Server never
receives the node secret" rule. Without it, a compromised Server yields every stored
credential at once.

## UC-6: A Node is offline

**Actor:** Operator whose home machine is asleep.

**Story:** The operator sends a request while the Node is not connected.

**Steps:**

1. The CLI signs both proofs and sends the request.
2. The Server verifies the client proof, then finds the `node-id` has no live
   channel.
3. The Server refuses with `node_offline`.

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
policy in force. No credential changes, because a scope is a policy decision and a
credential carries no permission.

## UC-8: A Windows machine serves a scope

**Actor:** Operator whose desktop runs Windows.

**Story:** The same story as UC-1, on Windows.

**Steps:**

1. The Node runs on Windows with a scope pointing at `C:\Users\me\project`.
2. The operator reads `notes.md`.
3. The operator tries `..\outside\secret.txt`.

**Acceptance:** The read succeeds and the traversal is refused, with the same error
code as on POSIX. The platform changes the set of rejected names, not the outcome.

## UC-9: An operator adds a second caller

**Actor:** Operator who wants a backup job to read the same scope as themselves,
without sharing their credential.

**Story:** Two callers need access. One credential shared between them would mean
retiring one retires both, and an audit record could not say which one acted.

**Steps:**

1. The operator runs
   `connector-node credential add --key-id backup-service`.
2. The Node prints the new credential once.
3. The operator gives it to the backup job.
4. Both callers read the same scope. A refusal names the `key_id` that was refused,
   so a caller whose credential was removed is identifiable in the log.

**Acceptance:** Both callers work, each with its own credential. Removing one leaves
the other working. Neither credential grants anything the policy does not grant, so
adding a caller does not widen access.

**Why this story matters:** it is the reason the credential is a `key_id.secret`
pair rather than one opaque string. A public `key_id` is what makes an audit record
name a caller without naming a secret.
