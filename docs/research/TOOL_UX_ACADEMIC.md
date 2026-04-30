# Research Findings — Academic Literature on Agent Tool Scale (v1, 2026-04-20)

> **Methodology caveat.** This review is compiled from model-training knowledge of the cited papers (cutoff Jan 2026). Where a specific number is cited, the figure/table is named. Where my recall of a specific number is uncertain, the claim is qualified with "approx." or marked UNKNOWN. No live web retrieval was performed for this document; the founder should spot-check the exact numerics against the linked arxiv PDFs before using them load-bearing in a design doc.

---

## TLDR

- **Flat tool exposure degrades well before 180 tools.** Gorilla (Patil et al. 2023, arxiv 2305.15334) explicitly motivates retrieval because LLMs cannot hold 1,600+ API signatures in-context; ToolLLM (Qin et al. 2023, arxiv 2307.16789) retrieves top-k≈5 from 16,464 APIs rather than exposing them flat. No paper we reviewed exposes >~50 tools flat and reports good accuracy.
- **Retrieval-over-tools beats flat exposure once N exceeds roughly the low tens.** ToolLLM's DFSDT+retriever pipeline and Gorilla's retrieval-aware training both report large gains vs. a zero-shot flat baseline (Gorilla: hallucination rate drops from ~52% zero-shot GPT-4 to ~14% with retrieval on TorchHub/HuggingFace APIs; Gorilla paper Table 4, approx.).
- **Hierarchical / category organization is used as infrastructure (ToolBench's 49 RapidAPI categories, MetaTool's 199 tools across categories) but there is no clean published ablation isolating "hierarchy vs flat-same-N" as of my knowledge cutoff.** The dominant published pattern is *retrieval*, not *hierarchy*. This is a real gap HuGR could document empirically.
- **Known failure modes at scale are confirmed:** tool hallucination (Gorilla's central metric), confusion between similar tools (ToolLLM's "similar API" splits; MetaTool's "tool-selection" task), and failure to invoke any tool when one was needed (MetaTool's "tool-usage awareness" task — even GPT-4 scores well below ceiling).
- **None of the cited papers publish a Claude 4.5 / 4.7 tool-count-vs-accuracy curve.** Anthropic's public model cards mention tool-use evals (SWE-bench, τ-bench, MCP) but do not publish N-tools → accuracy. Applying pre-2024 GPT-3.5/GPT-4 findings to Claude Opus 4.7 is an extrapolation.

---

## 1. Published empirical data on tool count vs accuracy

I am **not aware of a single paper that publishes a clean "N tools exposed flat → accuracy" curve** for a frontier model as of 2026-04. The closest published data points:

| Paper | Tool pool | Exposure mechanism | Headline metric |
|---|---|---|---|
| Toolformer (Schick 2023, arxiv 2302.04761) | 5 tools (QA, calc, calendar, MT, search) | Trained-in, flat | Shows tool-use helps 6.7B model beat GPT-3 on several tasks. N=5 is too small to inform scaling. |
| Gorilla (Patil 2023, arxiv 2305.15334) | 1,645 APIs (TorchHub/TF Hub/HuggingFace) | Retrieval (BM25 / GPT-index / oracle) | Zero-shot GPT-4 hallucination ~52%; Gorilla-retrieved drops to ~14% (Table 4, approx.). Direct evidence that flat does not scale to N≈1,600. |
| ToolLLM / ToolBench (Qin 2023, arxiv 2307.16789) | 16,464 RapidAPI APIs, 3,451 tools | Sentence-BERT retriever returning top-5 | ToolLLaMA + retriever reaches ~80%+ pass rate on I1-Inst; they do not run a "flat 16k" baseline because it is infeasible. |
| API-Bank (Li 2023, arxiv 2304.08244) | 73 APIs | Flat in-context | GPT-4 ~75% call accuracy; smaller models drop sharply. N=73 is the closest to HuGR's 180 but the paper does not ablate N. |
| MetaTool (Huang 2023, arxiv 2310.03128) | 199 tools across 21,127 queries | Tool-selection over description set | GPT-4 ~72% on tool-selection; Llama-2-7B ~40%. Binary awareness task (should I use a tool?) is even harder. |
| ToolACE (Liu 2024, arxiv 2409.00920) | 26,507 APIs synthesized | Retrieval + fine-tuning | 8B model competitive with GPT-4 on BFCL; retrieval is assumed, not ablated. |
| BFCL v1–v3 (Berkeley, 2024-2025) | Up to thousands of functions per category | Varies by split | Shows model ranking but does not isolate "flat N" axis cleanly. |

