Feature: Session agent driver drives a target session
  As an operator
  I want the driver to poll a target session and drive it with input
  So that the target agent progresses without manual intervention

  Scenario: Driver injects input when the target session waits for input
    Given a target session waiting for input
    And an analysis agent that decides to inject input
    When the driver runs one polling cycle
    Then the target session receives the injected input
    And the driver continues polling

  Scenario: Driver exits when the analysis agent requests exit
    Given a target session waiting for input
    And an analysis agent that decides the goal is complete
    When the driver runs one polling cycle
    Then the driver requests exit
    And the driver stops polling

  Scenario: Driver exits when the target session process exits
    Given a target session whose process has exited
    When the driver checks the session status
    Then the driver exits its polling loop

  Scenario: Driver keeps polling after an injection failure
    Given a target session waiting for input
    And an analysis agent whose injection fails
    When the driver runs one polling cycle
    Then the analysis agent shuts down completely
    And the driver continues polling

  Scenario: Driver waits while the target session is running
    Given a target session that is running
    When the driver runs one polling cycle
    Then the driver does not start an analysis agent
    And the driver continues polling
