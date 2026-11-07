---
maintainer: AI
author: DawsonLin
---
# Terminal editor integration safety

During prompt-gated editor implementation, staged review found child confirmation paths could convert reader errors into ordinary cancellation, and a generic answer prompt hid the start field name. Preserve exact child reader failures at the REPL boundary; propagate explicit field labels to the callback. Verify fatal read errors cause no admissions and Ctrl-C recovers from the wizard, while main prompt exits130. Resolved by full module, race, vet and four real tmux exit/restoration scenarios.

Real tmux found Escape timeout did not fire: os.File.Fd was called after successful deadline registration, switching the descriptor back to blocking. Capturing fd earlier was insufficient. Keep the original stdin fd for terminal mode operations and use a separately opened deadline reader whose Fd method is never called. Fake deadline inputs did not model this Go runtime side effect; retain actual PTY Escape and external signal regressions.

Final full regression caught parent cancellation check overriding existing fatal writer priority in stream mode. Restrict new callback-specific cancellation check to callback mode; retain C16 matrix unchanged as the regression oracle.