**The knee question.** I am **not aware of a peer-reviewed paper that publishes the specific knee in accuracy as N flat-exposed tools grows** for Claude 3.5 / 4 / 4.5 / 4.7. **UNKNOWN in literature as of 2026-04.** The closest indirect evidence is Gorilla's motivating argument (paper §1) that zero-shot tool selection is untenable at N≈1,600.

---

## 2. Retrieval-based tool exposure

The dominant published pattern at N > ~50 tools is **retrieval**: the agent is not shown all tools; instead, a retriever returns top-k descriptions that are then inlined into context.

- **Gorilla** (arxiv 2305.15334). Trains the LLM *with* a retriever in the loop ("retriever-aware training") so it learns to condition on retrieved API docs rather than memorize. Reports ~14% hallucination with oracle retrieval vs. ~52% GPT-4 zero-shot (Table 4, approx.). Also shows performance is sensitive to retriever quality.
- **ToolLLM / ToolBench** (arxiv 2307.16789). Two-stage: Sentence-BERT retriever → DFSDT (depth-first search decision tree) planner. Retriever trained on their own tool-query pairs. Reports that retriever-top-5 is competitive with oracle for most tasks.
- **RestGPT** (Song 2023, arxiv 2306.06624). Uses an online planner + coarse-to-fine API selector over REST endpoints. Effectively retrieval, scoped by OpenAPI spec.
- **AnyTool** (Du et al. 2024, arxiv 2402.04253). Hierarchical API retriever using GPT-4 itself as the navigator through a category → tool → function tree over 16k+ ToolBench APIs. Reports significant gains over the flat ToolLLM retriever (approx. +20 pp pass-rate on hard splits per their Table 2, figure uncertain). **This is the closest published evidence that hierarchy helps on top of retrieval.**

**When retrieval wins over flat:** whenever top-k << N and descriptions are long enough that flat exposure would blow context or confuse selection. All cited papers above assume this regime (N ≥ ~70–16,000).

---

## 3. Hierarchical / graph-based tool organization

- **AnyTool** (arxiv 2402.04253) is the cleanest hierarchical example: category agent → tool agent → function agent, each agent seeing only its local subtree. Reports pass-rate gains vs. ToolLLM flat retriever on ToolBench.
- **ToolBench RapidAPI** (Qin 2023) organizes 16k APIs into 49 categories and 3,451 collections as *infrastructure*, but the headline ToolLLM pipeline is flat retrieval — so ToolBench itself does not publish a category-aware ablation.
- **Chameleon** (Lu et al. 2023, arxiv 2304.09842). Composes tools in a plan but operates over a small fixed toolbox (~15 tools); not a scaling study.
- **HuggingGPT / JARVIS** (Shen 2023, arxiv 2303.17580). Uses a model-registry structure (tasks → models) but again at modest scale (~24 model-tools in headline evals).
- **Call-graph / dependency-aware organization.** **UNKNOWN in literature as of 2026-04** — I am not aware of a paper that organizes tools by explicit call-graph dependencies and measures agent accuracy. HuGR's "Maestro assembles LEGO" framing does not have a direct academic antecedent I can cite.

The decisive gap: **there is no clean "flat-N vs hierarchical-N" ablation holding N and model fixed in the public literature I can recall.** AnyTool is the closest but its comparison is "hierarchical retriever vs flat retriever," not "hierarchical exposure vs flat exposure."

