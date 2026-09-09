"""Build a static test/coverage dashboard (``site/index.html``) for GitHub Pages.

Reads the reports produced by::

    pytest --cov=polymnemo --cov-report=html --cov-report=json --junitxml=pytest.xml

- ``coverage.json`` — total + per-file coverage
- ``pytest.xml`` — passed / failed / errors / skipped counts

and writes a small Chart.js page. The workflow copies ``htmlcov/`` into
``site/htmlcov`` so the page can link to the full report. Run locally the same
way to preview ``site/index.html``.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

SITE = Path("site")


def _test_counts(path: str = "pytest.xml") -> dict[str, int]:
    root = ET.fromstring(Path(path).read_text())
    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        return {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    total = int(suite.get("tests", "0"))
    failed = int(suite.get("failures", "0"))
    errors = int(suite.get("errors", "0"))
    skipped = int(suite.get("skipped", "0"))
    return {
        "passed": total - failed - errors - skipped,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
    }


def _coverage(path: str = "coverage.json") -> tuple[float, list[dict]]:
    data = json.loads(Path(path).read_text())
    total = round(data["totals"]["percent_covered"], 1)
    files = [
        {
            "file": name.removeprefix("src/polymnemo/"),
            "pct": round(info["summary"]["percent_covered"], 1),
        }
        for name, info in data["files"].items()
    ]
    files.sort(key=lambda f: f["pct"])  # lowest first — what needs attention
    return total, files


def build() -> None:
    payload = {
        "counts": _test_counts(),
        "coverage": None,
        "files": [],
        "generated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
    payload["coverage"], payload["files"] = _coverage()

    SITE.mkdir(exist_ok=True)
    html = _TEMPLATE.replace("__DATA__", json.dumps(payload))
    (SITE / "index.html").write_text(html)


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>polymnemo — tests & coverage</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root { color-scheme: light dark; --fg:#1a1a1a; --muted:#666; --card:#fff;
          --line:#e5e5e5; --bg:#fafafa; }
  @media (prefers-color-scheme: dark) {
    :root { --fg:#e8e8e8; --muted:#9a9a9a; --card:#1c1c1c; --line:#333; --bg:#111; }
  }
  * { box-sizing: border-box; }
  body { margin:0; padding:2rem 1rem; background:var(--bg); color:var(--fg);
         font:16px/1.5 system-ui, -apple-system, sans-serif; }
  .wrap { max-width: 860px; margin: 0 auto; }
  h1 { font-size: 1.4rem; font-weight: 600; margin: 0 0 .25rem; }
  .sub { color: var(--muted); font-size: .85rem; margin-bottom: 1.5rem; }
  .tiles { display:grid; grid-template-columns: repeat(4, 1fr); gap:.75rem;
           margin-bottom:1.5rem; }
  .tile { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:1rem; text-align:center; }
  .tile .n { font-size:1.9rem; font-weight:600; }
  .tile .l { color:var(--muted); font-size:.8rem; text-transform:uppercase;
             letter-spacing:.04em; }
  .green .n{color:#2e7d32} .red .n{color:#c62828} .gray .n{color:#757575}
  .blue .n{color:#1565c0}
  .cards { display:grid; grid-template-columns: 1fr 1fr; gap:1rem; }
  @media (max-width:640px){ .cards,.tiles{grid-template-columns:1fr 1fr} }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:1rem; }
  .card h2 { font-size:.95rem; font-weight:600; margin:0 0 .75rem; }
  a.report { display:inline-block; margin-top:1.25rem; color:#1565c0;
             text-decoration:none; font-size:.9rem; }
  a.report:hover { text-decoration:underline; }
</style>
</head>
<body>
<div class="wrap">
  <h1>polymnemo — tests &amp; coverage</h1>
  <div class="sub" id="sub"></div>
  <div class="tiles" id="tiles"></div>
  <div class="cards">
    <div class="card"><h2>Test outcomes</h2><canvas id="outcomes"></canvas></div>
    <div class="card"><h2>Coverage by file</h2><canvas id="files"></canvas></div>
  </div>
  <a class="report" href="htmlcov/index.html">Full coverage report &rarr;</a>
</div>
<script>
const D = __DATA__;
const c = D.counts;
document.getElementById("sub").textContent = "Generated " + D.generated;
const tiles = [
  ["green","Passed",c.passed],["red","Failed",c.failed],
  ["gray","Skipped",c.skipped],["blue","Coverage",D.coverage + "%"],
];
document.getElementById("tiles").innerHTML = tiles.map(
  ([cls,l,n]) => `<div class="tile ${cls}"><div class="n">${n}</div><div class="l">${l}</div></div>`
).join("");

new Chart(document.getElementById("outcomes"), {
  type: "doughnut",
  data: { labels:["Passed","Failed","Errors","Skipped"],
    datasets:[{ data:[c.passed,c.failed,c.errors,c.skipped],
      backgroundColor:["#4caf50","#e53935","#fb8c00","#bdbdbd"] }] },
  options:{ plugins:{ legend:{ position:"bottom" } } }
});

new Chart(document.getElementById("files"), {
  type: "bar",
  data: { labels: D.files.map(f=>f.file),
    datasets:[{ label:"% covered", data:D.files.map(f=>f.pct),
      backgroundColor: D.files.map(f=> f.pct>=80?"#4caf50":f.pct>=50?"#fb8c00":"#e53935") }] },
  options:{ indexAxis:"y", plugins:{ legend:{ display:false } },
    scales:{ x:{ min:0, max:100 } } }
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
