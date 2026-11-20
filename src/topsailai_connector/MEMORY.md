---
maintainer: human
author: DawsonLin
---

# Rules the human required

## Naming

- The project is named `topsailai_connector`. The previous name
  `topsailai_proxy` was rejected because `proxy` implies transparent traffic
  forwarding and does not express the permission boundary, which is the core
  value of this system.
- The two components are `server` (cloud) and `node` (personal computer).
  `agent` is unavailable because `topsailai_agent` already exists, and
  `endpoint` is unavailable because `topsailai_agent_cluster` already uses it.
- `scope` names an area such as `project` or `tool`. `permission` names a
  read/write style action. The two words must not be swapped or merged.

## Language and layout

- The implementation language is Go.
- The layout follows the Go convention: `cmd/` for entry points, `internal/`
  for implementation, `internal/protocol` and `internal/security` shared by both
  sides.

## Token model

The human replaced the earlier signed-token design with three shared secrets. The
words used are `tunnel_token`, `client_token` and `node-token`, and those names are
binding.

- The Server is configured with two secrets through environment variables:
  `tunnel_token` gates a Node connecting, `client_token` gates a CLI calling.
- The Node generates its own identity as one dot-separated string,
  `node-id.node-token`, and may regenerate it on its own initiative.
- The CLI carries `client_token` and the whole `node-id.node-token` pair. The
  Server checks what it owns and forwards the `node-token` to the Node. The Node
  checks the `node-token` and decides whether the operation happens.
- No secret carries a permission. The policy file is the only place a permission
  is granted.

## Hard principle: the Server never stores a Node token

The human stated this principle explicitly and called it important:

> 这个原则很重要，server永远不存node的token。

The Server forwards the `node-token` on the request it arrives with and keeps no
copy. This covers persistence, logging, retention after forwarding, and any derived
value such as a hash, prefix or fingerprint.

Reason: if the Server stores a `node-token`, compromising the Server yields every
stored credential at once and the separation between the channel authority and the
operation authority collapses into one authority.

The same rule covers the Server's own two secrets: they are compared and dropped,
never logged, never written to a config file, never echoed by a configuration dump.

## Hard principle: the Node controls all permissions

The human stated this principle explicitly:

> 所有的权限都是 node 自己控制的，控制访问范围（scopes）,控制具体的读写/执行权限（permissions）。

- The Node is the only authority for permissions. It controls both dimensions: the
  access scope (`scope`) and the concrete action allowed there (`permission`).
- The Server holds no scope list and no permission list. It cannot add a scope,
  widen a grant, translate one permission into another, or mark a request as
  pre-approved.
- The CLI is not an authority. It asks for a scope and an operation, and that is a
  request, not a grant.
- A policy change and a new scope are Node-local acts. Nothing on the Server
  changes, so access cannot be widened by editing Server configuration.
- No secret carries a permission. A secret proves who may talk; the Node's policy
  file alone says what may be done.

## Agreed defaults

- No secret expires. Rotation is the only revocation mechanism, and it is a
  coordinated change with no grace period.
- The first version is read-only: `file.list`, `file.stat`, `file.read`.
  `file.write` is second, `command.exec` is third and only if a real need appears.

## Configuration precedence

The human approved the order on 2026-11-20:

> 关于那个配置优先级，我觉得可以记

- One value may come from four sources, and the order is fixed: `--set` beats an
  environment variable, which beats `--env-file`, which beats a value compiled
  into the binary.
- An empty value counts as unset at every layer, so an exported but empty variable
  does not shadow a file that holds a value.
- A value that none of the four supplies is generated in memory when it can be
  (the node id and a credential), and is a startup failure when it cannot (the
  Server address, the `tunnel_token` and the policy).
- The policy is the one value a file may not override when the build compiled one
  in: two complete policies would disagree about every scope and every grant, so
  the second source is refused rather than merged.

## Platform and client access

The human stated these requirements explicitly:

> 此外，windows要支持，cli如何连入server去操作node呢？ cli要带上 server和node的token去访问server，server会转发给node。当然 cli还得带上node_id，node连接server后，node会将全球唯一id上报给server。

