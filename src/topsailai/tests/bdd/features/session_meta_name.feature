Feature: Session names remain observable in process metadata
  The approved session metadata contract projects committed names locally
  without additional LLM requests or changing completion state

  Scenario: Automatically name a session and resume its metadata snapshot
    Given an isolated metadata session with a real naming provider
    When the Agent completes naming and resumes the same session
    Then the metadata retains the committed name and terminal timestamp
    And naming uses exactly one isolated provider request
