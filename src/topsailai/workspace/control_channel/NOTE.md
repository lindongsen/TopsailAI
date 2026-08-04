# control_channel Design Constraints

`workspace/control_channel/` is the runtime control bus of TopsailAI, existing as an independent infrastructure module.

## Scope of Responsibility

This module is only responsible for:

- Protocol framing and parsing (JSONL over stream)
- Transport layer implementation (Unix Domain Socket)
- Request dispatching and response return
- Handler registry mechanism (`ControlHandlerRegistry`)
- Connection management and server lifecycle

## Prohibited Content

This module **must not** contain any business logic, including but not limited to:

- Direct interaction with the agent runtime
- Read or write operations on LLM, session, or context
- Concrete `/` instruction or hook logic
- Any code that depends on runtime objects such as `thread_local_tool`, `agent.messages`, or `ctx_runtime_data`

## Where Business Logic Belongs

Business handlers should be placed in independent business modules, for example:

- `workspace/control_handlers/` — control-channel business handlers
- `workspace/plugin_instruction/` — interactive `/` instructions
- Other business modules

Business handlers register themselves with the control bus via `ControlHandlerRegistry.register(action, handler)`, decoupling infrastructure from business logic.

## Design Principles

- Generic: make no assumptions about whether the caller is an agent, LLM, or other runtime
- Replaceable: transport, protocol, and registry mechanisms can be extended independently
- Testable: the infrastructure layer does not depend on concrete business state, making unit testing straightforward
