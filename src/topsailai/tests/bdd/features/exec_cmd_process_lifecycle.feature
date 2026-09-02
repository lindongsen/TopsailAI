Feature: exec_cmd owns the complete command process lifecycle
  A caller must be able to impose a timeout without leaving the shell, command,
  or descendants running, while retaining normal input and output behavior.

  Scenario: A timed-out string command cleans up its complete process group
    When exec_cmd lifecycle runs a string command that records a child and exceeds its timeout
    Then exec_cmd lifecycle raises TimeoutExpired
    And exec_cmd lifecycle leaves no recorded child process running

  Scenario: A timed-out list command cleans up all descendants
    When exec_cmd lifecycle runs a list command that records a descendant and exceeds its timeout
    Then exec_cmd lifecycle raises TimeoutExpired
    And exec_cmd lifecycle leaves no recorded child process running

  Scenario: Timeout cleanup releases the direct process and its pipes
    When exec_cmd lifecycle times out a command with all standard pipes open
    Then exec_cmd lifecycle raises TimeoutExpired
    And exec_cmd lifecycle has reaped the direct process
    And exec_cmd lifecycle has closed all standard pipes

  Scenario Outline: Command input reaches the child and returns through stdout
    When exec_cmd lifecycle sends <input_kind> containing lifecycle-input to a child
    Then exec_cmd lifecycle returns code 0 stdout lifecycle-input and empty stderr

    Examples:
      | input_kind |
      | input      |
      | stdin_text |

  Scenario: Input cannot be combined with an explicit stdin stream
    When exec_cmd lifecycle combines input bytes with an explicit stdin pipe
    Then exec_cmd lifecycle raises the input and stdin conflict error

  Scenario: Normal execution preserves return code stdout and stderr
    When exec_cmd lifecycle runs a command that exits 7 with stdout normal-out and stderr normal-err
    Then exec_cmd lifecycle returns code 7 stdout normal-out and stderr normal-err
