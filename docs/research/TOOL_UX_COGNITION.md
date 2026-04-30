# Research Findings — Catalog Navigation + Cognition (v1, 2026-04-20)

Context: HuGR Smith exposes ~180 MCP tools to an LLM worker agent. We need an interface layer that is cognitively natural for both the model and a human reviewer. This document synthesizes empirical cognition research, UX design wisdom, CLI/command-palette precedent, and LLM-specific tool-selection literature into concrete design moves.

## TLDR (5 bullets)

- **180 tools is past every known "scan" threshold.** Miller's 7±2 and Cowan's 4±1 describe working memory, not catalogs, but designers treat ~7–10 as the point at which a flat list stops being scannable. We must design for *search + categorize*, never *scan*.
- **Humans switch from scan to search at ~20–30 items**; command palettes (VSCode, Raycast) assume search as the primary mode and sort by name for *stability* (muscle memory) rather than by fuzzy score. This translates directly to LLM UX: tool order must be stable across turns so the model builds a cache.
- **LLMs have measurable position bias.** "Lost in the middle" (Liu et al., 2023) and primacy/recency work (Raimondi 2025; Guo 2024) show tool lists suffer U-shaped recall. Put the most-used and most-"start-here" tools first and last; never bury the index.
- **Tool-RAG beats flat exposure past ~30–50 tools.** ToolLLM (16k APIs), ToolRet (43k tools), and Red Hat's 2025 tool-RAG writeup all show retrieval-based tool surfacing roughly *triples* selection accuracy vs. dumping the full list. At 180 tools we are squarely in tool-RAG territory.
- **Verb-noun hierarchy (kubectl / gh) scales to hundreds of subcommands** when the verb set is small (~7) and stable, and nouns are discoverable via a single index command (`kubectl api-resources`, `gh help`). Two levels is the sweet spot; three is where NN/g says users get lost.

## 1. Cognitive load limits

**Miller (1956) — 7±2.** Short-term memory holds ~7 chunks; this is the most-cited and most-misapplied number in UX (Britannica; Miller 1956). It describes *memory*, not *menu size*. The paper itself never says "menus should have 7 items."

**Cowan (2001) — 4±1.** Refined estimate: when chunking and rehearsal are blocked, true capacity is 3–4 chunks (Cowan 2001; Mathy & Feldman 2012). The 7 vs. 4 reconciliation: 7 applies when chunking is free; 4 when it is not.

**Hick's Law (1952) — RT ∝ log₂(n+1).** Choice reaction time scales *logarithmically* with number of options (Hick 1952; Hyman 1953; Proctor & Schneider 2018 review). *Critical caveat from the Proctor review:* Hick's logarithm requires that users can *subdivide* the choice space (alphabetical order, categories). For *unordered* menus, scan time is **linear**, not log. Cited at Wikipedia's own Hick page: "scanning each word in a randomly ordered list requires linear time, so Hick's law does not apply."

**Implication for a 180-tool catalog.** A flat unsorted list is O(n) to scan. A categorized or name-sorted list is O(log n) *if the user knows what they are looking for*. If they don't, categorization alone isn't enough — you need a search affordance.

## 2. Progressive disclosure patterns

**Nielsen (1995, reissued 2006).** Progressive disclosure = show the top-most-used options first; defer the rest behind an explicit "more" affordance (NN/g "Progressive Disclosure"). Empirical wisdom (not a controlled study): **more than 2 levels of disclosure causes users to get lost**; 3+ levels means the design itself is wrong and needs flattening (NN/g).

**Apple HIG & Material Design** both recommend the same pattern under different names: Apple's "Inspector" / "disclosure triangle"; Material's "expansion panel." Both cap primary action surfaces at ~5–7 items before pushing to secondary surfaces.

**Hamburger-menu research (NN/g video).** Hiding navigation behind a single icon *measurably* hurts discovery. Translation to tool catalogs: if the LLM must "open" something to see tools, usage drops. The index must be visible, even if summarized.

**Design wisdom vs. empirical.** NN/g's 2-level rule is design wisdom (qualitative usability studies). Miller/Cowan/Hick are empirical (controlled lab experiments). The 2-level rule has not been replicated as a controlled experiment; treat it as strong heuristic, not law.

## 3. Command palette design (deep)

