Feature: command recovery across Endpoint failures

  Scenario: endpoint crash before invocation is recovered and executed once
    Given a real cluster is started for recovery before invocation crash
    When a real command is submitted before invocation crash
    Then the recovered command eventually finishes from accepted journal with one provider invocation

  Scenario: invocation started crash remains unknown without replay
    Given a real cluster is started for invocation recovery
    When the crashed command reaches unknown certainty before endpoint restart
    Then restarting the endpoint preserves unknown certainty without a second invocation

  Scenario: lost receipt acknowledgement converges without reexecution
    Given a real cluster is started with receipt acknowledgements dropped
    When a real command is submitted and its receipt converges after acknowledgement loss
    Then the provider invocation count remains one

  Scenario: endpoint restart does not replay an executed command
    Given a real cluster with a healthy provider
    When a real command finishes before the endpoint is restarted
    Then restarting the endpoint preserves the finished command without replay
