"""RSP scanner plugins that are ours.

A plugin is a command, spawned per chunk, so each is a module with a `main`
and is run as `python -m polymnemo.plugins.<name>`. They live under the package
rather than beside it so they share `_runner` and `_strictjson` instead of
carrying a copy each -- the upstream examples duplicate because they are in
seven languages and cannot share anything; ours are all Python and can.

Importing `polymnemo` costs 1.3 ms (the package `__init__` is a docstring and a
version string), so the module form adds nothing measurable to a spawn.

The vendored gitleaks plugin in `plugins/gitleaks/` does NOT take part. It is a
verbatim copy so a re-vendor diffs against upstream; refactoring it to import
from here would fork it, which is the thing vendoring exists to avoid.
"""
