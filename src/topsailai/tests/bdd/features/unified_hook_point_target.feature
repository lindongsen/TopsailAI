@bdd
Feature: Target Hook Point execution across real isolated workers
  U11A acceptance: a host waits for one complete target plan, Modules main run
  in Unicode name order before ordered Scripts, and normal data is not policy.

  Scenario: Reversed sources execute in two name-ordered phases
    Given a real target Hook Point with ordered sources
    When the host waits for the target Hook Point execution
    Then the target business result matches the ordered acceptance contract
    And target process evidence and owned resources are settled

  Scenario: An empty point still executes exactly one default Hook
    Given a real target Hook Point with empty sources
    When the host waits for the target Hook Point execution
    Then the target business result matches the empty acceptance contract
    And target process evidence and owned resources are settled

  Scenario Outline: Normal module returns preserve presence without granting authority
    Given a real target Hook Point with <partition> sources
    When the host waits for the target Hook Point execution
    Then the target business result matches the <partition> acceptance contract
    And target process evidence and owned resources are settled
    Examples:
      | partition  |
      | none       |
      | false      |
      | error-dict |
      | opaque     |
