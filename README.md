# Project Information

## Project: `src/topsailai`

AI-Agent Core, Agent Workers.

## project: `src/topsailai_server/agent_daemon`

User Session Layer, It can be used to schedule agent workers.

---

## Core Vision / Goal

We believe the future agent kernel will evolve to resemble the modern Linux
kernel:

- **Rich, well-defined parameters** — many tunable knobs whose semantics,
  scope, defaults, and effects are precisely documented and auditable.
- **Clear boundary between determinism and uncertainty** — deterministic parts
  (scheduling, concurrency, quotas, retries, permission checks, logging) stay
  explicit and controllable; nondeterministic parts (LLM inference, free-form
  generation, open-ended planning) are exposed as first-class interfaces rather
  than hidden black boxes.
- **Flexible dynamic module / plugin mechanism** — hot-pluggable, versioned
  components with dependency resolution and lifecycle hooks (load/unload/reload),
  loadable on demand without restarting the kernel.
- **First-class event mechanism** — a unified event channel for inter-member
  communication, task-state transitions, tool-call results, approval requests,
  errors, and recovery, instead of scattered callbacks or polling.

Just as the Linux kernel succeeds through stable ABIs and backward-compatible
contracts, the agent kernel must define stable external interfaces, upgrade
guarantees, and clear security/permission boundaries.

**Slogan: 在不确定性中定义确定性** *(Defining certainty amid uncertainty)*
