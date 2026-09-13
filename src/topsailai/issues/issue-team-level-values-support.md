---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: implemented
---

# Add Team-Level Shared Values Prompt Support

## Status

Implemented and verified.

The approved design adds `{TOPSAILAI_TEAM_PATH}/team.values` as a persistent, team-directory-scoped shared prompt automatically included for the Manager and every Member. It establishes a two-level `.values` model:

- `team.values` is shared by the Manager and all Members.
- `<member-id>.values` remains scoped to one Member.

`team.values` and `TOPSAILAI_TEAM_PROMPT` are complementary, cumulative prompt sources. Neither replaces, overrides, nor aliases the other.

## Requirement

Add `team.values` as plain, non-structured prompt text in the active team directory. Manager startup, plugin-dispatched Member startup, directly started Member Agent, and directly started Member Chat must all receive this shared content exactly once.

The feature is not a key-value configuration or override mechanism. The `.values` name follows the existing Member-file convention, but its behavior is ordered prompt inclusion.

Direct Member startup not currently receiving team-wide content is one acceptance path for this broader shared-prompt capability; it is no longer the complete issue definition.

## Prompt Source Model

| Source | Scope | Purpose |
|---|---|---|
| `TOPSAILAI_TEAM_PROMPT` | Current runtime or deployment | Team orchestration and workflow prompt, supplied as existing file-or-text configuration. |
| `{TOPSAILAI_TEAM_PATH}/team.values` | Team directory | Persistent business context, shared constraints, and collaboration preferences for the Manager and all Members. |
| `{TOPSAILAI_TEAM_PATH}/<member-id>.values` | One Member | Member-specific role additions and working constraints. |

The sources are appended in a fixed order; there is no structured merge or field precedence.

## Canonical Prompt Order

```text
base SYSTEM_PROMPT
-> TOPSAILAI_TEAM_PROMPT
-> team.values
-> generated team inventory
-> manager/member role prompt
-> <member-id>.values
-> extra prompts
```

Generated team inventory is a Manager capability. Direct Members must load `team.values` but do not need to repeat Manager discovery unless that is separately approved.

## Existing Manager and Plugin Evidence

`ai_team/manager.py:178-191` currently reads `TOPSAILAI_TEAM_PROMPT`, resolves it as file content or direct content, appends generated team information, and publishes the result through:

```python
os.environ["TOPSAILAI_TEAM_PROMPT_CONTENT"] = team_prompt_content
```

The external plugin consumes that runtime contract in `/work/ai_team/__plugins/ai-team-4-topsailai/ai_team_tool.py`:

- `call_agent` and `call_agents` prepend `TOPSAILAI_TEAM_PROMPT_CONTENT` to the selected Member prompt, write the combined prompt to a temporary system-prompt file, and pass it through `SYSTEM_PROMPT` and `TOPSAILAI_SYSTEM_PROMPT`.
- `call_chat` combines `TOPSAILAI_TEAM_PROMPT_CONTENT` with the selected Member prompt and passes it through `SYSTEM_PROMPT`.

The current propagation chain is:

```text
TOPSAILAI_TEAM_PROMPT
  -> manager.generate_system_prompt()
  -> TOPSAILAI_TEAM_PROMPT_CONTENT
  -> plugin call_agent / call_agents / call_chat
  -> SYSTEM_PROMPT
  -> member agent or member chat
```

The required extension is:

```text
TOPSAILAI_TEAM_PROMPT + team.values + generated team inventory
  -> manager.generate_system_prompt()
  -> TOPSAILAI_TEAM_PROMPT_CONTENT
  -> existing plugin dispatch
  -> member agent or member chat
```

`TOPSAILAI_TEAM_PROMPT_CONTENT` remains the core Manager-to-plugin runtime contract. The plugin should not need to resolve `team.values` itself.

## Existing Direct-Start Gap

A directly started Member does not pass through the Manager-to-plugin chain:

- `ai_team/member_agent.py:63-73` assembles a Member system prompt from `SYSTEM_PROMPT`, `get_member_prompt(agent_name)`, and extra prompt files. It does not load a team-level `.values` file.
- `cli/team_chat.py:99-104` calls `get_member_prompt(team_member_name)` directly when constructing its additional prompt. It does not load team-level shared content.
- `ai_team/role.py:93-127` loads only `{TOPSAILAI_TEAM_PATH}/<member-id>.values`; this supplies Member-specific content and cannot provide one shared layer to all directly started Members.

Consequently, the direct Agent and Chat paths require a common prompt composer that includes `team.values`, while preserving Member-specific isolation.

## Proposed Design Boundary

Add a focused shared prompt module, preferably `ai_team/prompt.py`, responsible for:

