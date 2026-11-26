# Report F: industry and literature research for the continuity gate

Research agent report, 2026-11-26. Web research only; nothing here was tested on this pipeline.

## Summary

Labels: **[verified]** means I read the primary source this session; **[secondary]** means a search summary or third-party write-up; **[memory]** means prior knowledge, not re-checked. Nothing was tested on this pipeline.

1. **The open checker's recall is already at the published ceiling.** ConStory-Checker reports precision 0.884 and recall 0.550 on injected errors; professional novelists reached about 0.14–0.17 recall on the same set. On FlawedFictions' long split (2,703-word stories), almost every model is near chance, with o1 best at 0.61 accuracy. The gain available is in precision and cost.
2. **No paper compares open-ended and decomposed checking head-to-head on fiction.** Indirect evidence favours a hybrid: an open finder followed by a per-finding verifier. Decomposition loses context and creates ambiguous references, which matches the question checker's blind spots.
3. **Find-then-verify is what code-review systems converged on.** Anthropic Code Review, Cursor Bugbot and ByteDance's BitsAI-CR all use it. BitsAI-CR's ablation is the only one with numbers: precision 57.0% to 65.6%, recall 45.5% to 39.8%. A verifier also lifted Claude 3.5 Sonnet's localisation score from 0.35 to 0.50 on long FlawedFictions stories.
4. **Unioning two runs is the opposite of industry practice.** Bugbot ran eight passes in randomised order and dropped anything found in only one. I found no system that unions without a later filter.
5. **NLI and grounding models do not work for fiction contradiction.** Entailment baselines scored at chance in both FlawedFictions (0.53 and 0.48) and Re3 (0.528 ROC-AUC). They detect "unsupported", not "contradicted".
6. **The possession false positives have a published precedent.** Re3's attribute dictionary produced false positives from attributes that legitimately change, and removing it did not hurt their main metrics.
7. **Retrieval roughly matches whole-book context for local facts.** On NoCha, BM25 at k=50 reached 49.7% against 55.8% for the best full-context model, and beat full context on sentence-level claims (73.3% vs 59.8%). Neither handles global reasoning well.
8. **Literary coreference is weak on full books** (about 47–61 CoNLL-F1 [secondary]). An alias table over the closed cast plus a small-model cast list is my inference, not a tested result.
9. **Pricing changes the question checker's economics.** Claude Haiku 5.5 is $0.10/$0.50 per million tokens under 100K prompt tokens, with a 5x step above that. Batch is 50% off and stacks with caching. Changing a structured-output schema invalidates the prompt cache.
10. **Other "decision model" readings have little support.** Self-rated confidence was near random at Greptile. More reasoning effort was flat or worse for o1 and o3-mini. Solvers and decision tables have no evidence for this task; a cascade (cheap model raises, strong model confirms) is the useful form.

**Ranked techniques** (detail, evidence and effort in the report):

1. Find, then verify each finding with quotes from both sides.
2. Vote across runs, or union only ahead of the verifier.
3. One policy table routing every layer's output; typed-state violations go to the verifier.
4. Alias table plus cast extraction.
5. Retrieval-scoped context for the finder.
6. Seeded-error benchmark with clean controls; shadow mode for new layers.
7. Ledger validity intervals; lift the 30-question cap on Haiku 5.5.
8. Caching and batching discipline.
9. Per-category precision tracking and a memory of rejected findings.
10. Do not build: NLI pre-filter, confidence thresholds, maximum-effort finder, general coreference or a solver.

**Not verified:** current NoCha leaderboard, ConWriter and SCORE numbers, any ablation of two-sided quotes or "could both be true" prompts, Apple Silicon throughput for small models, and Google/Meta code-review work. The 240K-token book size is my estimate.

Researched 2026-11-26. My own inferences are marked **Inference**.

## 1. Narrative and long-document consistency checking

### What the benchmarks say

