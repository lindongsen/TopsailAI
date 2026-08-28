Feature: str-only tools stay predictable when an argument arrives badly typed
  These tools declare plain string parameters, so no coercion is expected. They still
  need a guard suite because ``exec_tool_func`` stringifies an uncaught exception into
  the tool result, which means a raw interpreter message is handed straight back to the
  model as an observation.

  The formal scenarios pin both established business behaviour and the defensive
  parameter contract: native strings remain untouched, while badly typed arguments are
  answered with a machine-readable parameter error rather than a raised exception.

  Nothing here reaches a real LLM, a real sub-agent, the real memory workspace or the
  network; every external layer is mocked inside the harness.

  # ------------------------------------------------------- already-correct behaviour

  Scenario Outline: retrieve_msg answers an empty string for a text identifier it cannot find
    When the guard tool retrieve_msg is called with parameter msg_id set to <msg_id>
    Then the guard tool answer is an empty string
    And the guard tool answer does not report an unavailable environment

    Examples: any text spelling of an unknown identifier
      | msg_id     |
      | msg-xyz    |
      | {"a":1}    |

  Scenario Outline: retrieve_msg rejects an identifier that is not text
    When the guard tool retrieve_msg is called with parameter msg_id set to <msg_id>
    Then the guard tool answer is a machine-readable parameter error
    And the guard tool answer does not report an unavailable environment

    Examples: identifiers that arrive with the wrong type
      | msg_id     |
      | int:123    |
      | null       |
      | raw:["a"]  |

  Scenario: get_local_date answers a formatted date without any argument
    When the guard tool get_local_date is called without any argument
    Then the guard tool answer matches the ISO-8601 date pattern
    And the guard tool answer does not report an unavailable environment

  Scenario: get_local_time answers a numeric timestamp without any argument
    When the guard tool get_local_time is called without any argument
    Then the guard tool answer is an integer
    And the guard tool answer does not report an unavailable environment

  Scenario: get_file_size reports the size of an existing file
    Given a guard file named sample.bin holding 5 bytes
    When the guard tool get_file_size is called with parameter file_path set to {file}
    Then the guard tool answer is the integer 5

  Scenario: recognize_image answers from its mocked model layer
    Given a guard file named pic.png holding 8 bytes
    When the guard tool recognize_image is called with parameters image_source set to {file} and prompt set to describe
    Then the guard tool answer is the mocked multimodal description
    And the guard tool answer does not report an unavailable environment

  Scenario: call_assistant answers from its mocked sub-agent
    When the guard tool call_assistant is called with parameter task set to say hi
    Then the guard tool answer is the mocked sub-agent answer

  # ------------------------------------------------------- memory record lifecycle

  Scenario: a written memory can be read back and listed
    Given a memory titled guard memory holding the content hello memory
    When the guard tool read_memory is called with parameter title set to guard_memory
    Then the guard tool answer is the string hello memory
    When the guard tool list_memories is called without any argument
    Then the guard tool answer is a non-empty list
    And the guard tool answer lists a record titled guard_memory

  Scenario: a deleted memory is really gone
    Given a memory titled guard memory holding the content hello memory
    When the guard tool delete_memory is called with parameter title set to guard_memory
    Then the memory titled guard_memory no longer exists

  Scenario: listing memories on an empty workspace answers an empty list
    Given a guard workspace folder
    When the guard tool list_memories is called without any argument
    Then the guard tool answer is an empty list

  # ------------------------------------------------------- story record lifecycle

  Scenario: a written story can be read back, listed and retrieved
    Given a guard workspace folder
    When the guard tool write_story is called with parameters story_id set to guard-story and story_content set to story body
    Then the guard tool answer is a path holding guard-story
    When the guard tool read_story is called with parameter story_id set to guard-story
    Then the guard tool answer is the string story body
    When the guard tool list_stories is called without any argument
    Then the guard tool answer is a non-empty list
    And the guard tool answer lists a record titled guard-story

  Scenario: retrieving stories by keyword answers records or None
    Given a guard workspace folder
    When the guard tool write_story is called with parameters story_id set to guard-story and story_content set to story body
    And the guard tool retrieve_stories searches for the keywords guard
    Then the guard tool answer is a non-empty list
    And the guard tool answer lists a record titled guard-story
    When the guard tool retrieve_stories searches for the keywords nomatch
    Then the guard tool answer is None

  Scenario: a deleted story leaves no record behind
    Given a guard workspace folder
    When the guard tool write_story is called with parameters story_id set to guard-story and story_content set to story body
    And the guard tool delete_story is called with parameter story_id set to guard-story
    Then the guard workspace holds no story record

  Scenario: listing stories on an empty workspace answers an empty list
    Given a guard workspace folder
    When the guard tool list_stories is called without any argument
    Then the guard tool answer is an empty list

  # ------------------------------------------------------- pinned contract defects

  Scenario Outline: a str-only tool must answer instead of raising on a badly typed argument
    A raw Python exception stringified into the tool result teaches the model nothing it
    can act on, so the argument must be validated and rejected as a parameter error.

    When the guard tool <tool> is called with parameter <param> set to <value>
    Then the guard tool answer is free of raw Python exception text
    And the guard tool answer does not report an unavailable environment

    Examples: file size argument types
      | tool          | param      | value       |
      | get_file_size | file_path  | null        |
      | get_file_size | file_path  | raw:["a"]   |
      | get_file_size | file_path  | int:987654  |

    Examples: memory argument types
      | tool          | param   | value       |
      | write_memory  | title   | int:5       |
      | write_memory  | title   | raw:["a"]   |
      | read_memory   | title   | int:5       |

    Examples: story argument types
      | tool         | param    | value       |
      | write_story  | story_id | int:5       |

    Examples: multimodal and sub-agent argument types
      | tool            | param        | value       |
      | recognize_image | image_source | int:5       |
      | recognize_image | image_source | null        |
      | recognize_image | image_source | raw:["a"]   |
      | call_assistant  | task         | null        |

  Scenario Outline: a str-only tool must reject a badly typed second argument too
    When the guard tool <tool> is called with parameters <first_param> set to <first_value> and <second_param> set to <second_value>
    Then the guard tool answer is free of raw Python exception text
    And the guard tool answer does not report an unavailable environment

    Examples: the second argument carries the bad type
      | tool         | first_param | first_value  | second_param | second_value |
      | write_memory | title       | guard memory | content      | int:5        |
      | write_story  | story_id    | guard-story  | story_content | int:5       |
      | call_assistant | task      | say hi       | role         | raw:["a"]    |

  Scenario Outline: keyword retrieval must answer instead of raising on non-text keywords
    When the guard tool retrieve_stories searches for the keywords <keywords>
    Then the guard tool answer is free of raw Python exception text
    And the guard tool answer does not report an unavailable environment

    Examples: keywords that arrive as something other than text
      | keywords  |
      | int:5     |
      | null      |
      | raw:["a"] |

  Scenario Outline: a JSON object string remains an ordinary string parameter
    Content that looks like JSON is still text when its native type is ``str``. The guard
    must preserve it for backward compatibility rather than parsing it as a container.

    When the guard tool <tool> is called with parameter <param> set to {"a":1}
    Then the guard tool answer does not reject the native string as a parameter error
    And the guard tool answer does not report an unavailable environment

    Examples: string parameters fed JSON-looking text
      | tool          | param     |
      | write_memory  | title     |
      | get_file_size | file_path |

  Scenario: get_file_size must not treat an integer as a file descriptor
    An integer argument is the classic LLM type slip; silently interpreting it as an open
    descriptor number is worse than rejecting it, because it can read an unrelated file.

    Given a guard file named sample.bin holding 5 bytes
    When the guard tool get_file_size is called with parameter file_path set to int:987654
    Then the guard tool answer is a machine-readable parameter error
    And the guard tool answer does not report an unavailable environment

  Scenario: delete_memory must answer instead of raising once a record exists
    The member test over stored titles is only reached when the workspace is not empty, so
    an empty-workspace call can pass for the wrong reason. With one record present a list
    title raises ``TypeError: 'in <string>' requires string as left operand``.

    Given a memory titled guard memory holding the content hello memory
    When the guard tool delete_memory is called with parameter title set to raw:["a"]
    Then the guard tool answer is free of raw Python exception text
    And the guard tool answer does not report an unavailable environment

  Scenario Outline: story tools must answer instead of raising once a record exists
    Reading or deleting by a badly typed identifier only touches the stored text when a
    story already exists; the empty case hides the defect.

    Given a guard workspace folder
    And the guard tool write_story is called with parameters story_id set to guard-story and story_content set to story body
    When the guard tool <tool> is called with parameter <param> set to <value>
    Then the guard tool answer is free of raw Python exception text
    And the guard tool answer does not report an unavailable environment

    Examples: identifiers that arrive as something other than text
      | tool         | param    | value       |
      | read_story   | story_id | int:5       |
      | delete_story | story_id | raw:["a"]   |
