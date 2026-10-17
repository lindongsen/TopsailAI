@bdd
Feature: Module admission accepts Python source and platform extension modules
  Scenario Outline: Point entry Module admission boundary <case>
    Given a live point entry fixture <case>
    When the business invokes the public named Hook Point
    Then exact module admission evidence matches the declaration

    Examples:
      | case |
      | compiled |
      | duplicate-logical |
      | source-and-init |
