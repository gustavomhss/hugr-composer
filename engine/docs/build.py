"""Reference docs site generator — CONTRACT §B2.3.

Reads `primitives_by_concern.yaml` + every primitive `.md` + `.contract.json`
+ every tool's `MCP_TOOL` metadata, and writes a static HTML site into
`docs_site/`. Zero build dependencies — pure-Python, no Node, no mkdocs.

Properties enforced by tests:
  * **Idempotent** — same inputs produce byte-identical `docs_site/` (hash
    check in test). Commit-safe for CI.
  * **Complete** — every production primitive gets a page; every adapt tool
    gets a row on the tools index.
  * **Flat nav** — landing page → (primitive OR tool) page is ≤ 2 clicks.
  * **Client-side search** — `search.json` + inline JS; no backend.

Usage:

    PYTHONPATH=. python -m engine.docs.build              # writes docs_site/
    PYTHONPATH=. python -m engine.docs.build --out /tmp/site --verify
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SKILL_ROOT.parents[1]
REGISTRY_PATH = SKILL_ROOT / "engine" / "primitives_by_concern.yaml"
VENOUS_ROOT = SKILL_ROOT / "core" / "venous"
ADAPT_ROOT = SKILL_ROOT / "adapt"
DEFAULT_OUT = SKILL_ROOT / "docs_site"

# Top-level contract docs published at docs.hugr.dev root. Order matters —
# this is the nav order on the landing page.
_TOP_LEVEL_DOCS: tuple[tuple[str, str, str], ...] = (
    ("PRODUCT.md", "product", "Product contract"),
    ("ROADMAP.md", "roadmap", "Roadmap"),
    ("CONTRACT.md", "contract", "Execution contract"),
    ("CONTRIBUTING.md", "contributing", "Contributing"),
    ("CHANGELOG.md", "changelog", "Changelog"),
)

_SOURCE_URL_BASE = (
    "https://github.com/humangr-labs/HuGR-Arsenal/tree/main/skills/SKILL-001-fastapi-production"
)


@dataclass(frozen=True)
class ToolMeta:
    name: str
    description: str
    tags: tuple[str, ...]
    module_path: str


# ---------------------------------------------------------------------------
# Tiny Markdown → HTML converter.
#
# We do NOT depend on `python-markdown`; the primitive `.md` files use a
# narrow subset (headings, bullets, tables, inline code, fenced code, bold).
# This function handles exactly that subset and escapes everything else.
# Determinism matters more than feature coverage — the site hash must not
# jitter run-to-run.
# ---------------------------------------------------------------------------

_INLINE_CODE = re.compile(r"`([^`\n]+?)`")
_BOLD = re.compile(r"\*\*([^*\n]+?)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _render_inline(text: str) -> str:
    html.escape(text, quote=False)
    # Links BEFORE bold/code (bold with ** could capture `[x]`) — but we
    # escaped first, so brackets are now &#91; etc. Unescape just for link
    # matching on the original string and re-render:
    # Simpler: do inline on original, escape chunks independently.
    return _inline_rich(text)


def _inline_rich(text: str) -> str:
    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(text):
        m_link = _LINK.match(text, i)
        m_bold = _BOLD.match(text, i)
        m_code = _INLINE_CODE.match(text, i)
        # pick earliest match at current i
        best = None
        for kind, m in (("link", m_link), ("bold", m_bold), ("code", m_code)):
            if m is None:
                continue
            if best is None or m.start() < best[1].start():
                best = (kind, m)
        if best and best[1].start() == i:
            kind, m = best
            if kind == "link":
                label, href = m.group(1), m.group(2)
                tokens.append(
                    ("link", f'<a href="{html.escape(href, quote=True)}">{html.escape(label)}</a>')
                )
            elif kind == "bold":
                tokens.append(("bold", f"<strong>{html.escape(m.group(1))}</strong>"))
            else:
                tokens.append(("code", f"<code>{html.escape(m.group(1))}</code>"))
            i = m.end()
        else:
            # emit one literal char (escaped)
            tokens.append(("text", html.escape(text[i])))
            i += 1
    return "".join(tok[1] for tok in tokens)


def _md_to_html(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    in_code = False
    code_lang = ""
    code_buf: list[str] = []
    para_buf: list[str] = []
    in_list = False
    in_table = False
    table_rows: list[list[str]] = []

    def _flush_para() -> None:
        nonlocal para_buf
        if para_buf:
            out.append(f"<p>{_inline_rich(' '.join(para_buf))}</p>")
            para_buf = []

    def _flush_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def _flush_table() -> None:
        nonlocal in_table, table_rows
        if not in_table:
            return
        # first row is header, second row is "| --- |..." skip it, rest are body
        if len(table_rows) >= 2:
            head = table_rows[0]
            body = table_rows[2:] if len(table_rows) > 2 else []
            out.append("<table>")
            out.append(
                "<thead><tr>"
                + "".join(f"<th>{_inline_rich(c)}</th>" for c in head)
                + "</tr></thead>"
            )
            out.append("<tbody>")
            for row in body:
                out.append("<tr>" + "".join(f"<td>{_inline_rich(c)}</td>" for c in row) + "</tr>")
            out.append("</tbody></table>")
        table_rows = []
        in_table = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                out.append(
                    f'<pre><code class="lang-{html.escape(code_lang)}">'
                    + html.escape("\n".join(code_buf))
                    + "</code></pre>"
                )
                code_buf = []
                code_lang = ""
                in_code = False
            else:
                _flush_para()
                _flush_list()
                _flush_table()
                in_code = True
                code_lang = stripped[3:].strip()
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if stripped.startswith("#"):
            _flush_para()
            _flush_list()
            _flush_table()
            level = len(stripped) - len(stripped.lstrip("#"))
            level = min(max(level, 1), 6)
            text = stripped[level:].strip()
            out.append(f"<h{level}>{_inline_rich(text)}</h{level}>")
            i += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            _flush_para()
            _flush_list()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            table_rows.append(cells)
            in_table = True
            i += 1
            continue
        if in_table:
            _flush_table()

        if stripped.startswith("- ") or stripped.startswith("* "):
            _flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline_rich(stripped[2:])}</li>")
            i += 1
            continue

        if not stripped:
            _flush_para()
            _flush_list()
            i += 1
            continue

        para_buf.append(stripped)
        i += 1

    _flush_para()
    _flush_list()
    _flush_table()
    if in_code:
        out.append(
            f'<pre><code class="lang-{html.escape(code_lang)}">'
            + html.escape("\n".join(code_buf))
            + "</code></pre>"
        )

    return "\n".join(out)


# ---------------------------------------------------------------------------

_CSS = """\
:root {
  --fg: #1a1a1a; --bg: #fff; --muted: #666; --accent: #0b5fff; --code-bg: #f5f5f7;
}
* { box-sizing: border-box; }
body { font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif; color: var(--fg); background: var(--bg); margin: 0; }
.wrap { max-width: 960px; margin: 0 auto; padding: 32px 20px 80px; }
h1 { font-size: 28px; margin: 0 0 16px; }
h2 { font-size: 20px; margin: 32px 0 12px; border-bottom: 1px solid #eee; padding-bottom: 6px; }
h3 { font-size: 16px; margin: 24px 0 8px; }
h4 { font-size: 14px; margin: 16px 0 6px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code { background: var(--code-bg); padding: 1px 6px; border-radius: 4px; font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; }
pre { background: var(--code-bg); padding: 14px 16px; border-radius: 6px; overflow-x: auto; font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
pre code { background: transparent; padding: 0; }
table { border-collapse: collapse; margin: 12px 0; font-size: 14px; }
th, td { padding: 6px 12px; border-bottom: 1px solid #eee; text-align: left; vertical-align: top; }
th { background: #fafafa; font-weight: 600; }
.breadcrumb { color: var(--muted); font-size: 13px; margin: 0 0 16px; }
.meta { color: var(--muted); font-size: 13px; margin: 4px 0 20px; }
.concerns { columns: 3 220px; gap: 24px; margin: 16px 0; }
.concerns section { break-inside: avoid; margin-bottom: 18px; }
.concerns h3 { margin: 0 0 6px; font-size: 14px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
.concerns ul { list-style: none; padding: 0; margin: 0; }
.concerns li { margin: 2px 0; font-size: 14px; }
.searchbox { width: 100%; padding: 10px 14px; font: inherit; border: 1px solid #ddd; border-radius: 6px; margin: 0 0 24px; }
.searchbox:focus { outline: none; border-color: var(--accent); }
#search-results { list-style: none; padding: 0; margin: 0 0 24px; }
#search-results li { padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px; background: #eee; font-size: 11px; color: var(--muted); margin-right: 4px; }
@media (max-width: 640px) {
  .wrap { padding: 20px 16px 60px; }
  .concerns { columns: 1; }
}
"""

_SEARCH_JS = """\
(function(){
  const input = document.getElementById('q');
  const results = document.getElementById('search-results');
  if (!input || !results) return;
  let docs = null;
  fetch('search.json').then(r => r.json()).then(d => { docs = d; });
  function score(q, doc) {
    q = q.toLowerCase();
    const hay = (doc.name + ' ' + doc.body).toLowerCase();
    if (!hay.includes(q)) return 0;
    return (doc.name.toLowerCase().includes(q) ? 100 : 0) + (hay.split(q).length - 1);
  }
  input.addEventListener('input', () => {
    const q = input.value.trim();
    results.innerHTML = '';
    if (!q || !docs) return;
    const hits = docs.map(d => [score(q, d), d]).filter(x => x[0] > 0).sort((a,b) => b[0]-a[0]).slice(0, 20);
    for (const [_, d] of hits) {
      const li = document.createElement('li');
      li.innerHTML = '<a href="' + d.url + '">' + d.name + '</a> <span class="tag">' + d.kind + '</span> <span class="meta">' + d.summary + '</span>';
      results.appendChild(li);
    }
  });
})();
"""


def _shell(title: str, body: str, *, depth: int = 0) -> str:
    prefix = "../" * depth
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — HuGR Arsenal</title>
<link rel="stylesheet" href="{prefix}style.css">
</head><body><div class="wrap">
<p class="breadcrumb"><a href="{prefix}index.html">HuGR Arsenal</a> / {html.escape(title)}</p>
{body}
</div></body></html>
"""


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def _load_registry() -> list[dict]:
    raw = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    return raw.get("primitives") or []


def _load_contract(namespace: str, name: str) -> dict | None:
    p = VENOUS_ROOT / namespace / name / f"{name}.contract.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_md(namespace: str, name: str) -> str:
    p = VENOUS_ROOT / namespace / name / f"{name}.md"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def _last_audit_timestamp(namespace: str, name: str) -> str:
    """Source-code audit timestamp — newest mtime of the primitive's files."""
    base = VENOUS_ROOT / namespace / name
    if not base.exists():
        return ""
    mtimes = [p.stat().st_mtime for p in base.glob("*") if p.is_file()]
    if not mtimes:
        return ""
    ts = datetime.fromtimestamp(max(mtimes), tz=UTC)
    return ts.strftime("%Y-%m-%d")


def _load_tools() -> list[ToolMeta]:
    tools: list[ToolMeta] = []
    for py in sorted(ADAPT_ROOT.rglob("add_*.py")):
        if py.name.startswith("test_") or "__pycache__" in py.parts:
            continue
        spec = importlib.util.spec_from_file_location(f"_tool_{py.stem}", py)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:  # noqa: BLE001
            continue
        meta = getattr(mod, "MCP_TOOL", None)
        if not isinstance(meta, dict) or "name" not in meta:
            continue
        tools.append(
            ToolMeta(
                name=str(meta["name"]),
                description=str(meta.get("description", "")),
                tags=tuple(meta.get("tags", []) or []),
                module_path=str(py.relative_to(SKILL_ROOT)),
            )
        )
    tools.sort(key=lambda t: t.name)
    return tools


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_landing(primitives: list[dict], tools: list[ToolMeta]) -> str:
    by_concern: dict[str, list[dict]] = {}
    for p in primitives:
        by_concern.setdefault(p["concern"], []).append(p)
    for lst in by_concern.values():
        lst.sort(key=lambda e: e["name"].lower())

    concerns_html: list[str] = []
    for concern in sorted(by_concern):
        items = "".join(
            f'<li><a href="primitive/{p["name"]}.html">{p["name"]}</a></li>'
            for p in by_concern[concern]
        )
        concerns_html.append(f"<section><h3>{html.escape(concern)}</h3><ul>{items}</ul></section>")

    doc_nav = "".join(
        f'<li><a href="doc/{slug}.html">{html.escape(title)}</a></li>'
        for _src, slug, title in _TOP_LEVEL_DOCS
        if (REPO_ROOT / _src).exists()
    )

    body = f"""<h1>HuGR Arsenal — Reference</h1>
<p class="meta">{len(primitives)} primitives · {len(tools)} tools · Rails-analogy 3-layer architecture</p>
<input class="searchbox" id="q" type="search" placeholder="Search primitives, tools, intents…" autocomplete="off">
<ul id="search-results"></ul>

<h2>Contract &amp; roadmap</h2>
<ul>{doc_nav}</ul>

<h2>Primitives by concern</h2>
<div class="concerns">{"".join(concerns_html)}</div>

<h2>Tools</h2>
<p><a href="tools.html">All {len(tools)} adapt tools →</a></p>

<script src="search.js"></script>
"""
    return _shell("Reference", body, depth=0)


def _render_primitive(entry: dict, md: str, contract: dict | None, audit: str) -> str:
    name = entry["name"]
    ns = entry["namespace"]
    source_url = f"{_SOURCE_URL_BASE}/core/venous/{ns}/{name}"

    body_parts: list[str] = []
    body_parts.append(f"<h1>{html.escape(name)}</h1>")
    body_parts.append(
        f'<p class="meta">namespace: <code>{html.escape(ns)}</code> · concern: <code>{html.escape(entry["concern"])}</code>'
        f' · <a href="{source_url}" target="_blank" rel="noopener">source</a>'
        f" · last audit: {html.escape(audit or '—')}</p>"
    )

    if contract and contract.get("api_signature"):
        body_parts.append("<h2>API signature</h2>")
        body_parts.append(
            f'<pre><code class="lang-python">{html.escape(contract["api_signature"])}</code></pre>'
        )

    if contract and contract.get("invariants"):
        body_parts.append("<h2>Invariants</h2><ul>")
        for inv in contract["invariants"]:
            rule = inv.get("rule", "") if isinstance(inv, dict) else str(inv)
            body_parts.append(f"<li>{_inline_rich(rule)}</li>")
        body_parts.append("</ul>")

    # Convert full .md for human context. Strip top-of-file H1 since we emit
    # our own header.
    md_body = re.sub(r"^# .+\n", "", md, count=1)
    body_parts.append(_md_to_html(md_body))

    # Inject compose-with link list using the registry (gives stable links).
    composes = entry.get("compose_with") or []
    if composes:
        body_parts.append("<h2>Compose with</h2><ul>")
        for other in composes:
            body_parts.append(
                f'<li><a href="{html.escape(other)}.html">{html.escape(other)}</a></li>'
            )
        body_parts.append("</ul>")

    return _shell(name, "\n".join(body_parts), depth=1)


def _render_tools(tools: list[ToolMeta]) -> str:
    rows = "".join(
        f'<tr><td><a href="tool/{html.escape(t.name)}.html"><code>{html.escape(t.name)}</code></a></td>'
        f"<td>{html.escape(t.description)}</td>"
        f"<td>{''.join(f'<span class=tag>{html.escape(tag)}</span>' for tag in sorted(t.tags))}</td></tr>"
        for t in tools
    )
    body = f"""<h1>Adapt tools</h1>
<p class="meta">{len(tools)} tools registered via <code>MCP_TOOL</code> metadata.</p>
<table><thead><tr><th>Name</th><th>Description</th><th>Tags</th></tr></thead>
<tbody>{rows}</tbody></table>
"""
    return _shell("Tools", body, depth=0)


def _render_tool(tool: ToolMeta) -> str:
    source_url = f"{_SOURCE_URL_BASE}/{tool.module_path}"
    tag_html = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in sorted(tool.tags))
    body = f"""<h1>{html.escape(tool.name)}</h1>
<p class="meta">MCP tool · <a href="{html.escape(source_url, quote=True)}" target="_blank" rel="noopener">source</a> · module <code>{html.escape(tool.module_path)}</code></p>
<p>{html.escape(tool.description)}</p>
<h2>Tags</h2>
<p>{tag_html or '<span class="meta">none</span>'}</p>
<h2>See also</h2>
<p><a href="../tools.html">All tools</a> · <a href="../index.html">Reference home</a></p>
"""
    return _shell(tool.name, body, depth=1)


def _render_doc(slug: str, title: str, md: str) -> str:
    md_body = re.sub(r"^# .+\n", "", md, count=1)
    body = f"<h1>{html.escape(title)}</h1>\n{_md_to_html(md_body)}"
    return _shell(title, body, depth=1)


def _build_search_index(primitives: list[dict], tools: list[ToolMeta]) -> list[dict]:
    docs: list[dict] = []
    for p in primitives:
        docs.append(
            {
                "name": p["name"],
                "kind": "primitive",
                "url": f"primitive/{p['name']}.html",
                "summary": p.get("purpose", "") or "",
                "body": p.get("purpose", "") + " " + " ".join(p.get("compose_with") or []),
            }
        )
    for t in tools:
        docs.append(
            {
                "name": t.name,
                "kind": "tool",
                "url": f"tool/{t.name}.html",
                "summary": t.description,
                "body": t.description + " " + " ".join(t.tags),
            }
        )
    for src, slug, title in _TOP_LEVEL_DOCS:
        if not (REPO_ROOT / src).exists():
            continue
        docs.append(
            {
                "name": title,
                "kind": "doc",
                "url": f"doc/{slug}.html",
                "summary": src,
                "body": title + " " + src,
            }
        )
    docs.sort(key=lambda d: (d["kind"], d["name"].lower()))
    return docs


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def _clean_out(out_dir: Path) -> None:
    if out_dir.exists():
        for p in sorted(out_dir.rglob("*"), reverse=True):
            if p.is_file() or p.is_symlink():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        out_dir.rmdir()


def build_site(out_dir: Path = DEFAULT_OUT) -> dict:
    """Generate the site into `out_dir`. Returns a build-manifest dict.

    Manifest shape::

        {
            "primitives": int,
            "tools": int,
            "pages_written": int,
            "hash": "<sha256 of concatenated file hashes, sorted by path>",
        }

    The same inputs must produce the same ``hash`` on any machine.
    """
    _clean_out(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "primitive").mkdir(parents=True, exist_ok=True)
    (out_dir / "tool").mkdir(parents=True, exist_ok=True)
    (out_dir / "doc").mkdir(parents=True, exist_ok=True)

    primitives = _load_registry()
    tools = _load_tools()

    (out_dir / "style.css").write_text(_CSS, encoding="utf-8")
    (out_dir / "search.js").write_text(_SEARCH_JS, encoding="utf-8")
    (out_dir / "search.json").write_text(
        json.dumps(_build_search_index(primitives, tools), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out_dir / "index.html").write_text(_render_landing(primitives, tools), encoding="utf-8")
    (out_dir / "tools.html").write_text(_render_tools(tools), encoding="utf-8")

    pages = 2  # index + tools
    for entry in primitives:
        name = entry["name"]
        md = _load_md(entry["namespace"], name)
        contract = _load_contract(entry["namespace"], name)
        audit = _last_audit_timestamp(entry["namespace"], name)
        html_out = _render_primitive(entry, md, contract, audit)
        (out_dir / "primitive" / f"{name}.html").write_text(html_out, encoding="utf-8")
        pages += 1

    for tool in tools:
        (out_dir / "tool" / f"{tool.name}.html").write_text(_render_tool(tool), encoding="utf-8")
        pages += 1

    for src, slug, title in _TOP_LEVEL_DOCS:
        src_path = REPO_ROOT / src
        if not src_path.exists():
            continue
        md = src_path.read_text(encoding="utf-8")
        (out_dir / "doc" / f"{slug}.html").write_text(
            _render_doc(slug, title, md), encoding="utf-8"
        )
        pages += 1

    site_hash = _site_hash(out_dir)

    manifest = {
        "primitives": len(primitives),
        "tools": len(tools),
        "pages_written": pages,
        "hash": site_hash,
    }
    (out_dir / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


def _site_hash(out_dir: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(out_dir.rglob("*")):
        if not p.is_file() or p.name == "build_manifest.json":
            continue
        rel = p.relative_to(out_dir).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _iter_html(out_dir: Path) -> Iterable[Path]:
    yield from out_dir.rglob("*.html")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--verify", action="store_true", help="Build twice; fail if hash differs.")
    args = parser.parse_args(argv)

    m = build_site(args.out)
    print(
        f"built {m['pages_written']} pages ({m['primitives']} primitives, {m['tools']} tools) → {args.out}"
    )
    print(f"hash: {m['hash']}")

    if args.verify:
        m2 = build_site(args.out)
        if m["hash"] != m2["hash"]:
            print(
                f"FAIL: hash drift across two builds ({m['hash']} vs {m2['hash']})", file=sys.stderr
            )
            return 1
        print("idempotent: hash stable across two builds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
