Feature: The path fence keeps a read inside its scope
  A scope is a directory. Every path a caller states is resolved inside it, and a
  path that would leave it is refused before any file is opened. The fence is
  enforced by the operating system through a directory handle, not by comparing
  strings, so a traversal, an absolute path and a symlink are all refused the same
  way.

  Scenario: A relative path inside the scope is read
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    When the node loads the policy
    Then the node starts
    When the caller reads "note.txt" on scope "project"
    Then the caller receives "hello"

  Scenario: A traversal is refused
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    When the node loads the policy
    Then the node starts
    When the caller reads "../outside/secret.txt" on scope "project"
    Then the caller receives the code "invalid_argument"

  Scenario: An absolute path is refused
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    When the node loads the policy
    Then the node starts
    When the caller reads "/etc/passwd" on scope "project"
    Then the caller receives the code "invalid_argument"

  Scenario: A symlink that leaves the scope is refused
    Given a policy that grants read on scope "project"
    And a symlink "escape" inside the scope pointing outside it
    When the node loads the policy
    Then the node starts
    When the caller reads "escape/secret.txt" on scope "project"
    Then the caller receives the code "denied"

  Scenario: A symlink is reported as a link rather than followed
    Given a policy that grants read and stat on scope "project"
    And a symlink "escape" inside the scope pointing outside it
    When the node loads the policy
    Then the node starts
    When the caller stats "escape" on scope "project"
    Then the entry is a "symlink"
    And the entry reports a symlink

  Scenario: A missing file is reported as missing
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    When the node loads the policy
    Then the node starts
    When the caller reads "absent.txt" on scope "project"
    Then the caller receives the code "not_found"
