"""
Session Agent Driver plugin tools package.

This package is loaded by the TopsailAI plugin-tool mechanism through the
``TOPSAILAI_PLUGIN_TOOLS`` environment variable (value: ``plugins.tools``).
Each submodule exposes a ``TOOLS`` dict (tool name -> callable) and a
``TOOLS_INFO`` dict (tool name -> JSON schema) so the analysis agent can
discover and call the tools with correct argument schemas.

Tools provided:
- inject_input: inject suggested input content into the target session.
- exit_process: request the driver script to exit its polling loop.
"""
