"""Generate the MCP tools reference page (``site/index.html``) from the live
FastMCP server — no hand-written docs. The tool names, parameters, types, and
descriptions all come from the function signatures + docstrings via
``mcp.list_tools()``, so the page never drifts from the code.

Run with the offline layers so importing the server is fast and side-effect-free::

    POLYMNEMO_EMBED_BACKEND=stub POLYMNEMO_AUTH_BACKEND=static \
        python scripts/gen_tools_page.py
"""

from __future__ import annotations

import asyncio
import html
import re
from datetime import UTC, datetime
from pathlib import Path

from polymnemo import __version__
from polymnemo.server import mcp

SITE = Path("site")

# Grouping + display order; anything unlisted lands in "Other".
CATEGORIES: list[tuple[str, list[str]]] = [
    ("Health", ["ping"]),
    (
        "Memory",
        ["remember", "recall", "list_memories", "get_memory", "update", "forget"],
    ),
    ("Sessions", ["save_session", "load_session"]),
    ("Media", ["create_upload", "confirm_upload", "get_download_url"]),
]


def _type(prop: dict) -> str:
    if "anyOf" in prop:
        types = [s.get("type") for s in prop["anyOf"]]
        named = [t for t in types if t and t != "null"]
        base = " | ".join(named) or "any"
        return base + ("?" if "null" in types else "")
    return prop.get("type", "any")


def _desc(text: str | None) -> str:
    """Escape a docstring to HTML: `code` spans + paragraphs."""
    out = []
    for para in (text or "").strip().split("\n\n"):
        esc = re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(para.strip()))
        out.append(f"<p>{esc.replace(chr(10), ' ')}</p>")
    return "".join(out)


def _badges(ann: object) -> str:
    flags = [
        ("read-only", getattr(ann, "read_only_hint", None)),
        ("destructive", getattr(ann, "destructive_hint", None)),
        ("idempotent", getattr(ann, "idempotent_hint", None)),
    ]
    return "".join(
        f'<span class="badge {name}">{name}</span>' for name, on in flags if on
    )


def _row(name: str, prop: dict, required: set[str]) -> str:
    d = prop.get("default")
    default = "—" if d is None else html.escape(repr(d))
    req = "yes" if name in required else "—"
    return (
        f"<tr><td><code>{html.escape(name)}</code></td>"
        f"<td>{html.escape(_type(prop))}</td><td>{req}</td><td>{default}</td></tr>"
    )


def _card(tool: object) -> str:
    schema = getattr(tool, "parameters", None) or {}
    props: dict = schema.get("properties", {})
    required = set(schema.get("required", []))
    sig_params = ", ".join(p + ("" if p in required else "?") for p in props)
    rows = "".join(_row(p, s, required) for p, s in props.items())
    table = (
        "<table><thead><tr><th>param</th><th>type</th><th>required</th>"
        f"<th>default</th></tr></thead><tbody>{rows}</tbody></table>"
        if props
        else "<p class='none'>No parameters.</p>"
    )
    return (
        f'<section id="{tool.name}" class="tool">'
        f"<h3><code>{tool.name}({html.escape(sig_params)})</code>"
        f"{_badges(getattr(tool, 'annotations', None))}</h3>"
        f"{_desc(tool.description)}{table}</section>"
    )


async def build() -> None:
    tools = {t.name: t for t in await mcp.list_tools()}
    listed = {n for _, names in CATEGORIES for n in names}
    groups = [*CATEGORIES, ("Other", [n for n in tools if n not in listed])]

    nav, body = [], []
    for title, names in groups:
        names = [n for n in names if n in tools]
        if not names:
            continue
        links = " · ".join(f'<a href="#{n}">{n}</a>' for n in names)
        nav.append(f"<div class='navgroup'><b>{title}</b> {links}</div>")
        cards = "".join(_card(tools[n]) for n in names)
        body.append(f"<h2>{title}</h2>{cards}")

    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    page = _TEMPLATE.replace("__NAV__", "".join(nav))
    page = page.replace("__BODY__", "".join(body))
    page = page.replace("__META__", f"v{__version__} · generated {generated}")
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(page)
    print(f"wrote {SITE / 'index.html'} ({len(tools)} tools)")


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>polymnemo — MCP tools</title>
<style>
  :root{color-scheme:light dark;--fg:#1a1a1a;--muted:#666;--card:#fff;--line:#e5e5e5;
        --bg:#fafafa;--code:#f2f2f2;--accent:#1565c0}
  @media(prefers-color-scheme:dark){:root{--fg:#e8e8e8;--muted:#9a9a9a;--card:#1c1c1c;
        --line:#333;--bg:#111;--code:#242424;--accent:#68a8ff}}
  *{box-sizing:border-box}
  body{margin:0;padding:2rem 1rem;background:var(--bg);color:var(--fg);
       font:16px/1.6 system-ui,-apple-system,sans-serif}
  .wrap{max-width:820px;margin:0 auto}
  h1{font-size:1.5rem;margin:0 0 .2rem}
  .meta{color:var(--muted);font-size:.85rem;margin-bottom:1.5rem}
  .nav{background:var(--card);border:1px solid var(--line);border-radius:12px;
       padding:1rem;margin-bottom:2rem;font-size:.9rem}
  .navgroup{margin:.25rem 0}
  .nav a{color:var(--accent);text-decoration:none}
  h2{font-size:1.15rem;margin:2rem 0 .75rem;border-bottom:1px solid var(--line);
     padding-bottom:.3rem}
  .tool{background:var(--card);border:1px solid var(--line);border-radius:12px;
        padding:1rem 1.25rem;margin:.75rem 0}
  .tool h3{margin:0 0 .5rem;font-size:1rem}
  code{background:var(--code);padding:.1em .35em;border-radius:4px;
       font:.9em ui-monospace,monospace}
  .tool h3 code{background:none;padding:0}
  p{margin:.5rem 0}.none{color:var(--muted)}
  table{border-collapse:collapse;width:100%;margin-top:.5rem;font-size:.9rem}
  th,td{text-align:left;padding:.35rem .5rem;border-bottom:1px solid var(--line)}
  th{color:var(--muted);font-weight:500}
  .badge{font-size:.7rem;font-weight:500;padding:.1em .5em;border-radius:99px;
         margin-left:.5rem;vertical-align:middle}
  .badge.read-only{background:#e6f1fb;color:#0c447c}
  .badge.destructive{background:#fcebeb;color:#791f1f}
  .badge.idempotent{background:#e1f5ee;color:#085041}
  a.repo{display:inline-block;margin-top:1.5rem;color:var(--accent);
         text-decoration:none;font-size:.9rem}
</style></head><body><div class="wrap">
<h1>polymnemo — MCP tools</h1>
<div class="meta">__META__ · auto-generated from the server</div>
<div class="nav">__NAV__</div>
__BODY__
<a class="repo" href="https://github.com/PCBZ/polymnemo">PCBZ/polymnemo &rarr;</a>
</div></body></html>
"""


if __name__ == "__main__":
    asyncio.run(build())
