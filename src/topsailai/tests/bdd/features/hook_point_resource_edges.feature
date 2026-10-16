@bdd
Feature: Resource selection boundaries and native input behavior
  Scenario Outline: Explicit external <group> selection as <form>
    Given external selection <group> uses <form>
    When the business invokes the public named Hook Point
    Then exact resource evidence and ordered results match the declaration

    Examples:
      | group | form |
      | ME | file |
      | ME | single_list |
      | ME | files |
      | ME | folders |
      | ME | mixed |
      | SE | file |
      | SE | single_list |
      | SE | files |
      | SE | folders |
      | SE | mixed |

  Scenario Outline: Public resource boundary <case>
    Given boundary fixture <case>
    When the business invokes the public named Hook Point
    Then exact resource evidence and ordered results match the declaration

    Examples:
      | case |
      | duplicate-ME-internal |
      | duplicate-ME-external |
      | duplicate-SE-internal |
      | duplicate-SE-external |
      | cross_kind |
      | permission-SI |
      | permission-SE |
      | missing-modules |
      | missing-scripts |
      | empty_dirs |
      | unset |
      | direct-ME |
      | direct-SE |
      | config-json |
      | config-relative |
      | config-unknown |
      | failure-module |
      | failure-script |
      | failure-format |
      | snapshot |
      | membership |
      | input_single |
      | input_multi |
      | timeout-ME |
      | timeout-SE |
      | descendant |
