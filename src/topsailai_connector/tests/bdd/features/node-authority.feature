Feature: The Node controls every permission
  The Node is the only authority for permissions. A scope names an area and a
  permission names an action, and both are decided by the Node's own policy file.
  Nothing outside the Node can widen either one.

  Scenario: A granted read succeeds
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    When the node loads the policy
    Then the node starts
    When the caller reads "note.txt" on scope "project"
    Then the caller receives "hello"

  Scenario: A scope with no grant refuses a read
    Given a policy that grants nothing on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    When the node loads the policy
    Then the node starts
    When the caller reads "note.txt" on scope "project"
    Then the caller receives the code "denied"

  Scenario: An undefined scope refuses a read
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    When the node loads the policy
    Then the node starts
    When the caller reads "note.txt" on scope "other"
    Then the caller receives the code "denied"

  Scenario: A read grant does not imply a list grant
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    When the node loads the policy
    Then the node starts
    When the caller lists "." on scope "project"
    Then the caller receives the code "denied"

  Scenario: A read grant does not imply a stat grant
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    When the node loads the policy
    Then the node starts
    When the caller stats "note.txt" on scope "project"
    Then the caller receives the code "denied"

  Scenario: A write is refused even when the policy grants it
    Given a policy that grants write on scope "project"
    When the node loads the policy
    Then the node starts
    When the caller writes "note.txt" on scope "project"
    Then the caller receives the code "denied"

  Scenario: A command is refused even when the policy grants it
    Given a policy that grants exec on scope "project"
    When the node loads the policy
    Then the node starts
    When the caller runs a command on scope "project"
    Then the caller receives the code "denied"
