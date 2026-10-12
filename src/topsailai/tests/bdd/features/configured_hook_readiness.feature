Feature: Real Catalog wrapper business authority
  As an application owner I require isolated Hook failures to obey declared phase policy
  without rolling back mutations or replacing original business errors.

  Scenario Outline: Declared wrapper policy respects business facts
    Given a real <mode> Catalog wrapper for <case>
    When the host executes the decorated business operation
    Then wrapper workers and captures converge without changing business facts

    Examples:
      | mode  | case              |
      | sync  | before-report     |
      | sync  | before-block      |
      | sync  | success-block     |
      | sync  | error-block       |
      | sync  | normal-none       |
      | sync  | normal-false      |
      | sync  | normal-error-dict |
      | async | before-report     |
      | async | before-block      |
      | async | success-block     |
      | async | error-block       |
      | async | normal-none       |
      | async | normal-false      |
      | async | normal-error-dict |