**VSCode command palette.** Algorithm: subsequence match (query chars must appear in target in order), not Levenshtein. Favors matches at word boundaries and camelCase splits (D0ntPanic/code-fuzzy-match; microsoft/vscode #1964). **Critical design choice**: VSCode sorts the command palette *alphabetically*, not by fuzzy score, to keep the list **stable** so users learn positions (microsoft/vscode #27317). This is the Hick's Law subdivision trick in action: a stable alphabetical index is log-searchable.

**Raycast root search.** Fuzzy match across title, subtitle, keywords, and alias; extensions define a `keywords` array *explicitly* for discoverability rather than relying on title tokens alone (Raycast manual "Search Bar"; Raycast API docs). Extensions can also expose *arguments* directly in root search — a flat entry point to a parameterized command, removing an entire navigation step.

**Linear / Notion / Slack.** All three use category-prefix sigils: `>` (command), `@` (person), `#` (channel/page). This is the cheapest possible category disambiguator — one character — and it turns an N-way search into a filtered N/k search. It is also trivially memorable because the sigil *is* the mental model.

**Recency / frequency weighting.** VSCode keeps recent commands at the top of the palette (the "Recently used" section) but below the query region — visible without interfering with stable sort.

**Takeaways that transfer.** (a) One stable sort order, not adaptive. (b) Fuzzy subsequence matching beats edit distance. (c) Sigils as category prefixes beat nested menus. (d) Explicit `keywords` metadata > relying on names alone.

## 4. CLI hierarchical design

**kubectl — verb + noun + flag.** `kubectl <verb> <resource> [name] [flags]`. Verb set is small and closed: `get, describe, create, apply, delete, edit, logs, exec, scale, rollout, port-forward, …` (~20). Resources are open and discoverable via `kubectl api-resources`. With 30 verbs × 40+ resources kubectl comfortably covers >1000 logical commands through **composition**, not enumeration (Kubernetes docs "kubectl overview").

**gh (GitHub CLI) — group + action.** `gh <group> <action>`. Groups: `repo, pr, issue, run, release, api, auth, gist, …` (~15). Actions: `create, view, list, edit, close, merge, …` (~10). Context-aware defaults (current repo/branch) collapse flags (cli/cli README). `--help` at every level is the uniform disclosure mechanism.

**docker.** Started flat (`docker run`, `docker ps`), migrated to nested (`docker container run`, `docker image ls`) as surface grew past ~40 commands. The old flat aliases remain as shortcuts. Lesson: **hierarchy is a discovery tool; aliases preserve ergonomics for experts.**

**Why verb-noun scales.** (a) Small closed verb vocabulary = fits in working memory. (b) Open noun vocabulary = enumerable via an `api-resources`-like index. (c) Composition multiplies coverage without multiplying the list the user must scan.

## 5. Applicability to LLM tool catalogs

Humans and LLMs differ in three ways that matter for this design:

| Human UX principle | LLM translation | Confidence |
|---|---|---|
| Hick's Law: RT ∝ log₂(n) with sorted list | LLMs don't "react" in time, but **token cost scales linearly with listed tools**, and selection accuracy *degrades* past ~30–50 tools (ToolLLM; ToolRet — Chen et al. 2025 at aclanthology 2025.findings-acl.1258) | Empirical |
| Miller 7±2, Cowan 4±1 (working memory) | No direct analog. But attention heads show recency/primacy peaks (Liu 2023 "Lost in the Middle"; Raimondi & Lombardi 2025). The U-curve is the LLM analog of "edges of working memory." | Empirical |
| Progressive disclosure (NN/g) | **Tool-RAG is progressive disclosure for agents.** Retrieve top-k tools by semantic match on task description; hide the rest (Red Hat 2025 "Tool RAG"). Triples accuracy, halves prompt. | Empirical |
| Stable alphabetical sort (VSCode) | Stable tool order enables **prompt caching** (Anthropic's 5-min cache is position-sensitive — moving a tool breaks cache). | Empirical (caching) + design wisdom (muscle memory) |
| Sigil prefixes (Linear `@`, `>`) | Tool-name prefixes (`add_`, `verify_`, `evolve_`) serve the same role for an LLM: they partition the name space and let retrieval filter by prefix before semantic match. | Design wisdom (no controlled study on LLM side) |
| Cheat sheets (vim, Unix man SYNOPSIS) | An **index tool** that returns a tight table of (name, one-line description, category) is the agent analog. Mirrors `kubectl api-resources`. | Design wisdom |
| Recall vs recognition | LLMs can do both: *recall* from pretraining if tool is famous (pandas, requests); *recognition* from the provided list. At 180 custom tools, recognition is the only viable path — which means the list (or a retrieved slice of it) must be in context. | Inferred from tool-RAG papers |

Key LLM-only findings:

- **"Lost in the middle" (Liu et al. 2023).** U-shaped performance by position across 4K/16K/32K context windows. At 180 tools the middle ~100 are the danger zone — if they matter, they need to be retrieved, not listed.
- **Primacy/recency bias (Raimondi 2025 arXiv 2507.13949; Guo et al. 2024 arXiv 2406.15981).** Llama-2 shows recency; GPT-class shows primacy; the effect is reliable but model-dependent. A "home" tool should appear at position 1 *and* be re-mentioned in the tail.
- **Tool-RAG scales (ToolLLM; ToolRet benchmarks).** ToolLLM trained on 16,464 RapidAPI endpoints across 49 categories; retrieval became the only workable pattern past ~50 tools (Qin et al. 2023 arXiv 2307.16789).

## 6. Recommendations for HuGR Smith (interface layer)

Goal: make 180 tools feel like ~7 to the model at any given moment, while preserving full coverage.

**Design moves (each with a precedent):**

1. **Single "home" index tool the agent always sees first.** Call it `skillkit.index` or similar. Returns a compressed map: categories + tool counts + one-line category descriptions. Precedent: `kubectl api-resources`, `gh help`, Unix `man -k`. This is the only tool that is always-on; it is always at position 1 to exploit primacy (Raimondi 2025).

2. **Verb prefix as the primary category.** Standardize: `add_*` (extend), `verify_*`, `operate_*`, `evolve_*`, `proactive_*`. The prefix is the sigil — cheap, memorable, filterable. Precedent: Linear's `@/#/>`, kubectl verbs, SKILL-001's existing `add_*` convention. *Keep the verb set closed and small (~7).* If a 6th verb is tempting, justify it the way kubectl justifies a new verb: by demonstrating it isn't an existing verb in disguise.

3. **Noun taxonomy as the secondary axis, discoverable not enumerated.** Nouns (crud, auth, infra, realtime, api, testing, observability…) live in a `tags` field, not the tool name. Agents query `skillkit.index(verb="add", tag="auth")` to get ~10 candidates, not 180. Precedent: kubectl resources; Raycast `keywords`; OpenAPI `tags`.

4. **Tool-RAG as the default selection mechanism for any task beyond a single domain.** Task description → embed → top-k (k≈10) tool schemas injected into context. Flat listing of 180 schemas is ~25–40k tokens; top-10 is ~1.5–3k tokens. Precedent: ToolLLM retriever; Red Hat "Tool RAG" 2025; MCP's own direction. *Keep the index tool + the top-k list — do not make tool-RAG the only surface, because the index gives the model the "landscape at a glance" the brief asks for.*

5. **Stable, alphabetical-within-category sort.** Do not reorder by recency/frequency across turns. Precedent: VSCode command palette (microsoft/vscode #27317). Rationale: (a) Anthropic prompt-cache 5-min TTL is position-sensitive; (b) gives the model a learnable position → cache key. If recency matters, expose it as a *separate* `recently_used` field, not by reordering the main list.

6. **Cheat-sheet shape for every tool's one-liner.** `verb_noun(required_args) → returns`. One line. Mirrors Unix man SYNOPSIS and Python docstring first line. Forces the author to name the tool well and limits index-row token cost. Precedent: Unix man pages; Python PEP 257.

7. **Bookend primacy + recency with the index tool.** Put `skillkit.index` at position 1 AND repeat a condensed one-line reminder near the tool-list tail (or in the system suffix). Counteracts "Lost in the middle" (Liu 2023) and exploits both primacy and recency (Raimondi 2025 duplication trick). This is a cheap ~100-token insurance policy.

**What NOT to do (anti-precedent):**

- Do not build 3+ level hierarchies (NN/g 2-level cap).
- Do not reorder by fuzzy score per turn (VSCode explicitly rejected this).
- Do not rely solely on tool names for discoverability — add explicit `keywords` + `tags` (Raycast convention).
- Do not dump all 180 schemas every turn (Tool-RAG literature; ~linear token cost, measurable accuracy degradation past ~30–50 tools).

**Concrete shape of the interface layer (strawman):**

```
Position 1 (system prompt tail):
  skillkit.index(verb?, tag?, query?) → {categories: [...], tools: [{name, synopsis, tags}]}

Positions 2..k+1 (retrieved per task):
  top-10 tool schemas matching task embedding, ordered alphabetically within category

Last position (brief reminder):
  "Unsure which tool? Call skillkit.index first."
```

This gives the agent: (a) a stable, cacheable home (position 1); (b) a just-in-time working set of ~10 tools (the Cowan/Miller-sized window); (c) a primacy+recency bookend; (d) a path back to the full 180 via the index. It is, structurally, `kubectl api-resources` + tool-RAG + Linear sigils, all stolen with attribution.

## Sources

- [Nielsen, "Progressive Disclosure" (NN/g, 2006)](https://www.nngroup.com/articles/progressive-disclosure/) — 2-level cap; defer rarely-used options; 3+ levels = redesign.
- [NN/g "Hamburger Menus Hurt UX Metrics"](https://www.nngroup.com/videos/hamburger-menus/) — hidden nav measurably reduces discovery.
- [Miller (1956), "The Magical Number Seven, Plus or Minus Two"](https://en.wikipedia.org/wiki/The_Magical_Number_Seven,_Plus_or_Minus_Two) — 7±2 is about memory chunks, not menu items.
- [Cowan (2001) / Mathy & Feldman (2012), "What's magic about magic numbers?"](https://www.sciencedirect.com/science/article/abs/pii/S0010027711002733) — chunk-free capacity is 3–4, reconciles with Miller's 7.
- [Proctor & Schneider (2018), "Hick's Law for Choice Reaction Time: A Review"](https://pubmed.ncbi.nlm.nih.gov/28434379/) — log law requires subdividable stimulus; unordered lists are linear.
- [Hick's Law, Wikipedia](https://en.wikipedia.org/wiki/Hick%27s_law) — explicit caveat that random menus do not obey the log law.
- [VSCode issue #27317 "Improve ranking of elements in quick open"](https://github.com/Microsoft/vscode/issues/27317) — explicit decision to keep command palette sort stable for muscle memory.
- [code-fuzzy-match (VSCode-inspired algorithm)](https://github.com/D0ntPanic/code-fuzzy-match) — subsequence, word-boundary, camelCase bonuses; not Levenshtein.
- [Raycast Manual — Search Bar](https://manual.raycast.com/search-bar) — fuzzy match across title, subtitle, keywords, alias.
- [Raycast API — Create Your First Extension](https://developers.raycast.com/basics/create-your-first-extension) — `keywords` array is an explicit discoverability affordance.
- [Kubernetes kubectl overview](https://unofficial-kubernetes.readthedocs.io/en/latest/user-guide/kubectl-overview/) — verb + resource + flag composition; `kubectl api-resources` as live index.
- [GitHub cli/cli README](https://github.com/cli/cli) — group + action + context-aware defaults.
- [Liu et al. (2023), "Lost in the Middle: How Language Models Use Long Contexts"](https://arxiv.org/abs/2307.03172) — U-shaped recall by position across 4K/16K/32K contexts.
- [Raimondi & Lombardi (2025), "Exploiting Primacy Effect To Improve LLMs"](https://arxiv.org/abs/2507.13949) — descending-order tricks lift MCQA accuracy; models vary in primacy vs recency bias.
- [Guo et al. (2024), "Serial Position Effects of Large Language Models"](https://arxiv.org/html/2406.15981v1) — SPE is general across generative models; Llama-2 shows recency.
- [Qin et al. (2023), "ToolLLM: Mastering 16,000+ Real-world APIs"](https://arxiv.org/abs/2307.16789) — retrieval becomes mandatory past ~50 tools.
- [Chen et al. (2025), "Benchmarking Tool Retrieval for LLMs" (ToolRet)](https://aclanthology.org/2025.findings-acl.1258.pdf) — 43k-tool corpus; retrievers + agents both degrade at scale.
- [Red Hat Emerging Tech (2025), "Tool RAG"](https://next.redhat.com/2025/11/26/tool-rag-the-next-breakthrough-in-scalable-ai-agents/) — tool-RAG roughly triples selection accuracy, halves prompt length.
