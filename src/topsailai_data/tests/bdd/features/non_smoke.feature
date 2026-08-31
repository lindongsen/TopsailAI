Feature: Non-smoke BDD selection
  @core
  Scenario: Run a normal scenario outside the smoke selection
    Given an isolated topsailai-data store
    When I create object "regular-note" from fixture "markdown/valid.md"
    Then the command succeeds