---

## 4. Tool-description retrieval vs embedding retrieval

- **BM25 vs dense embeddings.** Gorilla tests BM25, GPT-index (embedding), and oracle retrievers. Dense embeddings beat BM25, both lose to oracle — suggesting retrieval quality is a bottleneck (Gorilla Table 4, approx.).
- **Sentence-BERT, fine-tuned on tool-query pairs.** ToolLLM's approach; outperforms general-purpose embeddings on their benchmark.
- **LLM-as-retriever.** AnyTool uses GPT-4 itself to walk the hierarchy. More expensive, better on hard cases.
- **Description length matters.** ToolLLM (§4) and API-Bank both note that long, example-rich descriptions improve selection over terse signatures. No paper I recall gives a clean "description-tokens vs accuracy" curve.
- **Example-based retrieval (i.e., retrieving by past query-tool pairs rather than tool descriptions).** Mentioned in RAG literature generally; I am not aware of a dedicated tool-selection ablation. **Partially UNKNOWN.**

**Practical summary of published consensus:** fine-tuned dense embedding over *rich* tool descriptions (signature + natural-language purpose + 1–2 examples) is the default. BM25 is a viable fallback when no training data exists.

---

## 5. Agent self-reflection on tool choice

- **MetaTool** (arxiv 2310.03128). Defines two tasks: (a) *tool-usage awareness* — should I call a tool at all? (b) *tool-selection* — which tool? Finds frontier models (GPT-4) substantially imperfect on both; smaller models much worse. Direct evidence that "should I use a tool" is a non-trivial skill.
- **ReAct** (Yao 2022, arxiv 2210.03629). Thought–Action–Observation loop; shows reasoning-before-acting improves tool use on HotpotQA / ALFWorld. Baseline for all later agent papers.
- **Reflexion** (Shinn 2023, arxiv 2303.11366). Self-verbal feedback loop; improves tool/agent accuracy on HumanEval, HotpotQA. Relevant for recovery from wrong tool choice.
- **Tree of Thoughts** (Yao 2023, arxiv 2305.10601). Search-over-reasoning; not specifically about tool count but relevant to planning with many tools.
- **Chameleon** (arxiv 2304.09842). Explicit plan-first-then-execute over a toolbox; shows planner-level reflection helps composition.

**Does self-reflection on tool choice help at scale?** Published evidence is that ReAct/Reflexion improve outcomes in small toolboxes (≤20). For N=180, I am **not aware of a paper that ablates reflection's value specifically as a function of tool count.** **UNKNOWN.**

---

## 6. Known failure modes at scale

Confirmed by the literature:

- **Tool hallucination.** Gorilla's central motivating failure: zero-shot GPT-4 invents ~52% of API calls against TorchHub (Gorilla §4, approx.). Scales worse with N. This is the most robustly documented failure mode.
- **Confusion between similar tools.** ToolLLM's test splits include "similar API" cases (I2-Cat, I3-Inst) where pass-rate drops meaningfully vs. unambiguous splits. MetaTool explicitly constructs hard-pair sets.
- **Skipping the right tool.** MetaTool's awareness task — even GPT-4 fails a non-trivial fraction (approx. 20–25%, recall uncertain; see MetaTool Table 2).
- **Parameter-level errors.** API-Bank and BFCL isolate "parameter hallucination" (right tool, wrong arg) as a distinct and common failure.
- **Context-window dilution.** Heuristic and widely-cited-but-rarely-ablated: long tool manifests crowd out reasoning tokens and task context. I am **not aware of a controlled ablation isolating this effect at fixed N**; it is more folklore than published finding.
- **Primacy/recency bias in tool lists.** Mentioned in long-context literature (Liu et al. 2023 "Lost in the Middle", arxiv 2307.03172) but not, to my knowledge, specifically ablated on tool-selection tasks. **Partially UNKNOWN** for tool-use specifically.

---

## 7. Voyager / skill-acquisition analogues

