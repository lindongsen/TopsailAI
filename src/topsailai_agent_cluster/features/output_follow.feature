Feature: output follow
  The follow surface streams provider output records until the operator stops it.
  Both surfaces are covered here because they stop differently: the interactive
  REPL is stopped by any keypress through the watch seam, while the standalone
  command has no terminal and is stopped by an interrupt.

  Scenario: interactive follow streams records until a keypress stops it
    Given a real cluster with a streaming provider for the TUI
    When the interactive REPL runs logs follow in a real terminal
    Then the follow stream reports its target and mode
    And the streamed records arrive while the editor waits
    And the first keypress stops the follow stream

  Scenario: standalone follow streams records until an interrupt stops it
    Given a real cluster with a streaming provider for the TUI
    When the standalone logs follow command runs until it is interrupted
    Then the streamed records arrive before the interrupt
    And the interrupt ends the stream cleanly

  Scenario: any key stops the interactive follow stream
    Given a real cluster with a streaming provider for the TUI
    When the interactive REPL runs logs follow and the operator presses enter
    Then the streamed records arrive while the editor waits
    And the enter key stops the follow stream

  Scenario: a disconnect interrupts the stream instead of finishing it
    The Endpoint never delivers its terminal frame when the channel is already
    gone, so the Server releases the pending follow with its own inferred code.
    This scenario proves the client reports that interruption rather than
    presenting a truncated stream as a finished one.
    Given a real cluster with a streaming provider for the TUI
    When the standalone logs follow command runs while the endpoint disconnects
    Then the disconnect is reported as an interrupted stream

  Scenario: an expired follow budget is reported as a timeout, not a cancellation
    A follow is bounded by its own budget, which is separate from the one-shot
    call timeout. When that budget expires nobody stopped the stream, so the
    operator must be told the stream timed out. Reporting a cancellation here
    sent the operator looking for whoever stopped it while nobody had.
    Given a real cluster whose follow budget is shorter than the provider hold
    When the standalone logs follow command runs until its own budget expires
    Then the stream reports that its budget expired

  Scenario: the keypress releases the provider follow child
    A keypress must release the provider process, not only stop the drawing. The
    provider records the pid of its follow child before it starts streaming, so
    the pid is evidence that a child existed; the assertion then proves that pid
    is gone after the keypress. Without this the teardown chain rested on source
    tracing alone, and a regression that stopped cancelling the stream context
    would leave the child running while every other follow scenario still passed.
    Given a real cluster whose provider holds the follow stream past the keypress
    When the interactive REPL runs logs follow and the provider child is recorded
    Then the keypress releases the provider follow child
