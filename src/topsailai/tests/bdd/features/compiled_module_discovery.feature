@bdd
Feature: Compiled modules remain discoverable in packaged TopsailAI
  Registries and hooks must use import-system discovery so packaged Cython
  extension artifacts can replace their source modules.

  Scenario: Source discovery exposes the expected registries and hooks
    Given a source TopsailAI tree using import-system module discovery
    When source module discovery enumerates the representative registries and hooks
    Then source discovery exposes the expected modules and control actions

  @packaged
  Scenario: Compiled control handlers expose the same actions as source handlers
    Given a packaged TopsailAI tree containing compiled control-handler modules without sibling source modules
    When control handlers are registered from the source and packaged trees
    Then both trees expose the same control-handler action set
    And the packaged tree exposes every expected send-control action
    And the packaged control-handler modules originate from the packaged tree

  @packaged
  Scenario Outline: Compiled mistake hooks handle malformed DeepSeek responses
    Given a packaged TopsailAI tree containing compiled mistake hooks without sibling source modules
    When the packaged hook runner processes the DeepSeek response fixture "<fixture>"
    Then both expected compiled wrapper hooks are discovered in stable order
    And the expected corrective action is returned

    Examples:
      | fixture    |
      | dsml-3.txt |
      | dsml-4.txt |

  @packaged
  Scenario Outline: Shared package discovery includes compiled extension modules
    Given the packaged TopsailAI package "<package>" contains extension modules without sibling source modules
    When shared module discovery enumerates that package
    Then every expected compiled module for "<package>" is returned
    And every discovered module originates from the packaged tree

    Examples:
      | package                                  |
      | topsailai.tools                          |
      | topsailai.workspace.plugin_instruction   |
      | topsailai.workspace.agent.hooks          |
      | topsailai.context.chat_history_manager   |

  Scenario: A compiled-only nested external plugin package is resolved
    Given a nested external plugin package whose package initializers and plugin modules are extension artifacts only
    When its external function map is loaded by filesystem path
    Then the nested package path is resolved through the Python import system
    And its declared plugin functions are discovered
