Feature: Selecting a model profile for a session
  A session runs on one model profile, and an operator needs to see which profiles
  exist and move the session onto a different one. The catalog is a live provider
  query, so it is read on demand instead of being stored in the inventory.

  The operator selects a row by the number the table printed. That number is a
  position in a client-side rendering, so it never travels to the provider: the
  client resolves it against the catalog it last showed and sends the profile
  identity instead. A renumbered catalog therefore cannot change which profile a
  request addresses.

  Scenario: A session-scope model command lists the catalog and applies a row
    Given a real cluster with a healthy provider for the model catalog
    When the model command is run in session scope
    Then the model catalog is rendered with numbered rows
    When the second model row is applied in session scope
    Then the provider receives the second profile name and no row number

  Scenario: A workspace-scope model command applies to a named session
    Given a real cluster with a healthy provider for the model catalog
    When the model command is run in workspace scope for the fixture session
    Then the model catalog is rendered with numbered rows
    When the first model row is applied in workspace scope
    Then the provider receives the first profile name

  Scenario: A view-only credential can list the catalog but cannot select
    Given a real cluster whose credential may only view and whose provider answers the model catalog
    When the model command is run in workspace scope for the fixture session
    Then the model catalog is rendered with numbered rows
    When the first model row is applied in workspace scope
    Then the model change is refused for lack of control permission
