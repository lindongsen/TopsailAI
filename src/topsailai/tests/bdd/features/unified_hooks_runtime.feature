Feature: Standalone Unified Hooks runtime boundary
  As a host application
  I want optional hooks to run through an independently owned runtime
  So that hook reports are observable without replacing the host main flow

  Scenario Outline: The host observes a bounded standalone runtime report
    Given a standalone Unified Hooks runtime with <binding_state> bindings
    When the host marks its main flow around one public runtime dispatch
    And the standalone Unified Hooks runtime is closed
    Then the host main-flow markers remain intact
    And the <binding_state> Unified Hooks report is observable
    And worker launch and handler call counts match the public plan
    And the Unified Hooks public lifecycle and observed workers are settled

    Examples:
      | binding_state |
      | empty         |
      | minimal       |

  Scenario Outline: A module hook failure remains optional to the host
    Given a standalone Unified Hooks runtime with <failure_state> bindings
    When the host marks its main flow around one public runtime dispatch
    And the standalone Unified Hooks runtime is closed
    Then the host main-flow markers remain intact
    And the <failure_state> Unified Hooks report is observable
    And worker launch and handler call counts match the public plan
    And the Unified Hooks public lifecycle and observed workers are settled

    Examples:
      | failure_state   |
      | handler-failure |
      | process-failure |

  Scenario: A module load failure preserves other valid hook work
    Given a standalone Unified Hooks runtime with load-failure bindings
    When the host marks its main flow around one public runtime dispatch
    And the standalone Unified Hooks runtime is closed
    Then the host main-flow markers remain intact
    And the load-failure Unified Hooks report is observable
    And worker launch and handler call counts match the public plan
    And the Unified Hooks public lifecycle and observed workers are settled

  Scenario: Multiple module hooks execute in stable plan order
    Given a standalone Unified Hooks runtime with ordered bindings
    When the host marks its main flow around one public runtime dispatch
    And the standalone Unified Hooks runtime is closed
    Then the host main-flow markers remain intact
    And the ordered Unified Hooks report is observable
    And worker launch and handler call counts match the public plan
    And the Unified Hooks public lifecycle and observed workers are settled
