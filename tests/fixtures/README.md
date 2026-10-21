# Fixtures

## `gitleaks-offsets.json`

Vendored from [PCBZ/rsp](https://github.com/PCBZ/rsp) `examples/gitleaks-offsets.json`.
Line-and-column positions as gitleaks reports them, with the byte offsets the
RSP spec requires, **transcribed from what the binary emitted** rather than
worked out by hand.

That distinction is the point. From the file's own note:

> a number invented here would agree with whatever the code assumes, which is
> how an end offset was once wrong for every finding spanning two lines

Which is exactly what happened writing `fake_gitleaks.py`: its column formula
special-cased line one and was wrong everywhere else, and only a lint warning
on the dead half of the conditional exposed it.

The secrets in it are gitleaks' own documented test values, not real
credentials. Real leaked secrets are deliberately **not** used here — a public
repository is the last place they belong, and `remember` exists to keep them
out of a database, never mind a fixture.
