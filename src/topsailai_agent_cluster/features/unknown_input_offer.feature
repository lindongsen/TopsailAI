Feature: session scope unknown input offers send

  In session scope the common mistake is typing a message without the command
  word. Such a line is offered as a send instead of only being rejected, so the
  operator does not have to retype the text. The offer is a question, not a
  capability claim, and a refusal keeps the original diagnostic.

  Scenario: accepting the offer sends the literal line
    Given a real cluster with a healthy provider for the interactive REPL
    When unrecognized session input is offered as a send and accepted
    Then the offer names the whole literal line
    And exactly one send command is admitted
    And the offer does not repeat the send confirmation

  Scenario: declining the offer keeps the unknown command diagnostic
    Given a real cluster with a healthy provider for the interactive REPL
    When unrecognized session input is offered as a send and declined
    Then the unknown command diagnostic is reported
    And no send command is admitted

  Scenario: workspace scope keeps the plain diagnostic
    Given a real cluster with a healthy provider for the interactive REPL
    When unrecognized workspace input is entered
    Then the unknown command diagnostic is reported
    And no send offer is shown
