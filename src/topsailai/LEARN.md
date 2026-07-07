# Learn

## When user provides negative or corrective feedback, treat it as high-signal design constraints rather than just a code-location fix

In the auto session_name task, the user first rejected placing logic in session_manager/sql.py, then had to explicitly specify get_llm_chat(session_id="", need_stdout=False).

Lessons:
(1) proactively ask where business logic belongs when user rejects a layer;
(2) for LLM side effects that should not pollute session history or stdout, default to session_id="" and need_stdout=False without being told;
(3) negative feedback often reveals unstated architectural rules—extract and confirm them immediately.


## Capture the latency start timestamp before the operation whose overhead must be measured

When measuring first-byte latency for streaming LLM responses, the start timestamp must be captured **before** the request-creation call (`_create_with_first_byte_timeout()`), not after it. Capturing it after the request is created excludes the request-setup overhead and under-reports the true first-byte latency.

Lessons:
(1) define the measurement boundary explicitly: "first byte" should include everything from the caller's decision to start the request up to the first useful response chunk;
(2) place the start timestamp at the earliest point inside that boundary, immediately before any work that contributes to the latency;
(3) when a user reports a metric "looks wrong", verify the placement of the start and end timestamps before questioning the unit conversion or aggregation logic.