- **Voyager** (Wang et al. 2023, arxiv 2305.16291). GPT-4 agent in Minecraft. Key insight for HuGR: Voyager *builds a skill library over time* — new skills are written as code, stored, and retrieved by embedding similarity when relevant. Skills are *composed* rather than all exposed flat. Voyager explicitly reports that the skill library enables lifelong learning; ablation shows removing it hurts performance (Voyager §4).
- **CodeAct** (Wang et al. 2024, arxiv 2402.01030). Agent emits executable Python rather than JSON tool calls; effectively lets the model compose arbitrary tool *sequences* as code. Shows ~20% improvement over JSON-call baselines on several benchmarks (CodeAct Table 2, approx.). Relevant if HuGR ever considers code-as-composition.
- **SWE-agent** (Yang et al. 2024, arxiv 2405.15793). Hand-designed *agent-computer interface* (ACI) for software engineering — a small, carefully-chosen command set rather than raw shell. Reports large gains from *curating* the tool surface (SWE-agent §4). Direct evidence that **tool surface design matters more than tool count**.
- **OS-Copilot / FRIDAY** (Wu et al. 2024, arxiv 2402.07456). Self-improving OS agent with learned skills; same pattern as Voyager in a different domain.

**Lesson for HuGR.** The converging finding — Voyager, SWE-agent, CodeAct — is that **a small, well-curated, composable surface beats a large flat one**, and that **retrieval over a growing skill library is the published scaling pattern**. This is the most decision-relevant cluster of results for HuGR's 180-tool problem.

---

## 8. Recommendations for HuGR Smith

Each recommendation cites its grounding. Uncertainties are called out.

1. **Do not expose 180 tools flat.** Gorilla and ToolLLM both treat flat exposure as infeasible at their N; the *direction* of this finding almost certainly transfers to Claude 4.7 even without a Claude-specific curve. (Gorilla arxiv 2305.15334; ToolLLM arxiv 2307.16789.)

2. **Introduce a two-level surface: a small "intent router" tool + retrieval over the 180.** This is SWE-agent's ACI pattern (small curated top layer) combined with ToolLLM/Gorilla retrieval underneath. The top layer is what Claude sees; the retrieval layer is what returns the right subset per intent. (SWE-agent arxiv 2405.15793; ToolLLM arxiv 2307.16789.)

3. **Prefer fine-tuned dense embeddings over BM25 for the retriever, once you have query→tool training pairs.** Gorilla shows dense > BM25 but both below oracle. Until you have pairs, BM25 over rich descriptions is a viable cold-start. (Gorilla arxiv 2305.15334.)

4. **Write rich descriptions — signature + purpose + 1–2 canonical examples.** Folk-consensus across API-Bank, ToolLLM, BFCL; no clean curve but uniformly reported. Terse signatures underperform.

5. **Consider a hierarchy (category → tool) if your retriever top-k is noisy.** AnyTool (arxiv 2402.04253) reports hierarchical navigation helps on hard splits. Caveat: the clean ablation "hierarchy vs flat at equal N" is not in the public literature I can cite — this would be a novel empirical contribution HuGR could make.

6. **Adopt a skill-library mental model, not a tool-catalog one.** Voyager's composed, stored, retrieved skills (arxiv 2305.16291) and CodeAct's code-as-composition (arxiv 2402.01030) are the 2023–2024 state-of-the-art for agents operating over many capabilities. HuGR's "Maestro assembles LEGO" framing aligns with this; flat MCP-tool listings do not.

7. **Measure the knee yourself.** Since no published curve covers Claude 4.5/4.7 at 10/30/60/120/180 tools, run the ablation internally on HuGR's own benchmark (FinHealth). This would be a publishable contribution, not just product work.

8. **Budget for known failure modes in evaluation.** Specifically measure: (a) hallucinated tool names (Gorilla metric), (b) similar-tool confusion (ToolLLM I2-Cat style), (c) tool-awareness errors (MetaTool metric), (d) parameter hallucination (API-Bank / BFCL metric). These four metrics are the published vocabulary for tool-use failure.

