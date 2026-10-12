Feature: Awaited target Hook lifecycle preserves stop authority
  As a host awaiting configured Hooks
  I need cancellation and absolute deadlines to stop execution and its successors
  So that no business script runs after the stop boundary

  Scenario Outline: Target awaited execution stops safely
    Given real target lifecycle scripts for <mode>
    When the host awaits the target lifecycle stop boundary
    Then target lifecycle children and custody are settled without successors

    Examples:
      | mode     |
      | cancel   |
      | expired  |
      | deadline |
