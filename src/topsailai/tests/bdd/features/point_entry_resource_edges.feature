@bdd
Feature: Point entry resource admission edges on the live tree
  A symbolic link is never followed. Any symlink child rejects the complete
  affected point instead of being admitted or silently skipped, so a resource
  that resolves outside the selected tree can never run.

  Scenario Outline: Point entry resource edge <case>
    Given a live point entry resource fixture <case>
    When the business invokes the public named Hook Point
    Then exact resource edge evidence matches the declaration

    Examples:
      | case |
      | symlink-inside |
      | symlink-escape |
      | symlink-directory |
      | ordering-logical |