**Uncertainties / where literature disagrees or is silent:**
- No Claude-4.x-specific tool-count-vs-accuracy curve is publicly available.
- Hierarchy-vs-flat at equal N is not cleanly ablated in public work.
- The role of description-token length is folklore, not quantified.
- Primacy/recency effects in long tool manifests are inferred from "Lost in the Middle" but not directly ablated for tool use.

---

## Sources

- **Toolformer** — Schick et al., Meta AI, NeurIPS 2023 — https://arxiv.org/abs/2302.04761 — Self-supervised tool-use training; N=5; foundational but not scale-relevant.
- **Gorilla: LLM Connected with Massive APIs** — Patil et al., UC Berkeley 2023 — https://arxiv.org/abs/2305.15334 — Retrieval-aware training over 1,645 APIs; establishes hallucination as dominant failure at scale.
- **ToolLLM / ToolBench** — Qin et al., Tsinghua 2023 — https://arxiv.org/abs/2307.16789 — 16,464 RapidAPI APIs; retriever + DFSDT; de facto benchmark for scale.
- **API-Bank** — Li et al. 2023 — https://arxiv.org/abs/2304.08244 — 73-API benchmark; closest to HuGR's N.
- **MetaTool** — Huang et al. 2023 — https://arxiv.org/abs/2310.03128 — Tool-awareness + tool-selection benchmark over 199 tools.
- **RestGPT** — Song et al. 2023 — https://arxiv.org/abs/2306.06624 — REST-API agent with coarse-to-fine selection.
- **AnyTool** — Du et al. 2024 — https://arxiv.org/abs/2402.04253 — Hierarchical GPT-4-as-navigator over ToolBench; strongest published evidence that hierarchy helps.
- **ToolACE** — Liu et al. 2024 — https://arxiv.org/abs/2409.00920 — 26k-API synthesis + fine-tuning; 8B competitive with GPT-4 on BFCL.
- **Chameleon** — Lu et al. 2023 — https://arxiv.org/abs/2304.09842 — Plan-first composition; small toolbox.
- **HuggingGPT / JARVIS** — Shen et al. 2023 — https://arxiv.org/abs/2303.17580 — Model-registry as tools.
- **ReAct** — Yao et al. 2022 — https://arxiv.org/abs/2210.03629 — Reasoning+Acting baseline.
- **Reflexion** — Shinn et al. 2023 — https://arxiv.org/abs/2303.11366 — Verbal self-feedback.
- **Tree of Thoughts** — Yao et al. 2023 — https://arxiv.org/abs/2305.10601 — Search over reasoning.
- **Voyager** — Wang et al. 2023 — https://arxiv.org/abs/2305.16291 — Lifelong skill-library agent in Minecraft; core analogue for HuGR.
- **CodeAct** — Wang et al. 2024 — https://arxiv.org/abs/2402.01030 — Code-as-composition beats JSON tool calls.
- **SWE-agent** — Yang et al. 2024 — https://arxiv.org/abs/2405.15793 — Curated agent-computer interface; direct evidence that surface design beats surface size.
- **OS-Copilot / FRIDAY** — Wu et al. 2024 — https://arxiv.org/abs/2402.07456 — Self-improving OS agent.
- **Lost in the Middle** — Liu et al. 2023 — https://arxiv.org/abs/2307.03172 — Long-context position bias; suggestive for tool manifests, not directly ablated.
- **Berkeley Function-Calling Leaderboard (BFCL)** — Berkeley 2024–2025 — https://gorilla.cs.berkeley.edu/leaderboard.html — Live function-calling benchmark; current SOTA reference.
- **Anthropic model cards** (Claude 3.5 / 4 / 4.5 / 4.7) — https://www.anthropic.com/ — Report SWE-bench, τ-bench, MCP evals; do not publish N-tools-vs-accuracy curves.

*End of document. Founder should verify exact numeric claims (marked "approx.") against the linked PDFs before using them in design-defining arguments.*
