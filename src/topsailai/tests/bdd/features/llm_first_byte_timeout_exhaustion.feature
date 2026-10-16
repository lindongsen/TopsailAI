Feature: Exhaust first-byte timeout retries

  Scenario Outline: exhaust all non-interactive first-byte timeout attempts
    Given a real U5 <phase> timeout exhaustion scenario
    When the U5 production retry loop is executed
    Then U5 records exactly 18 attempts and 18 requests
    And U5 proves terminal settlement and no nineteenth request

    Examples:
      | phase      |
      | headers    |
      | first_item |
