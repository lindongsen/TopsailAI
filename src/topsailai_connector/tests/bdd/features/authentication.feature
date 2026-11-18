Feature: The Node admits only a proof it can verify
  A caller proves it may talk to this Node by signing a canonical string with a
  credential the Node holds. The credential itself never travels, so a captured
  proof yields no reusable secret and an edited proof stops verifying.

  The Node is the only verifier. The Server forwards the proof unchanged and
  cannot mint one, because it never holds a Node credential.

  Scenario: A proof signed with a credential the Node holds is admitted
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    And the node holds a credential the caller knows
    When the node loads the policy
    Then the node starts
    When the caller sends a read of "note.txt" on scope "project"
    Then the response carries the file content "hello"

  Scenario: A proof signed with a credential the Node does not hold is refused
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    And the caller signs with a credential the node does not hold
    When the node loads the policy
    Then the node starts
    When the caller sends a read of "note.txt" on scope "project"
    Then the response carries the code "unauthenticated"

  Scenario: A replayed proof is refused
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    And the node holds a credential the caller knows
    When the node loads the policy
    Then the node starts
    When the caller sends a read of "note.txt" on scope "project"
    Then the response carries the file content "hello"
    When the caller sends the same request again
    Then the response carries the code "unauthenticated"

  Scenario: A proof whose timestamp is outside the window is refused
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    And the caller signs with a timestamp older than the window
    When the node loads the policy
    Then the node starts
    When the caller sends a read of "note.txt" on scope "project"
    Then the response carries the code "unauthenticated"

  Scenario: A proof whose path was changed after signing is refused
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    And a file "other.txt" inside the scope containing "secret"
    And the node holds a credential the caller knows
    When the node loads the policy
    Then the node starts
    When the caller sends a read of "note.txt" on scope "project"
    Then the response carries the file content "hello"
    When the caller changes the path to "other.txt" after signing
    Then the response carries the code "unauthenticated"

  Scenario: A request with no proof is refused
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    And the node holds a credential the caller knows
    When the node loads the policy
    Then the node starts
    When the caller sends a read of "note.txt" on scope "project"
    Then the response carries the file content "hello"
    When the caller removes the proof after signing
    Then the response carries the code "unauthenticated"

  Scenario: A proof built for one node is refused by another
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    And the node holds a credential the caller knows
    When the node loads the policy
    Then the node starts
    When the caller sends a read of "note.txt" on scope "project"
    Then the response carries the file content "hello"
    When the caller changes the node id after signing
    Then the response carries the code "denied"

  Scenario: A refusal names the key id and never the secret
    Given a policy that grants read on scope "project"
    And a file "note.txt" inside the scope containing "hello"
    And the caller signs with a credential the node does not hold
    When the node loads the policy
    Then the node starts
    When the caller sends a read of "note.txt" on scope "project"
    Then the response carries the code "unauthenticated"
    And the node log does not contain the credential secret
    And the node log names the key id "bdd-other"