**FlawedFictions** (Ahuja, Sclar, Tsvetkov, 2025) [verified] — https://arxiv.org/html/2504.11900v3
- Task: does this story contain a continuity error, and where. The main set is 414 stories averaging 731 words, half of them clean. The long split is 200 stories averaging 2,703 words (1,200–4,000), which is this pipeline's scene length.
- Short stories: Claude 3.5 Sonnet is best at 0.76 accuracy, equal to humans (0.76). o1 scores 0.69–0.71 and GPT-4o 0.64.
- Long split: o1 is best at 0.61 accuracy and Claude 3.5 Sonnet scores 0.56. The "always say no error" baseline scores 0.51.
- **A verifier pass helped on the long split.** Claude 3.5 Sonnet's localisation score (CEEval-Full) went from 0.35 to 0.50. On short stories it made no difference (0.67 to 0.68).
- **More reasoning effort did not help** o1 or o3-mini; o3-mini at high effort dropped to 0.07 CEEval-Full on long stories. The exception is Claude 3.7 Sonnet extended thinking, 0.55 to 0.66 on short stories.
- An entailment-model baseline scored 0.53 (short) and 0.48 (long), which is chance.
- The text says humans had higher precision and lower recall than the best models; the table was not readable in my fetch.

**ConStory-Bench / ConStory-Checker** (Findings of ACL 2026) [verified] — https://arxiv.org/html/2603.05890
- Design: category-guided extraction of contradiction-prone spans across five dimensions, then pairwise contradiction judgement, then an evidence chain with quotes anchored to character offsets. The judge model is o4-mini.
- Validation on 200 stories with 1,000 injected errors: **precision 0.884, recall 0.550, F1 0.678**. Human experts scored precision 0.660 and recall 0.139; the paper's text says 17.1%, so it is internally inconsistent.
- Errors concentrate in "Factual & Detail" and "Timeline & Plot Logic". The fact is typically established 15–30% into the story and contradicted at 40–60%.
- There is no ablation against direct open-ended judging.

