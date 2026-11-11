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

  Scenario: an allowed command execution reaches the provider once
    Given a real cluster that publishes a live and a stopped session
    And a credential permitted to execute a command
    When the command exec operation is submitted with an allowlisted argv and that credential
    Then the command is accepted and the provider is invoked once

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
