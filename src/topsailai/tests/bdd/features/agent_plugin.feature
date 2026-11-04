Feature: Explicit assistant plugin loading
  The operator opts into assistant tools without changing core story support

  Scenario Outline: Plugin configuration and enablement control availability
    Given assistant plugin configuration is "<configuration>"
    When the tool registry starts in a fresh process
    Then assistant tool availability is "<availability>" and core story helpers remain usable

    Examples:
      | configuration | availability |
      | absent        | absent       |
      | enabled       | present      |
      | disabled      | absent       |
      | default-flag  | absent       |
