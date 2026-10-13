Feature: Session naming cannot consume Agent startup context
  As an agent operator
  I want automatic session naming isolated from startup context
  So that the real Agent receives USER.md on its first turn

  Scenario: A fresh plan Agent loads USER.md before session naming
    Given a fresh plan Agent startup scenario with automatic naming enabled
    When the plan Agent runs its first real turn
    Then the Manager request contains the USER.md marker
    And the naming request omits the USER.md and explicit startup markers
    And the naming request is made only after Agent startup is published
    And the session name update completes
    And the later plan Agent turn completes without reloading USER.md

  Scenario: A fresh chat Agent keeps startup context isolated across turns
    Given a fresh chat Agent startup scenario with automatic naming enabled
    When the chat Agent runs its first real turn
    Then the chat Manager request contains the USER.md marker
    And the chat naming request omits the USER.md and explicit startup markers
    And the chat naming request is made only after Agent startup is published
    And the chat session name update completes
    And the later chat Agent turn completes without reloading USER.md
