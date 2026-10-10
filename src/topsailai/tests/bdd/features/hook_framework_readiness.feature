Feature: Hook framework readiness wrappers
  As an application developer
  I want configured registration and callable Hook points to share stable contracts
  So that core flows can add Hook points without changing their normal behavior

  Scenario: Startup mode registers before business execution
    Given a startup configured Hook Registrar
    When the application starts configured Hooks
    Then the configured Hook is registered exactly once and ready

  Scenario: Lazy mode registers on first use only
    Given a lazy configured Hook Registrar
    When the configured Hook is ensured twice
    Then the configured Hook is registered exactly once and ready

  Scenario: A decorated callable publishes before and success points
    Given a callable decorated with distinct before success and error Hook points
    When the decorated callable returns normally
    Then before and success run once and error does not run
    And the exact business result object is returned

  Scenario: A decorated callable preserves its business exception
    Given a callable decorated with distinct before success and error Hook points
    When the decorated callable raises its business exception
    Then before and error run once and success does not run
    And the exact business exception and traceback are preserved
