Feature: endpoint command authorization
  Every command the cluster can send is authorized by the Endpoint that would
  perform it, not by the Server that routes it. The Server verifies the caller and
  forwards the request unchanged; the Endpoint decides whether the caller may
  exercise the operation on that machine.

  These scenarios exist because a refusal is easy to fake. The Endpoint refuses a
  command for many reasons before it ever consults the policy: an unknown target,
  an unadvertised capability, a mismatched profile revision, a live target where a
  resume was requested, or a missing generation. Each of those refusals also
  reaches the provider zero times, so a scenario that only asserts "refused and no
  provider call" would pass while proving nothing about authorization. Every
  scenario below is therefore built so the policy is the only remaining reason to
  refuse, and every allowed scenario asserts the provider was reached exactly once.

  Scenario: an allowed message reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to send a message
    When the message send command is submitted with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: a message without the send permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the message send command is submitted with that credential
    Then the command is refused with policy denied and the provider is not invoked

  Scenario: an allowed context injection reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to inject context
    When the context inject command is submitted with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: a context injection without the send permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the context inject command is submitted with that credential
    Then the command is refused with policy denied and the provider is not invoked

  Scenario: an allowed interrupt reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to interrupt execution
    When the execution interrupt command is submitted with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: an interrupt without the control permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the execution interrupt command is submitted with that credential
    Then the command is refused with policy denied and the provider is not invoked

  Scenario: an allowed stop reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to stop an agent
    When the agent stop command is submitted with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: a stop without the control permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the agent stop command is submitted with that credential
    Then the command is refused with policy denied and the provider is not invoked

  Scenario: an allowed workspace cleanup reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to clean a workspace
    When the workspace clean command is submitted with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: a workspace cleanup without the control permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the workspace clean command is submitted with that credential
    Then the command is refused with policy denied and the provider is not invoked

  Scenario: an allowed drive start reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to start a drive
    When the agent drive start command is submitted with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: a drive start without the control permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the agent drive start command is submitted with that credential
    Then the command is refused with policy denied and the provider is not invoked

  Scenario: an allowed drive stop reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to stop a drive
    When the agent drive stop command is submitted with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: a drive stop without the control permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the agent drive stop command is submitted with that credential
    Then the command is refused with policy denied and the provider is not invoked

  Scenario: an allowed resume reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to resume an agent
    When the agent resume command is submitted against the stopped session with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: a resume without the control permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the agent resume command is submitted against the stopped session with that credential
    Then the command is refused with policy denied and the provider is not invoked

  Scenario: an allowed start reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to start an agent
    When the agent start command is submitted with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: a start without the control permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the agent start command is submitted with that credential
    Then the command is refused with policy denied and the provider is not invoked

  Scenario: an allowed model selection reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to select a model
    When the agent model select command is submitted with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: a model selection without the control permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the agent model select command is submitted with that credential
    Then the command is refused with policy denied and the provider is not invoked

  # command.exec is Endpoint-native by contract: the Endpoint keeps the allowlist,
  # the working directory, the confinement, the minimal environment, the timeout
  # and the exact-process cleanup, and it does not start the provider CLI for this
  # operation. So the positive row asserts that the Endpoint ran the command and
  # that the provider was not consulted, which is the opposite of every other row.
  Scenario: an allowed command execution runs on the endpoint
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to execute a command
    When the command exec operation is submitted with an allowlisted argv and that credential
    Then the command is accepted and the endpoint ran it without the provider

  Scenario: a command execution without the control permission is refused before the allowlist
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the command exec operation is submitted with an allowlisted argv and that credential
    Then the command is refused with policy denied and the provider is not invoked

  # The provider control family is a separate cluster because the catalog reaches
  # only the TopsailAI adapter: the generic fixture adapter is constructed without
  # one, so a ctl. operation there would be refused as unsupported before the
  # policy hook ran and the scenario would prove nothing about authorization.
  #
  # The catalog entry is real, so the positive scenario proves the whole path from
  # the advertised capability through the policy hook to a provider argv. The
  # negative scenario therefore cannot be satisfied by an unconfigured action, an
  # unadvertised capability or a missing adapter: all three are present.

  Scenario: an allowed control action reaches the provider once
    Given a real cluster that publishes a control action catalog
    And a credential permitted to invoke the fixture control action
    When the fixture control action is submitted with that credential
    Then the control action is accepted and the provider is invoked once

  Scenario: a control action without its permission is refused before the provider
    Given a real cluster that publishes a control action catalog
    And a credential permitted only to view the control action
    When the fixture control action is submitted with that credential
    Then the control action is refused with policy denied and the provider is not invoked

  # Remote project registration is a mutating control operation, so it needs the
  # same two-sided proof as every other row: an allowed call that reaches the
  # provider once, and a refused call that never reaches it.
  #
  # The matrix cluster configures AGENT_CLUSTER_ENDPOINT_PROJECT_ROOT. Without it
  # the positive row would fail closed with project_root_unconfigured before the
  # policy hook ran, so the scenario would prove a configuration refusal instead
  # of authorization. The folder submitted by the positive row is read from the
  # live catalog, so it is a real directory inside that configured root.
  #
  # Removal addresses the opaque project ID and carries the exact provider path in
  # the opaque target slot, because the Endpoint mapping key is a digest and cannot
  # be reversed. Both rows therefore prove the whole path from the advertised
  # capability through the policy hook to a provider argv.

  Scenario: an allowed project registration reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to register a project
    When the project add command is submitted with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: a project registration without the control permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the project add command is submitted with that credential
    Then the command is refused with policy denied and the provider is not invoked

  Scenario: an allowed project removal reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to remove a project
    When the project remove command is submitted with that credential
    Then the command is accepted and the provider is invoked once

  Scenario: a project removal without the control permission is refused before the provider
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted only to view
    When the project remove command is submitted with that credential
    Then the command is refused with policy denied and the provider is not invoked
