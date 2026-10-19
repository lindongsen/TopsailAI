@bdd
Feature: PromptBase initialization Hook Point
  The PromptBase completion point observes a successfully initialized base.

  Scenario: A real Module observes one PromptBase instance
    Given a real PromptBase initialization Module
    When PromptBase is constructed for the Hook scenario
    Then the Module ran exactly once with the same PromptBase instance

  Scenario: An ordinary Module failure does not break PromptBase construction
    Given a failing PromptBase initialization Module
    When PromptBase is constructed for the Hook scenario
    Then PromptBase construction succeeds and the Module failure was executed