- resolving the existing file-or-text `TOPSAILAI_TEAM_PROMPT` contract;
- loading optional `{TOPSAILAI_TEAM_PATH}/team.values`;
- composing team prompt segments in canonical order;
- supporting Manager, Member Agent, and Member Chat without duplicated parsing;
- distinguishing an already precomposed plugin prompt from a direct-start prompt;
- preventing duplicate team-level content.

Keep `ai_team/role.py` and `get_member_prompt()` responsible for role identity and `<member-id>.values`. Loading `team.values` inside `get_member_prompt()` would mix scopes and could duplicate shared content after plugin dispatch.

## Candidate Changes

| File | Intended change |
|---|---|
| `ai_team/prompt.py` | New canonical resolver/composer for runtime team prompt and `team.values`. |
| `ai_team/manager.py` | Include `team.values` in the Manager prompt and `TOPSAILAI_TEAM_PROMPT_CONTENT`. |
| `ai_team/member_agent.py` | Include `team.values` for direct Members and avoid re-adding plugin-precomposed content. |
| `cli/team_chat.py` | Use the same Member composition contract as `team_agent`. |
| `cli/team_agent.py` | Preserve delegation to the common composer; change only if explicit inputs are required. |
| `ai_team/role.py` | Preserve Member-only scope; optional neutral helper extraction only. |
| `/work/ai_team` plugin | No change expected; continue consuming `TOPSAILAI_TEAM_PROMPT_CONTENT`. |

Implementation, test, template, and documentation changes are separate follow-up work and require their applicable workspace permissions.

## Risks

### Ambiguous Source Responsibilities

`TOPSAILAI_TEAM_PROMPT` and `team.values` must not both be described generically as interchangeable team prompts. The former is runtime/deployment orchestration input; the latter is persistent team-directory shared context.

### Duplicate Injection

The Manager will include `team.values` in `TOPSAILAI_TEAM_PROMPT_CONTENT`; the plugin will then place that content in `SYSTEM_PROMPT`. If the Member process independently reloads `team.values`, the same prompt will appear twice.

A centralized composer needs an explicit already-composed signal or provenance-aware API. Distributed substring checks are not a reliable contract.

### Non-Structured File Semantics

`team.values` is plain text. It does not support key parsing, key collision handling, field override, or inheritance semantics beyond ordered prompt inclusion.

### Scope Leakage

The Manager and all Members receive `team.values`. Only the selected Member receives `<member-id>.values`; the Manager must not load arbitrary Member-specific values.

### Ordering and Authority

Natural-language instructions can conflict. The canonical order must remain stable, and application system/security constraints must remain authoritative over team and Member additions.

### Compatibility

A missing or empty `team.values` must preserve current behavior. The implementation must define and consistently test the policy for an existing but unreadable file.

## Acceptance Criteria

- `{TOPSAILAI_TEAM_PATH}/team.values` is automatically included for the Manager and every Member.
- `TOPSAILAI_TEAM_PROMPT` and `team.values` are cumulative and appear in canonical order.
- The Manager publishes `team.values` through the existing `TOPSAILAI_TEAM_PROMPT_CONTENT` contract.
- A plugin-launched Member and a directly launched Member receive the same unique `team.values` marker.
- `team_agent` and `team_chat` use the same team-level composition semantics.
- Two Members receive the shared team marker but only their own `<member-id>.values` marker.
- Team-level and Member-specific markers each appear exactly once.
- The Manager receives `team.values` but does not receive arbitrary Member-specific values.
- Missing or empty `team.values` preserves legacy behavior.
- Standard Manager-plus-plugin behavior remains unchanged except for the intentional shared prompt addition.
- `call_agent`, `call_agents`, and `call_chat` continue to consume `TOPSAILAI_TEAM_PROMPT_CONTENT` without independently loading the shared file.
- `.values` content remains non-structured prompt text with no override guarantee.
- Unit, integration, and LLM-backed BDD tests cover Manager, direct Agent, direct Chat, and plugin-precomposed paths.

## Implemented Decisions

- Precomposed prompts are identified by an explicit composer argument, with a defensive fallback that requires structured plugin launch provenance.
- An existing but unreadable `team.values` fails closed before provider I/O.
- The `/work/ai_team` plugin required no modification and passed a real subprocess-chain verification.
- Direct Members load `team.values` without independently generating Manager team inventory.

## Related

- `.task/plan_20260913T075700_direct-member-team-prompt.md` — accepted design and test plan
- `ai_team/manager.py:178-191` — produces `TOPSAILAI_TEAM_PROMPT_CONTENT`
- `ai_team/member_agent.py:63-73` — directly assembles a Member system prompt
- `cli/team_chat.py:99-104` — directly assembles a Member chat prompt
- `ai_team/role.py:93-127` — loads Member-specific `<member-id>.values`
- `/work/ai_team/__plugins/ai-team-4-topsailai/ai_team_tool.py` — consumes Manager-produced content for plugin-launched Members
