---
maintainer: AI
---
# Adapter omits runtime control handler

Confirmed during live tmux testing: execution.interrupt invoked `topsailai runtime control` without the required handler positional argument, while help advertised the unsupported payload action `interrupt`. The provider therefore could not route the request to a real interrupt handler. Resolved by accepting only explicit `soft_interrupt` or `hard_interrupt` envelopes, placing that action in the provider argv, validating handler arguments, updating help, and covering exact argv plus rejection paths.
