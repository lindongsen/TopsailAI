Feature: List and search topsailai-data objects

  Scenario: Empty list is a structural empty array in YAML and JSON
    Given an isolated topsailai-data store
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | yaml |
    Then the command succeeds
    And the YAML list has exactly IDs ""
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | json |
    Then the command succeeds
    And the JSON list has exactly IDs ""

  Scenario: List exposes active objects with pagination and both time sort directions
    Given an isolated topsailai-data store
    When I create object "list-one" from fixture "markdown/valid.md" with description "One" and classify "list/one"
    Then the command succeeds
    When I wait for a new time-prefix minute after "list-one"
    When I create object "list-two" from fixture "markdown/alternate.md" with description "Two" and classify "list/two"
    Then the command succeeds
    When I wait for a new time-prefix minute after "list-two"
    When I create object "list-three" from fixture "markdown/valid.md" with description "Three" and classify "list/three"
    Then the command succeeds
    And the sort fixtures have distinct public time-prefix keys
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | json |
      | --sort |
      | time:desc |
    Then the command succeeds
    And the JSON list has exactly IDs "list-three,list-two,list-one"
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | yaml |
      | --sort |
      | time:asc |
    Then the command succeeds
    And the YAML list has exactly IDs "list-one,list-two,list-three"
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | json |
      | --sort |
      | time:asc |
      | --offset |
      | 1 |
      | --limit |
      | 1 |
    Then the command succeeds
    And the JSON list has exactly IDs "list-two"

  Scenario: Search matches name tag classify path case insensitively and supports OR
    Given an isolated topsailai-data store
    When I create object "NameMatch" from fixture "markdown/valid.md" with description "Name" and tags "specialtag" and classify "search/alpha"
    Then the command succeeds
    When I create object "tag-match" from fixture "markdown/alternate.md" with description "Tag" and tags "NeedleTag" and classify "search/beta"
    Then the command succeeds
    When I create object "path-match" from fixture "markdown/valid.md" with description "Path" and tags "other" and classify "UniqueClassify"
    Then the command succeeds
    When I run topsailai-data with arguments:
      | search |
      | namematch |
      | --format |
      | json |
    Then the command succeeds
    And the JSON search result contains exactly IDs "NameMatch"
    When I run topsailai-data with arguments:
      | search |
      | needletag |
      | --format |
      | yaml |
    Then the command succeeds
    And the YAML search result contains exactly IDs "tag-match"
    When I run topsailai-data with arguments:
      | search |
      | uniqueclassify |
      | --format |
      | json |
    Then the command succeeds
    And the JSON search result contains exactly IDs "path-match"
    When I run topsailai-data with arguments:
      | search |
      | namematch\|needletag |
      | --format |
      | json |
    Then the command succeeds
    And the JSON search result contains exactly IDs "NameMatch,tag-match"

  Scenario Outline: Search rejects unsupported query syntax
    Given an isolated topsailai-data store
    When I run topsailai-data with arguments:
      | search |
      | <query> |
    Then the command fails with "<error>"

    Examples:
      | query | error |
      | foo bar | spaces or tabs |
      | foo	bar | spaces or tabs |
      | foo\\bar | backslash escapes |
      | foo\| | empty term |
      | \|foo | empty term |
      | foo\|\|bar | empty term |

  Scenario: Default list and search hide deleted objects while include deleted exposes them
    Given an isolated topsailai-data store
    When I create object "hidden-deleted" from fixture "markdown/valid.md" with description "Deleted" and tags "hidden"
    Then the command succeeds
    When I delete object "hidden-deleted" once times
    Then the command succeeds
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | json |
    Then the command succeeds
    And the JSON list has exactly IDs ""
    When I run topsailai-data with arguments:
      | search |
      | hidden |
      | --format |
      | json |
    Then the command succeeds
    And the JSON search result has exactly IDs ""
    When I run topsailai-data with arguments:
      | list |
      | --include-deleted |
      | --format |
      | json |
    Then the command succeeds
    And the JSON list has exactly IDs "hidden-deleted"
    When I run topsailai-data with arguments:
      | search |
      | hidden |
      | --include-deleted |
      | --format |
      | json |
    Then the command succeeds
    And the JSON search result has exactly IDs "hidden-deleted"

  Scenario: List rejects invalid output options
    Given an isolated topsailai-data store
    When I run topsailai-data with arguments:
      | list |
      | --format |
      | xml |
    Then the command fails with "unsupported format"
    When I run topsailai-data with arguments:
      | list |
      | --sort |
      | invalid |
    Then the command fails with "unsupported sort"

  Scenario: Search rejects invalid output options
    Given an isolated topsailai-data store
    When I run topsailai-data with arguments:
      | search |
      | query |
      | --format |
      | xml |
    Then the command fails with "unsupported format"
    When I run topsailai-data with arguments:
      | search |
      | query |
      | --sort |
      | invalid |
    Then the command fails with "unsupported sort"
