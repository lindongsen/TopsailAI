@bdd
Feature: Registrar reload preserves a usable isolated target plan
  U11B acceptance: desired configuration is not active publication authority;
  failed whole-plan replacements preserve LKG and first failure is unavailable.

  Scenario: Rejected desired revision exposes mismatch and still executes LKG
    Given a real Registrar with mismatch reload sources
    When the host executes the Registrar reload business flow
    Then reload workers and captured resources are settled

  Scenario: A later valid revision replaces the retained LKG plan
    Given a real Registrar with recovery reload sources
    When the host executes the Registrar reload business flow
    Then reload workers and captured resources are settled

  Scenario: First rejected candidate has no active plan or worker execution
    Given a real Registrar with first-failure reload sources
    When the host executes the Registrar reload business flow
    Then reload workers and captured resources are settled
