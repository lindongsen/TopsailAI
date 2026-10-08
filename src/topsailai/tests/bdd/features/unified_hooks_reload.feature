Feature: Standalone Unified Hooks reload and admission snapshots
  As a host application
  I want operational reload and registry mutations to affect only future admissions
  So that admitted hook work remains coherent while later work observes current state

  Scenario: Reload publishes current settings while admitted work keeps its captured generation
    Given a standalone Unified Hooks reload runtime with an admitted old plan
    When the host changes registrations and reloads settings during real worker execution
    And the Unified Hooks reload runtime is closed
    Then the admitted report keeps the old generation and binding plan
    And the later report uses the latest generation and binding plan
    And no-op and rejected reloads do not advance generation
    And reload leaves the host main flow intact
    And the reload runtime and observed workers are settled
