Feature: ask_decision keeps its string-first parameter contract
  ``human_tool.ask_decision`` is this project's reference implementation of the rule
  "tool parameters must assume string-typed LLM output": it decodes a JSON-array
  string into options, always accepts free-text answers, and requires finite integer
  seconds for the wait budget. The removed ``allow_free_text`` argument is not accepted;
  callers must use the always-enabled free-text behavior.

  Every call runs in a non-interactive process with no input channel, inside a worker
  thread with a hard ceiling, so no scenario can block waiting for a human.

  # --------------------------------------------------------------- options

  Scenario Outline: ask_decision accepts options that arrive as a JSON array
    When the human decision tool is asked with parameter options set to <options>
    Then the human decision answer is unavailable without rendering any prompt
    And the human decision answer carries no raw exception text

    Examples: option spellings an LLM really sends
      | options                |
      | ["yes","no"]           |
      | ["approve","deny"]     |
      | raw:["yes","no"]       |

  Scenario Outline: ask_decision rejects options that are not a JSON array of strings
    When the human decision tool is asked with parameter options set to <options>
    Then the human decision answer is a parameter error naming options
    And the human decision answer carries no raw exception text

    Examples: text that is not an option list
      | options          |
      | {"a":1}          |
      | "just"           |
      | 3                |
      | [bad             |
      | [1,2]            |
      | ["a",2]          |

  Scenario Outline: ask_decision treats absent options as no options at all
    An absent option list is not a bad argument, so the request stays well-formed and
    simply has nothing to offer the operator.

    When the human decision tool is asked with parameter options set to <options>
    Then the human decision answer is unavailable without rendering any prompt
    And the human decision answer carries no raw exception text

    Examples: unset spellings
      | options |
      | empty   |
      | null    |

  # --------------------------------------------- removed allow_free_text

  Scenario Outline: ask_decision rejects every removed free-text flag spelling
    The removed argument is not part of the tool contract and is not retained as a
    backward-compatibility keyword.

    When the human decision tool is asked with parameter allow_free_text set to <flag>
    Then the human decision call raises TypeError naming allow_free_text

    Examples: removed legacy values
      | flag           |
      | 1              |
      | 0              |
      | int:0          |
      | yes            |
      | true           |
      | 2              |
      | empty          |
      | null           |
      | raw:[1]        |
      | raw:{"old":1}  |

  # ------------------------------------------------------- timeout_seconds

  Scenario Outline: ask_decision converts a wait budget that arrives as text
    When the human decision tool is asked with parameter timeout_seconds set to <timeout>
    Then the human decision answer is unavailable without rendering any prompt
    And the human decision answer reports no timeout
    And the human decision answer carries no raw exception text

    Examples: integer text and native integer-valued numbers
      | timeout    |
      | 30         |
      | <sp>30<sp> |
      | 5.0        |
      | 1e2        |
      | int:30     |
      | float:5.0  |

  Scenario Outline: ask_decision keeps a non-positive wait budget as wait indefinitely
    Zero and negative budgets are existing business semantics, not bad arguments.

    When the human decision tool is asked with parameter timeout_seconds set to <timeout>
    Then the human decision answer is unavailable without rendering any prompt
    And the human decision answer reports no timeout

    Examples: non-positive budgets
      | timeout |
      | 0       |
      | -5      |
      | int:0   |

  Scenario Outline: ask_decision rejects a wait budget that is not finite integer seconds
    Fractions must not be truncated to zero because zero means an indefinite wait; NaN and
    both infinities also convert in Python but must never reach the wait call.

    When the human decision tool is asked with parameter timeout_seconds set to <timeout>
    Then the human decision answer is a parameter error naming timeout_seconds
    And the human decision answer carries no raw exception text

    Examples: unusable budget text
      | timeout |
      | 0.5     |
      | abc     |
      | NaN     |
      | inf     |
      | -inf    |
      | empty   |
      | raw:[1] |

  Scenario Outline: ask_decision treats an absent wait budget as unset
    When the human decision tool is asked with parameter timeout_seconds set to <timeout>
    Then the human decision answer is unavailable without rendering any prompt
    And the human decision answer reports no timeout

    Examples: unset spellings fall back to the environment default
      | timeout |
      | null    |

  # ------------------------------------------------------- question/default

  Scenario Outline: ask_decision rejects a question it cannot render
    When the human decision tool is asked with parameter question set to <question>
    Then the human decision answer is a parameter error naming question
    And the human decision answer carries no raw exception text

    Examples: a question must be non-empty text
      | question     |
      | empty        |
      | <sp><sp><sp> |
      | null         |
      | int:5        |
      | raw:["a"]    |

  Scenario Outline: ask_decision rejects a fallback it cannot return as text
    When the human decision tool is asked with parameters question set to Should the scenario continue? and default set to <default>
    Then the human decision answer is a parameter error naming default
    And the human decision answer carries no raw exception text

    Examples: a fallback must be text
      | default        |
      | int:5          |
      | raw:["a"]      |
      | raw:{"a":1}    |

  Scenario: ask_decision hands the caller's fallback back when nobody answers
    When the human decision tool is asked with parameters question set to Should the scenario continue? and default set to fallback
    Then the human decision answer is the status unavailable
    And the human decision answer keeps the default fallback
    And the human decision answer carries no raw exception text

  # ------------------------------------------------- operator is reachable

  Scenario Outline: ask_decision maps a scripted reply onto the offered options
    When the human decision tool is asked with a scripted answer <answer> and parameter options set to ["yes","no"]
    Then the human decision answer is answered from the scripted reply
    And the human decision answer equals <expected>
    And the human decision answer selected option index <index>

    Examples: option text and option number both resolve
      | answer | expected | index |
      | yes    | yes      | 0     |
      | 0      | yes      | 0     |
      | 1      | no       | 1     |
      | no     | no       | 1     |

  Scenario: ask_decision records a cancellation and keeps the fallback
    When the human decision tool is asked with a scripted answer /cancel and parameters options set to ["yes","no"] and default set to fallback
    Then the human decision answer is the status cancelled
    And the human decision answer keeps the default fallback

  Scenario: ask_decision always accepts free text alongside options
    When the human decision tool is asked with a scripted answer anything goes and parameter options set to ["yes","no"]
    Then the human decision answer is answered from the scripted reply
    And the human decision answer equals anything goes
    And the human decision answer selected option index -1

  Scenario: ask_decision accepts a plain reply when no options were offered
    When the human decision tool is asked with a scripted answer hello there and parameter options set to empty
    Then the human decision answer is answered from the scripted reply
    And the human decision answer equals hello there

  Scenario: ask_decision falls back when the operator replies with nothing
    When the human decision tool is asked with a scripted answer empty and parameters options set to ["yes","no"] and default set to fallback
    Then the human decision answer is answered from the scripted reply
    And the human decision answer equals fallback

  Scenario: ask_decision accepts an unlisted reply
    Free-text input is always enabled, so the human's own answer remains authoritative.

    When the human decision tool is asked with a scripted answer zzz and parameter options set to ["yes","no"]
    Then the human decision answer is answered from the scripted reply
    And the human decision answer equals zzz
    And the human decision answer selected option index -1
    And the human decision answer carries no raw exception text
