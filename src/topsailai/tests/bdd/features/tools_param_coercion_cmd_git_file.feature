Feature: Tools accept string-typed parameters from the LLM
  An LLM serializes every argument as text, so a parameter declared as a number,
  a boolean flag or a container usually arrives as a string. The tools must still
  do their job, and when the text cannot be understood they must answer with a
  machine-readable parameter error instead of a crash or an unrelated business
  status.

  Background:
    Given a parameter test file named sample.txt containing lines LINE01 to LINE20

  # ---------------------------------------------------------------- exec_cmd
  Scenario Outline: exec_cmd understands a timeout that arrives as text
    When the tool exec_cmd is called with command echo hi and parameter timeout set to <timeout>
    Then the command succeeds and prints hi

    Examples: timeout values an LLM really sends
      | timeout   |
      | 120       |
      | 30        |
      | <sp>1e2<sp> |
      | 1.5       |
      | int:45    |
      | float:20  |

  Scenario Outline: exec_cmd rejects a timeout that is not a finite number
    When the tool exec_cmd is called with command echo hi and parameter timeout set to <timeout>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the timeout parameter

    Examples: unusable timeout text
      | timeout |
      | abc     |
      | NaN     |
      | inf     |
      | -inf    |
      | empty   |
      | null    |

  Scenario Outline: exec_cmd reads the stderr switch as an integer flag
    When the tool exec_cmd is called with command echo hi and parameter no_need_stderr set to <flag>
    Then the command succeeds and prints hi

    Examples: integer flag spellings
      | flag |
      | 1    |
      | 0    |
      | <sp>1<sp> |
      | int:1 |
      | int:0 |

  Scenario Outline: exec_cmd refuses a stderr switch written as prose
    When the tool exec_cmd is called with command echo hi and parameter no_need_stderr set to <flag>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the no_need_stderr parameter

    Examples: rejected flag values
      | flag  |
      | 2     |
      | -1    |
      | yes   |
      | true  |
      | empty |
      | null  |

  Scenario: exec_cmd applies an environment written as a JSON object
    When the tool exec_cmd is called with command echo $TP_BDD_PARAM_VAR and parameter env set to {"TP_BDD_PARAM_VAR":"ok42"}
    Then the command succeeds and prints ok42

  Scenario Outline: exec_cmd rejects an environment that is not a JSON object
    When the tool exec_cmd is called with command echo hi and parameter env set to <env>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the env parameter

    Examples: malformed environment
      | env       |
      | {bad      |
      | ["ONLY"]  |
      | empty     |

  Scenario: exec_cmd accepts a command already serialized as a JSON list
    When the tool exec_cmd is called with plain command ["echo","hello"]
    Then the command succeeds and prints hello

  Scenario: exec_cmd accepts a command given as a native list
    When the tool exec_cmd is called with plain command raw:["echo","hello"]
    Then the command succeeds and prints hello

  Scenario: exec_cmd rejects a truncated JSON list command
    When the tool exec_cmd is called with plain command ["echo"
    Then the tool returns a machine-readable parameter error
    And the parameter error names the cmd parameter

  # ---------------------------------------------------------- exec_readonly
  Scenario Outline: exec_readonly understands a timeout that arrives as text
    When the tool exec_readonly is called with command git rev-parse --is-inside-work-tree and parameter timeout set to <timeout>
    Then the command succeeds and prints true

    Examples: coercible timeouts
      | timeout     |
      | 30          |
      | <sp>15<sp>  |
      | 1e1         |
      | int:20      |

  Scenario Outline: exec_readonly rejects a timeout that is not a finite number
    When the tool exec_readonly is called with command git rev-parse --is-inside-work-tree and parameter timeout set to <timeout>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the timeout parameter

    Examples: unusable timeouts
      | timeout |
      | abc     |
      | NaN     |
      | inf     |
      | empty   |
      | null    |

  Scenario: exec_readonly keeps its own timeout outcome as a business answer
    When the tool exec_readonly is called with command git rev-parse --is-inside-work-tree and parameter timeout set to 0
    Then the tool reports a business problem instead of a parameter error
    And the tool response carries no raw conversion exception

  # -------------------------------------------------------------- read_file
  Scenario Outline: read_file slices the file with text byte offsets
    When the tool read_file is called on the test file with parameter <param> set to <value>
    Then the tool call is accepted and produces a result
    And the tool output contains LINE

    Examples: coercible byte offsets
      | param | value   |
      | seek  | 5       |
      | seek  | <sp>5<sp> |
      | seek  | 1e1     |
      | size  | 10      |
      | size  | 1e1     |
      | size  | 0       |
      | size  | -1      |
      | seek  | int:6   |

  Scenario Outline: read_file rejects byte offsets that are not finite numbers
    When the tool read_file is called on the test file with parameter <param> set to <value>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the <param> parameter

    Examples: unusable byte offsets
      | param | value |
      | seek  | abc   |
      | seek  | NaN   |
      | seek  | inf   |
      | seek  | empty |
      | seek  | null  |
      | size  | abc   |
      | size  | -inf  |
      | size  | empty |
      | size  | null  |

  Scenario: read_file treats a negative byte offset as a tail slice
    When the tool read_file is called on the test file with parameter seek set to -5
    Then the tool reports a business problem instead of a parameter error
    And the tool response carries no raw conversion exception

  Scenario: read_file combines two text byte offsets
    When the tool read_file is called on the test file with parameters seek set to 10 and size set to 5
    Then the tool call is accepted and produces a result

  # ------------------------------------------------------------ write_file
  Scenario Outline: write_file honours a write mode written as text
    Given a parameter test file named alpha.txt containing the text ABCDEFGHIJ
    When the tool write_file is called on the test file with content NEW and parameters seek set to <seek> and to_insert set to <to_insert>
    Then the tool call is accepted and produces a result
    And the test file now contains NEW

    Examples: coercible write modes
      | seek  | to_insert |
      | 0     | 0         |
      | 3     | 1         |
      | <sp>3<sp> | 1     |
      | 1e1   | 0         |
      | int:2 | int:1     |

  Scenario Outline: write_file refuses a write mode that is not an integer flag
    Given a parameter test file named alpha.txt containing the text ABCDEFGHIJ
    When the tool write_file is called on the test file with content NEW and parameter to_insert set to <to_insert>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the to_insert parameter
    And the test file still contains ABCDEFGHIJ

    Examples: rejected write modes
      | to_insert |
      | 2         |
      | -1        |
      | yes       |
      | true      |
      | empty     |
      | null      |

  Scenario Outline: write_file refuses a byte offset that is not a finite number
    Given a parameter test file named alpha.txt containing the text ABCDEFGHIJ
    When the tool write_file is called on the test file with content NEW and parameter seek set to <seek>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the seek parameter
    And the test file still contains ABCDEFGHIJ

    Examples: unusable byte offsets
      | seek  |
      | abc   |
      | NaN   |
      | inf   |
      | empty |
      | null  |

  # ------------------------------------------------- insert_content_to_file
  Scenario Outline: insert_content_to_file accepts a line number written as text
    When the tool insert_content_to_file is called on the test file with content INSERTED and parameter line_num set to <line_num>
    Then the tool call is accepted and produces a result
    And the tool output contains INSERTED

    Examples: coercible line numbers
      | line_num    |
      | 3           |
      | <sp>3<sp>   |
      | 1e1         |
      | int:5       |

  Scenario Outline: insert_content_to_file rejects a line number that is not a number
    When the tool insert_content_to_file is called on the test file with content INSERTED and parameter line_num set to <line_num>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the line_num parameter

    Examples: unusable line numbers
      | line_num |
      | abc      |
      | NaN      |
      | inf      |
      | empty    |
      | null     |

  # --------------------------------------------------- read_file_around_line
  Scenario Outline: read_file_around_line accepts line arguments written as text
    When the tool read_file_around_line is called on the test file with parameters line_number set to <line_number> and context_num set to <context_num>
    Then the tool call is accepted and produces a result
    And the tool output contains LINE

    Examples: coercible line arguments
      | line_number | context_num |
      | 3           | 3           |
      | <sp>3<sp>   | <sp>2<sp>   |
      | 1e1         | 1           |
      | 3           | 0           |
      | int:4       | int:2       |

  Scenario Outline: read_file_around_line rejects line arguments that are not numbers
    When the tool read_file_around_line is called on the test file with parameters line_number set to <line_number> and context_num set to <context_num>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the <param> parameter

    Examples: unusable line arguments
      | line_number | context_num | param       |
      | abc         | 3           | line_number |
      | NaN         | 3           | line_number |
      | inf         | 3           | line_number |
      | null        | 3           | line_number |
      | empty       | 3           | line_number |
      | 3           | abc         | context_num |
      | 3           | NaN         | context_num |
      | 3           | inf         | context_num |
      | 3           | null        | context_num |

  Scenario Outline: read_file_around_line answers an out-of-range line as a business result
    When the tool read_file_around_line is called on the test file with parameters line_number set to <line_number> and context_num set to 3
    Then the tool reports a business problem instead of a parameter error
    And the tool output contains out of range

    Examples: finite but impossible line numbers
      | line_number |
      | 9999        |
      | -1          |

  # ------------------------------------------------------- read_file_lines
  Scenario Outline: read_file_lines accepts a range written as text
    When the tool read_file_lines is called on the test file with parameters start_num set to <start_num> and end_num set to <end_num>
    Then the tool call is accepted and produces a result
    And the tool output contains LINE

    Examples: coercible ranges
      | start_num | end_num |
      | 2         | 4       |
      | <sp>2<sp> | <sp>4<sp> |
      | 1e1       | 0       |
      | int:1     | int:3   |

  Scenario Outline: read_file_lines rejects a range that is not a number
    When the tool read_file_lines is called on the test file with parameters start_num set to <start_num> and end_num set to <end_num>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the <param> parameter

    Examples: unusable ranges
      | start_num | end_num | param     |
      | abc       | 4       | start_num |
      | NaN       | 4       | start_num |
      | null      | 4       | start_num |
      | empty     | 4       | start_num |
      | 1         | abc     | end_num   |
      | 1         | -inf    | end_num   |
      | 1         | null    | end_num   |

  Scenario: read_file_lines answers an inverted range as a business result
    When the tool read_file_lines is called on the test file with parameters start_num set to 5 and end_num set to 2
    Then the tool reports a business problem instead of a parameter error
    And the tool output contains Invalid range

  # ------------------------------------------------- read_file_with_context
  Scenario Outline: read_file_with_context reads the case switch as an integer flag
    When the tool read_file_with_context is called on the test file with pattern line and parameter case_sensitive set to <flag>
    Then the tool call is accepted and produces a result

    Examples: integer flag spellings
      | flag  |
      | 1     |
      | 0     |
      | <sp>1<sp> |
      | empty |
      | null  |
      | int:0 |

  Scenario Outline: read_file_with_context refuses a case switch written as prose
    When the tool read_file_with_context is called on the test file with pattern LINE and parameter case_sensitive set to <flag>
    Then the tool reports a parameter error inside its text result
    And the parameter error names the case_sensitive parameter

    Examples: rejected flag values
      | flag |
      | 2    |
      | -1   |
      | yes  |
      | true |

  Scenario: read_file_with_context rejects a text context size as a text parameter error
    When the tool read_file_with_context is called on the test file with pattern LINE and parameter context_num set to abc
    Then the tool reports a parameter error inside its text result
    And the parameter error names the context_num parameter

  # ------------------------------------------------- overwrite_lines_in_file
  Scenario Outline: overwrite_lines_in_file accepts line numbers written as text
    Given a parameter test file named short.txt containing lines L1 to L10
    When the tool overwrite_lines_in_file is called on the numbered test file with content REPLACED and parameters start_num set to <start_num> and end_num set to <end_num>
    Then the tool call is accepted and produces a result
    And the numbered test file now contains REPLACED

    Examples: coercible line ranges
      | start_num | end_num |
      | 3         | 4       |
      | <sp>5<sp> | <sp>6<sp> |
      | int:2     | int:2   |
      | 1e1       | 0       |

  Scenario Outline: overwrite_lines_in_file rejects a text line number as a parameter error
    Given a parameter test file named short.txt containing lines L1 to L10
    When the tool overwrite_lines_in_file is called on the numbered test file with content REPLACED and parameters start_num set to <start_num> and end_num set to <end_num>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the <param> parameter

    Examples: unusable line ranges
      | start_num | end_num | param     |
      | abc       | 4       | start_num |
      | 3         | NaN     | end_num   |
      | empty     | 4       | start_num |
      | null      | 4       | start_num |

  # ------------------------------------------------------ container params
  Scenario Outline: read_files accepts native JSON and bare file lists
    When the tool read_files is called with single parameter files set to <files>
    Then the tool call is accepted and produces a result
    And the tool output contains LINE01

    Examples: usable file lists
      | files            |
      | raw:["{file}"]   |
      | ["{file}"]       |
      | {file}           |

  Scenario Outline: read_files rejects a file list it cannot understand
    When the tool read_files is called with single parameter files set to <files>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the files parameter

    Examples: unusable file lists
      | files        |
      | {"a":1}      |
      | [bad         |
      | empty        |
      | null         |

  Scenario Outline: list_dirs accepts native JSON and bare folder lists
    When the tool list_dirs is called with single parameter dirs set to <dirs>
    Then the tool call is accepted and produces a result
    And the tool output contains sample.txt

    Examples: usable folder lists
      | dirs            |
      | raw:["{folder}"] |
      | ["{folder}"]     |
      | {folder}         |

  Scenario Outline: list_dirs rejects a folder list it cannot understand
    When the tool list_dirs is called with single parameter dirs set to <dirs>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the dirs parameter

    Examples: unusable folder lists
      | dirs    |
      | {"a":1} |
      | [bad    |
      | empty   |
      | null    |

  Scenario: mkdirs creates a folder requested through JSON text
    When the tool mkdirs is called with single parameter dirs set to ["{folder}/made-by-json"]
    Then the tool call is accepted and produces a result
    And the tool output contains True

  Scenario: mkdirs creates a folder requested through a native list
    When the tool mkdirs is called with single parameter dirs set to raw:["{folder}/made-by-list"]
    Then the tool call is accepted and produces a result
    And the tool output contains True

  Scenario: mkdirs creates a folder requested through a bare string
    When the tool mkdirs is called with single parameter dirs set to {folder}/made-by-bare-string
    Then the tool call is accepted and produces a result
    And the tool output contains True

  Scenario: mkdirs rejects a relative folder instead of raising an assertion
    When the tool mkdirs is called with single parameter dirs set to ["rel/dir"]
    Then the tool returns a machine-readable parameter error
    And the parameter error names the dirs parameter

  Scenario Outline: mkdirs rejects a folder list it cannot understand
    When the tool mkdirs is called with single parameter dirs set to <dirs>
    Then the tool returns a machine-readable parameter error
    And the parameter error names the dirs parameter

    Examples: unusable folder lists
      | dirs    |
      | {"a":1} |
      | [bad    |
      | empty   |
      | null    |
      | rel/dir |
