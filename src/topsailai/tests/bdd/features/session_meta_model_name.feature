Feature: Session metadata records the applied model name
  The session metadata file records the model name once at creation
  and must follow every later model switch so operators can trust it

  Scenario: Selecting a registered model updates the metadata file
    Given an isolated session metadata file created for the current process
    When the operator selects a registered model through the instruction
    Then the metadata file records the newly applied model name
    And the instruction reports the previous and applied model names
