# gitleaks plugin

Vendored from [PCBZ/rsp](https://github.com/PCBZ/rsp) `examples/gitleaks-py`
at **v0.1.1**, unmodified except for the provenance header on each file.

## Why vendored

The published `rag-security-protocol` distribution ships the host library only;
the example plugins are not part of it. So the choice was to copy this or to
rewrite it, and rewriting would mean redoing the offset mapping in
`gitleaks.py` — which is the subtle part. gitleaks counts a finding's columns
from the newline byte ending the *previous* line, not from the line's own
first byte, and a span that does not slice `Match` back out of the content is
dropped and turned into a BLOCK rather than a wrong redaction. That logic is
specified and tested upstream; reimplementing it is how a scanner silently
redacts the wrong bytes.

## Licensing

`rsp` is Apache-2.0 and polymnemo is MIT. These four files stay under
Apache-2.0; the header on each says so. Both repositories are PCBZ's.

## Keeping it current

Nothing here updates automatically. When `rsp` changes its gitleaks example,
this copy does not, so re-vendor deliberately rather than assuming parity.