> 我们再细化方案，再写各种用例，包括对抗用例。我认为，node启动后会自己生成一个字符串，用点号分隔，node-id.node-token，允许node主动重新生成。server启动时可以配置环境变量去设置node连入的token就叫tunnel_token，cli连入的token就叫client_token。cli 带着 client_token 和 node-id.node-token 去访问server，server识别和检查并转发给node，node识别和检查来决定是否可访问。

- Windows is a supported platform in the first version, not a later port. The
  path fence is the standard library `os.Root`, which enforces the boundary on
  Windows as well as on POSIX, so the platform cost is a set of path rules rather
  than a second fence implementation.
- The CLI reaches a Node through the Server over HTTP. It carries `client_token`
  and the `node-id.node-token` pair. The Server validates `client_token` and
  forwards the `node-token` unchanged.
- The CLI also carries the `node-id`. The Node reports a globally unique
  identifier to the Server when it connects.
- The identifier is generated by the Node at first start and persisted locally, so
  a Node must be started once before anyone can address it. The Server never mints,
  assigns or overrides a `node-id`, and there is no lookup endpoint.
- The Node may regenerate the pair at any time. Regeneration invalidates the old
  `node-token` immediately and drops the live channel.
- The human asked for test cases to be written, including adversarial cases. They
  live in `docs/cases/`.

## Skill documentation is written for someone who cannot see the code

The human stated this requirement explicitly:

> skill的更新这件事，你要顺便写到项目记忆里，要注意：使用skill的人是完全看不到代码的，要站在使用者的角度去写。

- A skill is read by a person who has only the binary. They cannot read the Go
  source, cannot see a struct field, cannot follow a call chain, and cannot check
  what a function does. Anything a skill says must be verifiable from the command
  line alone.
- Write from the user's side of the boundary: what to type, what appears on the
  screen, what the exit status is, and what to do next. Never explain a behaviour
  by naming an internal function, a struct field, a package or a file.
- Describe the observable result, not the mechanism. "One line per entry: name,
  type, size" is usable; "the `Entry` struct serialises `Name`, `Type`, `Size`" is
  not, because the reader has no way to act on it.
- Quote the message the program actually prints, and state the exit status that
  accompanies it. A paraphrase sends the reader searching a log for text that does
  not exist, and a missing status leaves a script unable to branch.
- Every command shown must be one the binary accepts, in the order it accepts it.
  A documented command is a claim, so it is executed before it is published and
  again after the interface it names changes.
- When a feature is added or changed, the skill is part of the change, not a
  follow-up. A feature the user cannot discover from the skill is a feature that
  does not exist for them, because the skill is the only documentation they read.
- State a limit where the user meets it. A cap, a refusal or a required flag
  belongs next to the command that hits it, not in a design document the reader
  will never open.

## 无状态模式 is the binding name for the mode that writes nothing

The human named the mode and the name is binding for code, help, documents and
conversation:

> 我把这种纯内存运行，不创建任何文件的运行模式称之为 无状态模式，以后称呼或提起
> 就能建立联系。

- 无状态模式 / stateless mode means the Node runs entirely in memory: it creates
  no directory, writes no identity file and writes no credential file. The node id
  and the credentials live in the process and are lost when it exits.
- The switch is `CONNECTOR_NODE_STATELESS=1`. The value is validated strictly:
  `1` enables it, an empty value or `0` disables it, and anything else is refused
  rather than read as "off".
- The mode exists for a machine whose filesystem is read-only. A config directory
  that cannot be created must not stop the Node, which is the whole point.
- The policy is the one value that cannot be generated. A Node that invented its
  own scopes would be a Node whose operator believes it serves something it does
  not, so a stateless Node requires a compiled-in policy or
  `CONNECTOR_NODE_POLICY_FILE`.
- The interactive console is the only way to change the address or revoke a caller
  in this mode, because `id`, `regenerate` and the `credential` subcommands write
  files and are therefore refused. The console changes the same state in memory.
- The mode is additive. The file-backed mode stays the default and its behaviour
  does not change.

## Incremental development is a standing requirement

The human stated this as a rule for every request, not for one task:

> 我提的需求都是增量式开发，不要去删掉以前支持的功能。

- A new capability is added beside the existing one, never in place of it.
- No existing subcommand, flag, environment variable, help entry, skill section,
  test or documented behaviour may be removed to make room for a new one.
- When a new mode changes what an existing command means, the command refuses in
  the new mode with a message naming the alternative, rather than silently
  acquiring a second meaning.
