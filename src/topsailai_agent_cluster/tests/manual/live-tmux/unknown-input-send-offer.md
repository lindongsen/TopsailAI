---
maintainer: AI
author: DawsonLin
---

# Session-scope unknown-input send offer

This module verifies the session-scope behaviour where text that matches no command is offered as a `send` message. It is an operator acceptance procedure driven through the real `agent-cluster-cli` binary in tmux, not a unit-test claim.

## OFFER-01 Offer appears in session scope

Precondition: the CLI is in session scope with a fresh selected session whose adapter advertises `message.send`.

Type `hello world` then Enter. Expect the message on its own row, carrying only the payload and coloured differently from the question, followed by the question row `>>> send the text above as a message? [y/N]`. Expect the cursor to wait after the answer hint on that question row, and expect no separate `answer>` prompt. Expect no `unknown command hello;` prefix on the offer. Expect no command admission before the answer, and expect the prompt to return after the answer.

## OFFER-02 Accepting the offer sends the literal line

Precondition: same as OFFER-01.

Type `hello world` then Enter, then `y` then Enter. Expect exactly one admitted `message.send` command whose payload text is the whole literal line `hello world`, including its first word. Expect the send confirmation question to appear exactly once in total, so the offer does not ask the same question twice. Expect the durable command receipt to be rendered, and expect the receipt to show delivery evidence rather than task completion.

## OFFER-03 Declining keeps the unknown-command diagnostic

Precondition: same as OFFER-01.

Type `hello world` then Enter, then `n` then Enter. Expect the original diagnostic `unknown command "hello" (try help)` and expect no command admission. Repeat with an empty answer and expect the same diagnostic.

## OFFER-04 Other scopes keep the plain diagnostic

Precondition: workspace scope, then endpoint scope.

Type `hello world` then Enter in each scope. Expect the plain `unknown command "hello" (try help)` diagnostic, no question, and no command admission, because `send` is unavailable outside session scope.

## OFFER-05 Help documents the offer

Precondition: session scope.

Type `help` then Enter. Expect the session-scope `send` description to mention that unrecognized text offers the action, and expect the session workflow block to state that declining keeps the unknown-command diagnostic.

## OFFER-06 A bare number is message text, not navigation

Precondition: same as OFFER-01.

Type `1` then Enter. Expect the same offer as OFFER-01, with the message row showing the literal text `1`, and expect no `row-number navigation is unavailable in session scope` diagnostic. Type `y` then Enter and expect exactly one admitted `message.send` whose payload text is `1`. Repeat with `01` and with `1 foo`, and expect the whole literal line to be the payload in each case, because session scope has no row table to navigate and the shorthand's surplus rule belongs to navigation.

Then type `cd 1` then Enter. Expect the diagnostic `row-number navigation is unavailable in session scope; use cd .. or cd <session>` and expect no command admission, because the explicit command word still reaches the row-number rule.

## Evidence

Record case ID, exact keystrokes, captured output, admitted command ID, payload text, elapsed time and the tmux target under workspace `.tmp/live-tmux-audit/`. Stop only the tmux session and service processes created by this run.