**NoCha** (Karpinska et al., EMNLP 2024) [verified] — https://arxiv.org/html/2406.16264v3
- Task: whole novel in context, verify one claim. GPT-4o is best in the paper at 55.8% pair accuracy; humans score 97.4%.
- By evidence scope: sentence-level 59.8%, passage-level 47.6%, global reasoning 41.6%.
- **BM25 retrieval plus GPT-4o: 28.2% at k=5, 44.1% at k=25, 49.7% at k=50** (about 17% of the book retrieved). That beat every full-context model except GPT-4o itself. On sentence-level claims retrieval beat full context (73.3% vs 59.8%).
- Speculative fiction with heavy world-building was hardest (38.8% vs 56.4% for historical).
- Claude 3.5 Sonnet labelled false claims correctly 83.5% of the time but true claims only 55.3%. That over-calling of "false" is the false-alarm direction for a contradiction checker.
- Newer results are on the leaderboard (https://novelchallenge.github.io/, updated July 2025), but the table did not render. **Not verified.**

**ContraDoc** (NAACL 2024) [secondary] — https://arxiv.org/abs/2311.09182 — GPT-4 was best but unreliable on self-contradictions in 300–2,200-token documents. Factual contradictions were found far more reliably than ones about emotion or perspective.

### Generation systems with consistency components

**Re3** (Yang et al., EMNLP 2022) [verified] — https://ar5iv.labs.arxiv.org/html/2210.06774
- This is the closest published ancestor of the fact ledger. It keeps a per-character attribute dictionary, checks new passages only against the dictionary, and uses an entailment model to flag contradictions on the same attribute key.
- Controlled detection test: ROC-AUC 0.528 for plain entailment, 0.610 with retrieval, **0.684 for the structured dictionary**. The authors call absolute performance low.
- Stated false-positive source: **attributes that legitimately change over time.** Stated blind spot: non-character facts such as setting and current scene.
- Ablation: removing the Edit module did not hurt the main metrics. The authors say it "does not improve our main metrics".

**SCORE** (2025 preprint) [secondary] — https://arxiv.org/abs/2503.23512 — tracks item state as active/lost/destroyed and flags reappearance, with hybrid TF-IDF and embedding retrieval of episode summaries. Abstract claims vary between versions and I found no precision or recall for the detector. Evidence quality is low.

**ConWriter** (2026 preprint) [verified, abstract only] — https://arxiv.org/abs/2608.05169 — scene-by-scene generation with symbolic state tracking and transition checks, where risk signals decide what to validate. It claims to beat DOME on ConStory-Bench. The abstract has no numbers and the PDF was not readable.

**DOC** (detailed outline control) was not researched.

### Memory graphs and writing products

- **Zep/Graphiti** [secondary] — https://arxiv.org/abs/2501.13956 — a bi-temporal knowledge graph where a contradicting fact invalidates the older edge with a timestamp. It is benchmarked on conversational memory, not contradiction detection. The transferable idea is validity intervals on facts.
- **Sudowrite** [secondary] — https://docs.sudowrite.com/using-sudowrite/1ow1qkGqof9rtcyGnrWUBS/what-is-story-bible/jmWepHcQdJetNrE991fjJC — Story Bible plus Chapter Continuity (prior chapters in context). I found no dedicated checker; their blog suggests asking chat to look for inconsistencies.
- **NovelCrafter Codex, NovelAI Lorebook, GraphRAG for fiction, game narrative state** were not verified. From memory, the first two are keyword-triggered context injection, and narrative game engines hold authoritative state in explicit variables. I know of no published accuracy figures.

### Translation to this system

- **Inference:** checker A at 0.5–0.57 recall and checker B at 0.53–0.56 on asked facts are both at the published ceiling for a single pass. Effort is better spent on precision and coverage than on a better single judge.
- **Inference:** Re3's finding matches the possession result here. A typed-state diff cannot tell "the state changed in this scene" from "the scene contradicts the state". Typed-state violations should become candidates for a verifier, not direct rewrite triggers.
- **Inference:** validity intervals fix the same problem in the ledger. Each fact gets "true from scene X until scene Y", so a superseded fact is not asked about.

## 2. Fact verification and small grounding models

### Decompose-then-verify vs holistic

**Decomposition Dilemmas** (2024 preprint, small datasets) [verified] — https://arxiv.org/html/2411.02400v2
- Decomposition helps weak verifiers and long inputs. It **hurts strong verifiers on already-atomic claims**: MiniCheck on WICE scores 80.0 balanced accuracy undecomposed and 71.1 with FActScore-style decomposition.
- The errors it introduces are lost context, ambiguous references, over-fragmentation and altered meaning.
- A reflect-and-repair step on the decomposition recovered most of the loss.

Related pipelines all use decompose, retrieve, verify:
- FActScore — https://arxiv.org/abs/2305.14251 [memory]
- SAFE — https://arxiv.org/abs/2403.18802 [memory]
- VeriScore — https://arxiv.org/abs/2406.19276 [secondary]
- Chain-of-Verification — https://arxiv.org/abs/2309.11495 [memory]
- RARR — https://arxiv.org/abs/2210.08726 [memory]

They measure support against a reference corpus, which is a different task from contradiction against prior narrative.

**Inference:** checker B's blind spots (facts with no subject, epithets, wrong names) are the "lost context" and "ambiguous reference" errors this paper names. They belong to decomposition as a method, not to the Haiku judge.

### Small grounding models

LLM-AggreFact leaderboard [verified] — https://llm-aggrefact.github.io/

| Model | Score | Size |
|---|---|---|
| Top entry (nimble-v4-max) | 79.5 | 27B |
| Bespoke-MiniCheck-7B | 77.4 | 7B |
| Claude 3.5 Sonnet | 77.2 | — |
| Granite Guardian 3.3 | 76.5 | 8B |
| GPT-4o (2024-05) | 75.9 | — |
| FactCG-DeBERTa-L | 75.6 | 0.4B |
| MiniCheck-Flan-T5-L | 75.0 | 0.8B |

The newest frontier model on the board is Claude 3.5 Sonnet, so it says nothing about current models.

- **Bespoke-MiniCheck-7B** [verified] — https://huggingface.co/bespokelabs/Bespoke-MiniCheck-7B — 32K-token context, over 500 documents per minute on one A6000 GPU with vLLM, licence CC BY-NC 4.0. Mac support is not stated; it is on Ollama (https://ollama.com/library/bespoke-minicheck) [secondary].
- **HHEM-2.1-Open** (Vectara) [verified] — https://huggingface.co/vectara/hallucination_evaluation_model — Flan-T5-base, about 0.1B parameters, under 600 MB RAM, about 1.5 s for a 2k-token input on a CPU, unlimited context, Apache-2.0. It runs on any Mac.
- **ModernBERT NLI** (tasksource) [secondary] — https://huggingface.co/tasksource/ModernBERT-large-nli — Apache-2.0. I did not confirm the 8,192-token window or MPS throughput.
- **Patronus Lynx, Azure groundedness detection, Google check-grounding** were not researched beyond names.

### Are they usable for fiction contradiction?

No.
- FlawedFictions' entailment baseline scored 0.53 and 0.48 accuracy, and Re3's scored 0.528 ROC-AUC. Both are chance. [verified]
- These models answer "is this claim supported by this document". HHEM's card shows "I visited Iowa" flagged as unsupported given "I visited the United States".
- **Inference:** every new detail in a scene is "unsupported" by earlier text, so they would flag nearly everything. They do not separate "not established" from "contradicted".
- **Inference:** the same applies to source fidelity. A faithful retelling legitimately adds invention, so only "contradicts Butler" is an error. That needs an LLM judge given the mapped source passage.

**Recommendation: do not add an NLI pre-filter.**

## 3. "Modern decision models": five readings

| Reading | Evidence for consistency checking | Verdict |
|---|---|---|
| (a) Encoder classifiers (ModernBERT etc.) | Chance on stories off the shelf. Greptile's largest gain came from an embedding filter over past accepted/rejected findings (section 4). | Useful only as a learned filter over the checker's own past findings, once a few hundred are labelled. |
| (b) DMN / decision tables | None found for narrative. | Useful as a discipline: one explicit table saying which finding type from which layer triggers a rewrite, a verify, or a log entry. |
| (c) Symbolic: LLM extracts, solver checks | Bedrock Automated Reasoning claims "up to 99%" only for unambiguous translation into logic [secondary, vendor]. Logic-LM and LINC show gains on formal logic puzzles [memory]. Re3 and the possession result show extraction is the weak link. | Keep to a few hard invariants with clean extraction (dead stays dead, calendar moves forward, one place at a time). |
| (d) Cascades and routers | FrugalGPT claims up to 98% cost reduction with a learned stop rule [secondary]. RouteLLM keeps about 95% of GPT-4 quality on MT-Bench with a fraction of GPT-4 calls [secondary]. Neither was tested on consistency checking. | The useful form is a cascade: cheap model raises, strong model confirms. |
| (e) Reasoning models as judges | FlawedFictions: more effort was flat or worse for o1/o3-mini, a gain for Claude 3.7 [verified]. ConStory-Checker reached 0.884 precision with o4-mini [verified]. | Moderate effort; do not pay for maximum on the finder. |

Sources for the table:
- Bedrock — https://aws.amazon.com/blogs/aws/minimize-ai-hallucinations-and-deliver-up-to-99-verification-accuracy-with-automated-reasoning-checks-now-available
- Logic-LM — https://arxiv.org/abs/2305.12295
- LINC — https://arxiv.org/abs/2310.15164
- FrugalGPT — https://arxiv.org/abs/2305.05176
- RouteLLM — https://arxiv.org/abs/2406.18665

**Most likely useful reading: (d) as a cascade, with (b) as the explicit policy table.**

## 4. Judge reliability and the code-review analogue

### What published systems do

**Anthropic Code Review** [verified] — https://code.claude.com/docs/en/code-review.md and https://claude.com/blog/code-review
- Four stages: several agents find in parallel; a verification step checks each candidate against the code and drops false positives; findings are deduplicated and ranked by severity; the review posts.
- Scope is deliberately narrow: correctness bugs, not style.
- Self-reported: under 1% of findings marked incorrect by engineers, at $15–25 and about 20 minutes per review. VentureBeat notes ignored findings are not counted as incorrect [secondary] — https://venturebeat.com/ai/anthropic-rolls-out-code-review-for-claude-code-as-it-sues-over-pentagon

**Cursor Bugbot** [verified] — https://cursor.com/blog/building-bugbot
- Early pipeline: **eight parallel passes with the diff in randomised order, bucket similar findings, majority vote to drop findings seen in only one pass**, merge, filter unwanted categories, **validator model to catch false positives**, dedupe against earlier runs.
- It later moved to an agentic finder with **aggressive** prompts ("err toward flagging"), because a restrained finder became too cautious.
- Resolution rate went from 52% to over 70%. They ran 40 major experiments, many of which regressed, evaluated offline on a curated benchmark and online on resolution rate.

**BitsAI-CR (ByteDance)** [verified] — https://arxiv.org/html/2501.15134v1
- Finder then filter. Finder alone: precision 57.0%, recall 45.5%. With filter: **precision 65.6%, recall 39.8%**. The paper's text quotes other figures; I used the table.
- Filter prompt format mattered: conclusion-first gave 77.1% precision, and reasoning-first gave 65.8% at 18 times the latency.
- Removing rules whose findings developers rarely acted on raised the acted-on rate from about 15% to 26.7%.

**Greptile** [verified] — https://www.greptile.com/blog/make-llms-shut-up
- Baseline: 19% of comments good, 2% wrong, **79% true but unwanted**.
- Failed: prompting to be less nitpicky (lost good comments too), few-shot examples (made it worse), and **asking the model to self-rate severity 1–10 (ratings were nearly random)**.
- Worked: embed past comments with their accept/reject outcome, and block a new comment similar to at least three rejected ones. Addressed rate went from 19% to over 55%.

**Static-analysis false-positive triage with LLMs** [secondary]
- Tencent: 94–98% of false alarms eliminated at high recall — https://arxiv.org/html/2601.18844v1
- LLM4PFA: 72–96% filtered, 42 of 45 real bugs kept — https://arxiv.org/pdf/2506.10322

**PoLL, panels of diverse judges** [secondary] — https://arxiv.org/abs/2404.18796 — a three-model panel correlated better with humans than one large judge at about one-seventh the cost. The evidence is on QA grading.

Google and Meta code-review work was not researched.

### Answers to the specific questions

- **Does a second verification pass cost recall?** Yes, a little. BitsAI-CR lost about 6 points of recall for about 9 of precision. FlawedFictions' verifier improved the combined score on long stories.
- **Voting vs union.** Bugbot votes. FlawedFictions kept an injected error only when a judge flagged it in at least 4 of 5 samples. **Inference:** union-of-two raises recall and false alarms together, and is defensible only as candidate generation ahead of a verifier.
- **Confidence scores.** Greptile found self-rated severity near random. Prefer binary decisions with evidence.
- **Verbatim quotes from both sides.** ConStory-Checker anchors both spans to character offsets and reports 0.884 precision, but did not ablate the requirement. **Inference:** checker B checks the scene-side quote only; checking the earlier-side quote against stored text is cheap and catches a misremembered earlier fact.
- **"Could both be true?"** No direct study found. Re3 names legitimate change over time as the dominant false positive, which is what the question tests. **Inference only.**
- **Debate / prosecutor–skeptic.** No evidence found either way.
- **Position bias.** Bugbot randomises input order across passes. ConStory finds contradictions cluster mid-story.

## 5. Cost and latency engineering (late 2026)

### Prices [verified] — https://platform.claude.com/docs/en/about-claude/pricing

| Model | Input | Output | 5-min write | 1-hour write | Cache read |
|---|---|---|---|---|---|
| Claude Opus 5.5 | $4 | $20 | $5 | $8 | $0.20 |
| Claude Sonnet 5.5 | $2 | $10 | $2.50 | $4 | $0.10 |
| Claude Haiku 5.5, prompt up to 100K tokens | $0.10 | $0.50 | $0.125 | $0.20 | $0.01 |
| Claude Haiku 5.5, prompt over 100K tokens | $0.50 | $2.50 | $0.625 | $1 | $0.05 |
| Claude Haiku 4.5 | $1 | $5 | $1.25 | $2 | $0.10 |

Prices are per million tokens. Batch is 50% off all of these and stacks with caching.

- **Haiku 5.5 is 10 times cheaper than Haiku 4.5 below 100K prompt tokens and has a 5x price step above it.** Cache reads count toward prompt length.
- Claude 4.7 and later use a tokenizer that produces about 30% more tokens for the same text.

### Caching

Sources: the pricing page above, plus Anthropic's bundled API reference for https://platform.claude.com/docs/en/build-with-claude/prompt-caching (the live page was not re-fetched).

- Writes cost 1.25x (5-minute) or 2x (1-hour). Reads cost 0.1x, or 0.05x on Opus 5.5 and Sonnet 5.5. A read refreshes the timer for free.
- Caching is a prefix match in the order tools, system, messages. Any byte change invalidates everything after it.
- Changing the tool set or the model invalidates everything. Changing thinking or effort settings invalidates at least the messages cache.
- **Changing the structured-output schema invalidates the prompt cache for that thread**; compiled schemas are cached for 24 hours [verified] — https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- For parallel fan-out, a cache entry is readable only once the first response has started. Send one request, wait for its first token, then send the rest.
- There are up to 4 breakpoints, and the minimum cacheable prefix is 512 tokens on current models.
- Context editing rewrites the cached prefix, so it is a context-window tool and not a savings lever.

### Batches [verified] — https://platform.claude.com/docs/en/build-with-claude/batch-processing

- 50% off. Most batches finish within 1 hour, with a hard expiry at 24 hours and no SLA. Results come back in any order.
- Cache hits inside a batch are best-effort; the docs recommend the 1-hour TTL for batches with shared context.
- A batch request is single-shot, so no tool loops.

### Whole book cached vs retrieval

- **Inference (token count estimated):** 140,000 words is roughly 240K tokens on the current tokenizer. A whole-book prefix late in the run costs about $0.60 to write and $0.024 to read on Sonnet 5.5, and about $1.20 and $0.05 on Opus 5.5. If scenes arrive more than an hour apart, every check pays the write.
- **Inference:** a retrieval-scoped check (bibles, ledger and the 20–50 most relevant earlier passages, perhaps 30–60K tokens) stays under Haiku 5.5's 100K step and has a flat cost per scene.
- Long-context evidence is NoCha above [verified] and Chroma's context-rot report, which finds degradation with length and with topically similar distractors across 18 models [secondary, vendor] — https://research.trychroma.com/context-rot. **Inference:** a 92-scene war narrative with many near-identical duels is close to the worst case for similar distractors.
- **Contextual retrieval** [secondary] — https://www.anthropic.com/engineering/contextual-retrieval — prepending a short generated context to each chunk and combining embeddings with BM25 cut top-20 retrieval failures by 49%; a reranker took that to 67%. Fiction was one of the tested domains.

### Incremental re-verification

I found no narrative-specific evidence. **Inference** from incremental static analysis and test-impact selection: after a rewrite round, re-run only the findings that triggered it and the checks whose evidence quotes overlap changed sentences. Run the full gate once at acceptance.

## 6. Programmatic methods

- **Literary coreference is not good enough to rely on.** BookCoref (ACL 2025) [secondary] — https://arxiv.org/abs/2507.12075:
  - LitBank documents are truncated to about 2,000 tokens.
  - On full books, off-the-shelf systems score about 46.6 CoNLL-F1 (Longdoc), with BookNLP and Maverick close behind, and 61–67 after training on silver data.
  - On LitBank-length text the figure is about 78–80 [secondary] — https://arxiv.org/pdf/2510.15594.
- LLM-based coreference "has yet to reach the performance of supervised models" on benchmarks [secondary] — https://arxiv.org/html/2509.17796v2.
- I found **no direct comparison** of a coreference model against a small LLM asked "who is present, under which names".
- **Inference:** this book has a closed cast and a name map, so the task is entity linking against a known list, not open coreference.
  - A gazetteer of names, epithets and patronymics handles explicit mentions deterministically.
  - A small LLM handles the residue, such as "the son of Tydeus" when two candidates exist.
  - Epithets shared by several characters must be marked ambiguous in the table, not guessed.
- Typed state machines are covered by Re3 and SCORE in section 1. Detection quality is bounded by extraction quality.

## 7. Evaluation practice

- **Seeded-error sets.** FlawedFictionsMaker [verified] picks an established fact, negates it, rewrites later text to match, splices with the original opening, filters with a judge, and confirms with humans. About 70% of injections survived human review. ConStory validated on 1,000 injected errors [verified].
- **Clean items.** FlawedFictions is half unmodified stories, which is what exposes over-flagging. The 75% clean-scene stop rate here is the equivalent number and should be a headline metric.
- **Online proxy metrics.** Bugbot uses resolution rate (was the finding fixed) and BitsAI-CR uses outdated rate (were flagged lines changed). **Inference:** the equivalent here is whether the rewrite changed the quoted sentence and the finding disappeared on re-check without a new one appearing.
- **Per-category pruning.** BitsAI-CR tracks precision per rule over a 14-day window and removes rules below threshold [verified].
- **Offline plus online.** Bugbot ran 40 experiments against both, and many plausible changes regressed [verified].
- **Shadow mode.** I found no citable study; it is standard practice. **Inference:** every new layer should log findings without triggering rewrites until its measured precision clears a bar.
- **Cost per true catch.** No published figures found; it is computable from the existing ledger.

## Ranked: the most transferable techniques

Effort: S is under a day, M is a few days, L is a week or more. Effects are my estimates unless a number is cited.

**1. Find, then verify each finding separately.**
- What: keep an open, recall-oriented finder. Send each candidate to a fresh verifier call that sees only the candidate, the earlier passage and the scene passage. It must return confirm or reject with a verbatim quote from each side, both checked programmatically. Ask whether both statements can be true (time passed, state changed in this scene, different referent, figurative speech).
- Evidence: Anthropic Code Review, Bugbot, BitsAI-CR (precision +9, recall −6), FlawedFictions verifier (0.35 to 0.50 on long stories), static-analysis triage. URLs are in section 4. The both-sides quote and "could both be true" parts are inference.
- Effect: false alarms down substantially, recall down a few points, cost up by one small call per candidate.
- Effort: M.

**2. Stop unioning two runs; vote, or union only ahead of the verifier.**
- What: either require a finding in at least 2 of 3 passes with context order varied, or keep the union strictly as candidate generation for technique 1.
- Evidence: Bugbot's majority vote over 8 randomised passes; FlawedFictions' 4-of-5 filter.
- Effect: fewer false alarms, recall unchanged or slightly down, cost neutral in the union-plus-verifier form.
- Effort: S.

**3. Route every layer's output through one policy table.**
- What: typed-state violations, ledger questions and open findings all become candidates with a type and a source layer. A table says which combinations trigger a rewrite, which go to the verifier, and which are logged. Possession diffs go to the verifier, not straight to rewrite.
- Evidence: Re3's false positives from changing attributes and its null ablation; this pipeline's possession result. The table itself is inference.
- Effect: removes the known false-positive source without discarding the signal.
- Effort: S–M.

**4. Alias table plus cast extraction, replacing subject matching.**
- What: a gazetteer mapping every name, epithet and patronymic to a canonical character, with ambiguous epithets marked. Link scene mentions deterministically, and use one small-model call to list who is present and under what names for the residue. Use the result to select ledger facts and to catch wrong-name errors.
- Evidence: BookCoref shows general coreference is weak on full books. The closed-cast argument is inference.
- Effect: recall up on checker B's stated blind spots at near-zero cost.
- Effort: M.

**5. Retrieval-scoped context for the open finder.**
- What: bibles and calendar in a cached prefix, then the passages retrieved for this scene's cast, objects and places (alias-expanded BM25 plus embeddings), plus the previous scene in full.
- Evidence: NoCha (BM25 k=50 at 49.7% vs 55.8% for the best full-context model, and better on local facts); contextual retrieval (−49% retrieval failures); Chroma context rot.
- Effect: cost per check stops growing with book length. Local-fact recall is likely equal or better; global-reasoning errors are not helped. Run a whole-book pass per act as a backstop.
- Effort: M–L.

**6. Seeded-error benchmark with clean controls, and shadow mode for new layers.**
- What: inject errors into accepted scenes by the FlawedFictionsMaker recipe, by category (death, wound, place, object, time, posture, name, source deviation). Keep an equal number of clean scenes. Report recall per category, clean-scene stop rate and cost per true catch for each layer.
- Evidence: FlawedFictions, ConStory, Bugbot's offline benchmark and 40 experiments.
- Effect: makes every other change measurable. The existing labelled set already covers part of this.
- Effort: M.

**7. Give ledger facts validity intervals and lift the question cap on Haiku 5.5.**
- What: each fact carries the scene it became true and the scene it stopped, and only live facts become questions. At $0.10/$0.50 per million tokens the 30-question cap is no longer a cost constraint. Send a "yes" to the technique-1 verifier instead of asking twice and requiring agreement.
- Evidence: Graphiti's edge invalidation (design idea only); the pricing page; FrugalGPT-style cascade. The recall effect is inference.
- Effect: recall up on asked facts, false alarms held by the verifier, cost still cents.
- Effort: S–M.

**8. Caching and batching discipline.**
- What: fixed prefix order (tools, bibles, calendar, retrieved context, scene), fixed output schema, pinned effort. Warm with one request and fan out after its first token. Use the 1-hour TTL when checks on the same prefix are 5–60 minutes apart. Use the Batch API for ledger extraction and benchmark runs, never for the blocking gate. Keep Haiku 5.5 prompts under 100K tokens.
- Evidence: Anthropic pricing, batch and structured-output docs (section 5).
- Effect: no quality change; roughly halves non-blocking spend and removes repeated prefix cost.
- Effort: S.

**9. Per-category precision tracking and a memory of rejected findings.**
- What: log every finding with its category, layer and outcome (confirmed, rejected by verifier, reverted by the author). Demote categories whose precision stays low. Once a few hundred outcomes exist, block new findings that closely match several rejected ones.
- Evidence: BitsAI-CR rule pruning (acted-on rate 15% to 26.7%); Greptile's embedding filter (19% to 55%).
- Effect: false alarms fall over time, but it needs data first.
- Effort: S to log, M for the filter.

**10. Things the evidence says not to build.**
- An NLI or grounding-model pre-filter (chance on stories in two papers).
- Self-rated confidence thresholds (near random at Greptile).
- Maximum reasoning effort on the finder (flat or worse in FlawedFictions).
- A general coreference model or a logic solver ahead of fixing extraction.

## Not verified or not found

- Current NoCha leaderboard numbers for 2025–26 models.
- ConWriter's numbers and its symbolic/LLM split; SCORE's detector accuracy.
- Any head-to-head of open-ended vs decomposed contradiction finding on fiction.
- Any ablation of two-sided quote requirements, "could both be true" prompts, or debate-style adjudication for contradiction detection.
- ModernBERT NLI context length; Apple Silicon throughput for any of the small models; Lynx, Azure and Google grounding services.
- Google and Meta code-review papers, CodeRabbit internals, DOC, NovelCrafter, NovelAI, GraphRAG for fiction, and game-industry practice.
- The 240K-token book estimate; derive it with the token-counting endpoint.
