---
maintainer: AI
---
# TAB exits interactive CLI

Confirmed in real tmux: pressing TAB at workspace prompt returns unsupported or malformed terminal key and exits to shell. The decoder lacks TAB support. Fix: decode TAB and handle bounded scope command completion without submitting input. Resolved: focused and full TUI/CLI tests, vet, and real tmux verification passed. TAB no longer exits; canonical scope command names complete without submitting actions.
