# Topsail AI

**Slogan: 在不確定中定義確定性** *(Defining certainty amid uncertainty)*

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

---

## Projects under `src/`

### Project: `src/topsailai`

AI-Agent Core, Agent Workers.

An interactive AI-agent runtime providing a command-line interface to watch
sessions, send messages, launch agents, and manage workspace tasks, together
with a layered engine that drives ReAct-style agent execution.

### Project: `src/topsailai_data`

Local-first object store CLI (Go).

A data management system that unifies access to heterogeneous storage backends
through pluggable adapters. It separates **metadata** (identity, path,
description, time, status, tags) from **actual data** (plain text or arbitrary
files carried primarily by a mandatory `object.md`). The current implementation
focuses on the **local adapter**.

### Project: `src/topsailai_server/agent_daemon`

User Session Layer, It can be used to schedule agent workers.

A Python RESTful daemon exposing endpoints for managing sessions, messages,
tasks, and API keys, with optional API-key authentication, role-based permission
control, and QoS rate limiting.

### Project: `src/topsailai_server/agent_community`

AI-Agent Community Server (ACS, Go).

A stateless distributed service that enables humans and AI agents to collaborate
in groups (communities). Groups serve as sessions where members chat together,
with agent triggering and coordination managed by designated manager-agents over
HTTP (Gin), NATS/JetStream messaging, and PostgreSQL (GORM).

---
