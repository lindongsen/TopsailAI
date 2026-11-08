Feature: output read authorization
  Session output carries prompts, model answers, tool arguments and command
  results, so reading it requires the read_output permission. Both output
  surfaces are covered because the follow route was copied from the snapshot
  route and inherited the same missing check: a fix applied to one route would
  leave the other open.

  Scenario: a credential without read output cannot read a snapshot
    Given a real cluster whose credential may only view
    When the logs command is run with a credential that may only view
    Then the output request is refused for lack of read output permission

  Scenario: a credential without read output cannot follow a stream
    Given a real cluster whose credential may only view
    When the logs follow command is run with a credential that may only view
    Then the follow request is refused for lack of read output permission

  Scenario: a credential with read output still reads a snapshot
    Given a real cluster whose credential may read output
    When the logs command is run with a credential that may read output
    Then the output request returns provider output
