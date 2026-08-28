Feature: Remote tools accept string-typed parameters from the LLM
  Remote tools declare numbers, integer flags and containers, yet an LLM sends every
  one of those arguments as text. A remote tool must still reach the transport with a
  correctly converted value, and when the text cannot be understood it must answer
  with a machine-readable parameter error *before* opening any connection or starting
  any subprocess.

  Background:
    Given a local payload file named payload.txt for the copy operation
    And a local folder named srcdir for the rsync operation
    And a skill folder holding the offline script scripts/echo.sh

  # ---------------------------------------------------------- call_sandbox timeout

  Scenario Outline: call_sandbox understands a timeout that arrives as text
    When the remote tool call_sandbox is invoked with parameter timeout set to <timeout>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received timeout equal to 120
    And the remote response carries no raw conversion exception

    Examples: timeout spellings an LLM really sends
      | timeout     |
      | 120         |
      | <sp>120<sp> |
      | int:120     |

  Scenario Outline: call_sandbox converts a scientific notation timeout
    When the remote tool call_sandbox is invoked with parameter timeout set to <timeout>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received timeout equal to 100

    Examples: exponential text
      | timeout |
      | 1e2     |
      | 1.0e2   |

  Scenario Outline: call_sandbox keeps its own default when the timeout is zero
    A zero timeout is an existing business rule of this tool, not a bad argument.
    When the remote tool call_sandbox is invoked with parameter timeout set to <timeout>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received timeout equal to 30

    Examples: zero in any spelling
      | timeout |
      | 0       |
      | int:0   |

  Scenario Outline: call_sandbox rejects a timeout that is not a finite number
    When the remote tool call_sandbox is invoked with parameter timeout set to <timeout>
    Then the remote call is rejected as a parameter error before any connection
    And the parameter error names the timeout remote parameter
    And the remote response carries no raw conversion exception

    Examples: unusable timeout text
      | timeout |
      | abc     |
      | NaN     |
      | inf     |
      | -inf    |
      | empty   |
      | null    |

  # --------------------------------------------------------- copy2sandbox timeout

  Scenario Outline: copy2sandbox understands a timeout that arrives as text
    When the remote tool copy2sandbox is invoked with parameter timeout set to <timeout>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received timeout equal to 60
    And the copy operation reports success

    Examples: timeout spellings an LLM really sends
      | timeout     |
      | 60          |
      | <sp>60<sp>  |
      | int:60      |

  Scenario Outline: copy2sandbox converts a scientific notation timeout
    When the remote tool copy2sandbox is invoked with parameter timeout set to <timeout>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received timeout equal to 60

    Examples: exponential text
      | timeout |
      | 6e1     |
      | 60.0    |

  Scenario Outline: copy2sandbox rejects a timeout that is not a finite number
    When the remote tool copy2sandbox is invoked with parameter timeout set to <timeout>
    Then the remote call is rejected as a parameter error before any connection
    And the parameter error names the timeout remote parameter

    Examples: unusable timeout text
      | timeout |
      | abc     |
      | NaN     |
      | inf     |
      | empty   |
      | null    |

  # ------------------------------------------------------------- operate_ssh port

  Scenario Outline: operate_ssh understands a port that arrives as text
    When the remote tool operate_ssh is invoked with parameter port set to <port>
    Then the remote call is accepted and reaches the transport once
    And the remote command line contains -p 22
    And the remote response carries no raw conversion exception

    Examples: port spellings an LLM really sends
      | port        |
      | 22          |
      | <sp>22<sp>  |
      | int:22      |

  Scenario Outline: operate_ssh converts a scientific notation port
    When the remote tool operate_ssh is invoked with parameter port set to <port>
    Then the remote call is accepted and reaches the transport once
    And the remote command line contains -p 22

    Examples: exponential text
      | port  |
      | 2.2e1 |
      | 22.0  |

  Scenario Outline: operate_ssh refuses a port outside the valid range
    A finite but impossible port is still a bad argument for a network tool.
    When the remote tool operate_ssh is invoked with parameter port set to <port>
    Then the remote call is rejected as a parameter error before any connection
    And the parameter error names the port remote parameter

    Examples: impossible ports
      | port  |
      | 0     |
      | -1    |
      | 70000 |

  Scenario Outline: operate_ssh rejects a port that is not a number
    When the remote tool operate_ssh is invoked with parameter port set to <port>
    Then the remote call is rejected as a parameter error before any connection
    And the parameter error names the port remote parameter

    Examples: unusable port text
      | port  |
      | abc   |
      | NaN   |
      | inf   |
      | empty |
      | null  |

  # ---------------------------------------------------------- operate_ssh timeout

  Scenario Outline: operate_ssh understands a timeout that arrives as text
    When the remote tool operate_ssh is invoked with parameter timeout set to <timeout>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received timeout equal to 30

    Examples: timeout spellings an LLM really sends
      | timeout     |
      | 30          |
      | <sp>30<sp>  |
      | int:30      |

  Scenario Outline: operate_ssh converts a scientific notation timeout
    When the remote tool operate_ssh is invoked with parameter timeout set to <timeout>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received timeout equal to 30

    Examples: exponential text
      | timeout |
      | 3e1     |
      | 30.0    |

  Scenario: operate_ssh passes a finite zero timeout through unchanged
    When the remote tool operate_ssh is invoked with parameter timeout set to 0
    Then the remote call is accepted and reaches the transport once
    And the remote transport received timeout equal to 0

  Scenario Outline: operate_ssh rejects a timeout that is not a finite number
    When the remote tool operate_ssh is invoked with parameter timeout set to <timeout>
    Then the remote call is rejected as a parameter error before any connection
    And the parameter error names the timeout remote parameter

    Examples: unusable timeout text
      | timeout |
      | abc     |
      | NaN     |
      | -inf    |
      | empty   |
      | null    |

  # ------------------------------------------------------- operate_ssh delete flag

  Scenario Outline: operate_ssh enables rsync delete only for the integer one
    When the remote tool operate_ssh is invoked for rsync with parameter delete set to <flag>
    Then the remote call is accepted and reaches the transport once
    And the remote command line contains --delete

    Examples: integer one
      | flag        |
      | 1           |
      | <sp>1<sp>   |
      | int:1       |

  Scenario Outline: operate_ssh must not read the text zero as enable delete
    When the remote tool operate_ssh is invoked for rsync with parameter delete set to <flag>
    Then the remote call is accepted and reaches the transport once
    And the remote command line does not contain --delete

    Examples: integer zero
      | flag        |
      | 0           |
      | <sp>0<sp>   |
      | int:0       |

  Scenario Outline: operate_ssh refuses a delete switch written as prose or out of range
    When the remote tool operate_ssh is invoked for rsync with parameter delete set to <flag>
    Then the remote call is rejected as a parameter error before any connection
    And the parameter error names the delete remote parameter
    And the remote command line does not contain --delete

    Examples: rejected flag values
      | flag  |
      | 2     |
      | -1    |
      | yes   |
      | true  |
      | empty |
      | null  |

  # ------------------------------------------------------ operate_ssh options

  Scenario Outline: operate_ssh accepts ssh options in every documented shape
    When the remote tool operate_ssh is invoked with parameter options set to <options>
    Then the remote call is accepted and reaches the transport once
    And the remote command line contains Compression=yes

    Examples: option shapes
      | options                       |
      | Compression=yes               |
      | raw:["Compression=yes"]       |
      | raw:{"Compression": "yes"}    |
      | ["Compression=yes"]           |
      | {"Compression": "yes"}        |

  Scenario Outline: operate_ssh rejects options it cannot turn into ssh arguments
    When the remote tool operate_ssh is invoked with parameter options set to <options>
    Then the remote call is rejected as a parameter error before any connection
    And the parameter error names the options remote parameter

    Examples: broken option values
      | options  |
      | [bad     |
      | {"bad"   |
      | int:3    |

  # ----------------------------------------------------------- call_skill timeout

  Scenario Outline: call_skill understands a timeout that arrives as text
    When the remote tool call_skill is invoked with parameter timeout set to <timeout>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received timeout equal to 120
    And the remote response carries no raw conversion exception

    Examples: timeout spellings an LLM really sends
      | timeout     |
      | 120         |
      | <sp>120<sp> |
      | int:120     |

  Scenario Outline: call_skill converts a scientific notation timeout
    When the remote tool call_skill is invoked with parameter timeout set to <timeout>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received timeout equal to 100

    Examples: exponential text
      | timeout |
      | 1e2     |
      | 1.0e2   |

  Scenario Outline: call_skill rejects a timeout that is not a finite number
    When the remote tool call_skill is invoked with parameter timeout set to <timeout>
    Then the remote call is rejected as a parameter error before any connection
    And the parameter error names the timeout remote parameter
    And the remote response carries no raw conversion exception

    Examples: unusable timeout text
      | timeout |
      | abc     |
      | NaN     |
      | inf     |
      | -inf    |
      | empty   |
      | null    |

  # ----------------------------------------------------- call_skill stderr flag

  Scenario Outline: call_skill reads the stderr switch as the integer one
    When the remote tool call_skill is invoked with parameter no_need_stderr set to <flag>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received no_need_stderr equal to True

    Examples: integer one
      | flag      |
      | 1         |
      | <sp>1<sp> |
      | int:1     |

  Scenario Outline: call_skill reads the stderr switch as the integer zero
    When the remote tool call_skill is invoked with parameter no_need_stderr set to <flag>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received no_need_stderr equal to False

    Examples: integer zero
      | flag      |
      | 0         |
      | <sp>0<sp> |
      | int:0     |

  Scenario Outline: call_skill refuses a stderr switch written as prose
    When the remote tool call_skill is invoked with parameter no_need_stderr set to <flag>
    Then the remote call is rejected as a parameter error before any connection
    And the parameter error names the no_need_stderr remote parameter

    Examples: rejected flag values
      | flag  |
      | 2     |
      | -1    |
      | yes   |
      | true  |
      | empty |
      | null  |

  # ------------------------------------------------------- call_skill environ

  Scenario Outline: call_skill accepts environment overrides as a mapping or as JSON text
    When the remote tool call_skill is invoked with parameter environ set to <environ>
    Then the remote call is accepted and reaches the transport once
    And the remote transport received env_info as the mapping {"BDD": "ok"}

    Examples: mapping shapes
      | environ                      |
      | raw:{"BDD": "ok"}            |
      | {"BDD": "ok"}                |

  Scenario: call_skill treats an omitted environment mapping as no override
    When the remote tool call_skill is invoked with parameter environ set to null
    Then the remote call is accepted and reaches the transport once
    And the remote transport received env_info equal to None

  Scenario Outline: call_skill rejects an environment override it cannot decode
    When the remote tool call_skill is invoked with parameter environ set to <environ>
    Then the remote call is rejected as a parameter error before any connection
    And the parameter error names the environ remote parameter
    And the remote response carries no raw conversion exception

    Examples: broken mapping values
      | environ  |
      | [bad     |
      | ["a"]    |
      | empty    |

  # ------------------------------------------------------ call_skill stdin_text

  Scenario: call_skill forwards plain text to the script standard input
    When the remote tool call_skill is invoked with parameter stdin_text set to hello
    Then the remote call is accepted and reaches the transport once

  Scenario Outline: call_skill rejects a standard input payload that is not text
    When the remote tool call_skill is invoked with parameter stdin_text set to <payload>
    Then the remote call is rejected as a parameter error before any connection
    And the parameter error names the stdin_text remote parameter
    And the remote response carries no raw conversion exception

    Examples: non-text payloads
      | payload      |
      | raw:["a"]    |
      | int:123      |

  # ------------------------------------------------- call_skill script_parameters

  Scenario Outline: call_skill accepts script parameters as text or as a native list
    When the remote tool call_skill is invoked with parameter script_parameters set to <params>
    Then the remote call is accepted and reaches the transport once
    And the remote command line contains --flag x

    Examples: parameter shapes
      | params                  |
      | --flag x                |
      | raw:["--flag", "x"]     |

  Scenario: call_skill understands script parameters serialized as a JSON array
    An LLM that serialized a list argument sends JSON text, which must not be
    split into broken shell words.
    When the remote tool call_skill is invoked with parameter script_parameters set to ["--flag", "x"]
    Then the remote call is accepted and reaches the transport once
    And the remote command line contains --flag x

  # ------------------------------------------------------------- offline skill run

  Scenario Outline: the offline skill script runs with a timeout that arrived as text
    When the skill tool call_skill is really invoked with parameter timeout set to <timeout>
    Then the offline skill script prints its marker

    Examples: timeout spellings an LLM really sends
      | timeout     |
      | 120         |
      | <sp>120<sp> |
      | 1e2         |
      | int:120     |

  # ----------------------------------------------------------- list_sandbox guard

  Scenario: list_sandbox answers an unconfigured environment without crashing
    When the remote tool list_sandbox is invoked with parameter tag set to bdd
    Then the remote tool reports that sandbox configuration is unavailable
