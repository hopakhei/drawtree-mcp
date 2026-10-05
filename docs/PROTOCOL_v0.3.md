# Draw Tree protocol v0.3

Status: implemented in `drawtree_mcp/_kernel/` (2026-10-05). Deterministic; no model calls. v0.2 documents keep their legacy semantics (`aggregate_v02`, the 9 invariants); a doc is treated as v0.3 when `drawtree_version` is `"0.3"` or any branch carries `impact_grade`.

## 1. Document shape

```
drawtree_version: "0.3"
ticker, snapshot_date
consensus:        { narrative, implicit_assumptions[], pricing_logic }      # frozen baseline
root:             { id: "H0", question, core_thesis, verdict, narrative_versions{...} }
branches[]:       see §2
hypotheses[]:     see §3  (a list; an id-keyed object is also accepted)
valuation:        { snapshot_price, scenarios{bull|base|bear: {target_price}}, methodology_primary? }
decisions?:       { no_fatal_layer: {reason} }   # persistence trees only
```

## 2. Branch

| field | rule |
|---|---|
| `id` | `^[A-Z]$` |
| `impact_grade` | one of 致命 / 重創 / 明顯受損 / 輕微 / 邊緣. Derived from the largest move (÷ price) the branch's `falsification_consequence` causes in the scenario ladder: ≥25% / 10–25% / 4–10% / 1–4% / <1%. Never authored. |
| `weight` | must equal `IMPACT_GRADES[impact_grade]` = 2.5 / 1.6 / 0.9 / 0.4 / 0.15 (omit it and the engine derives it) |
| `scenario_role` | contains one of 分子交付 (numerator delivery) / 倍數持久 (multiple persistence) / 倍數升級 (multiple upgrade) / 加速器 (accelerator) |
| `necessary_condition` | one sentence of the proposition path |
| `falsification_rule` | which leaves falsify the branch (any leaf / named leaves / all leaves) |
| `falsification_consequence` | non-empty subset of `bear_full, bear_multiple, bear_numerator, bull_numerator, bull_multiple` |
| `framework` | `名稱｜出處（冊名）｜本層量的是什麼` |
| `weight_rationale` | starts with `§1.5 衝擊評級：` and states the price impact |
| `aggregation` | `portfolio` only (`chain` is legacy) |
| `necessity_leaves[]` | leaves whose Falsified verdict kills the branch regardless of weight |
| `leaf_weights{}` | optional per-leaf weights (default 1.0) |

Structure: 3–5 branches; at least one 致命 branch unless `decisions.no_fatal_layer.reason` is declared; at least one 分子交付 branch; every 致命 branch has a leaf with a numeric-metric condition.

## 3. Leaf (`hypotheses[]`, fleet schema `v2.3-ledger`)

| field | rule |
|---|---|
| `id` | `^[A-Z][1-9][0-9]*$`; exactly one parent (first letter, or `parents: [X]`) |
| `title`, `hypothesis_full` | required |
| `verdict` | one of the six states; legacy values rejected |
| `scenario_role` | contains one of `bull 驅動` / `bear 觸發` / `兩者` / `輔助` |
| `leaf_nature` | `machine` (numeric condition) / `judge` / `text` |
| `short_question` | a question of ≤22 characters (weekly summary line) |
| `reading_guide` | one sentence for each of `✅ 已驗證, 🟢 趨向正面, ⚪ 未定, 🟡 趨向負面, 🟠 接近證偽, ✗ 已證偽` |
| `baseline_data[]` | `{text, source_name, url, date}` — non-empty, each with date and a source |
| `conditions[]` | `{cid, kind, text, metric, operator, threshold, unit, window, status, due?, basis?, breach?, superseded?}` |
| `condition_assessments[]` | `{cid, assessment, reason}` — one per condition |
| `evidence_ledger[]` | `{eid, date, text, source_name, url, tier, impact, bears_on[], digest}` — append-only |
| `observations[]` | `{metric, value, date, window, eid?}` — inputs to the sweep |
| `falsification[]` | free text, optional (kept for readers; conditions are authoritative) |

Vocabularies:

- `kind`: falsification / verification / deadline
- `status`: open / breached / met / superseded / expired_unfulfilled
- `operator`: `<  <=  >  >=  ==  qoq_decline  streak_decline`
- `assessment`: not_met / approaching / met / superseded
- `tier`: filing / earnings / trade_press / news / synthetic
- `impact`: supports / challenges / neutral (`contradicts`, `against`, `refutes` map to challenges)

Gates (from the fleet's `tree_quant --check`):

| gate | severity | rule |
|---|---|---|
| E1 | error | enums valid, `cid` unique, metric ⇒ numeric threshold, deadline ⇒ `due` + `basis` |
| E2 | error | a falsification/deadline condition that is breached / expired / met while the verdict is still positive and not superseded |
| E3 | error | such a condition without an entry in `condition_assessments` |
| E4 | error | `superseded` without a reason of ≥8 characters |
| E5 | warning | a falsification-zone verdict with no condition met / breached / expired and none assessed met |
| E6 | warning | dated news / earnings / filing / trade_press evidence without a URL |
| E7 | error | any condition never assessed |

## 4. Aggregation (engine `h0-engine/1`, semantics `tree_quant/4`)

Scores: Validated 2, Trending positive 1, Inconclusive 0, Trending negative −1, Approaching falsification −2, Falsified −3.

Branch: `score = Σ lw·s / Σ lw`; kill if a Falsified leaf has `lw ≥ 2.0` or is in `necessity_leaves`. Verdict: ≥1.5 Validated, ≥0.5 Trending positive, >−0.5 Inconclusive, >−1.5 Trending negative, else Approaching falsification; Falsified only via kill. Branch conviction `σ(logit(0.40) + 1.5·score)`. Branch scores are rounded to 4 decimals before the H-0 step.

H-0: `score = Σ w·score_b / Σ w` with `w = IMPACT_GRADES[grade]`. Kill if a Falsified branch has `w ≥ 2.0`. Verdict guards, in order: Validated needs score ≥1.5 and every branch Inconclusive or better; Trending positive needs ≥0.5 and no branch at Approaching or Falsified; Approaching falsification if score ≤ −1.5 or ≥2 branches are negative; Trending negative if ≤ −0.5; otherwise Inconclusive.

Conviction: `logit(H0) = logit(0.40) + Σ w·(score_b/3)`, each positive term multiplied by 0.5, result clamped to [0.005, 0.95].

Probabilities: verdict-based `p_bull = clip(score/2)`, `p_bear = clip(−score/3)` (renormalised if the sum exceeds 1), `p_base = 1 − p_bull − p_bear`. Price-implied (Max-Base): zero weight on the far scenario, split the rest so `Σ p·target = price`; outside `[bear, bull]` the output is a clamp flagged `infeasible: above_bull | below_bear`.

Expected return: `Σ p·(target − price)/price` for both probability sets.

Certificate: `input_sha256` over branches and leaf verdicts plus the frozen assumptions above; `point_in_time_verified: false` — the certificate proves the derivation, not that evidence was available at the stated date.

## 5. Sweep (`sweep_conditions`)

Deterministic, idempotent. Open `deadline` (or metric-less) conditions past `due` → `expired_unfulfilled`; open scalar falsification conditions whose `observations[]` entry (same metric and window) crosses the threshold → `breached` with a permanent `breach{value, date, eid}`. Each transition appends a synthetic ledger row (`SYN-<cid>-<date>`, tier synthetic, impact challenges).

## 6. Verdict-change gate (`validate_verdict_change`)

Rules 1 (cite a URL from this week's evidence; exemptions recorded), 1b (cited evidence verifiable), 1c (cited eids exist), 1d (evidence direction matches the move), 2 (falsification-zone verdicts quote a real condition), 3 (reason is not price-only). Provenance labels: new_evidence / stale_reread / expiry / none.

## 7. Migration from v0.2 (`migrate_tree`)

Mechanical: weights → impact grades via `{8:致命, 5:重創, 3:明顯受損, 2:輕微, 1:邊緣}` (Fibonacci positions when no explicit weight), `falsification[]` text → `conditions[]` with `metric: null`, `recent_evidence` → `evidence_ledger` (tier news, impact neutral), legacy verdicts → six states, multi-parent leaves keep the first parent. Everything v0.2 never held (roles, necessary conditions, frameworks, reading guides, numeric metrics, price-derived grades) is returned in `todo`; `validate_tree` will not pass until it is supplied.

## 8. Not yet in this repo

Valuation rules R1–R12 (consensus numerator × frozen ratio, tier-median multiples, R5 `bear < price < bull`, R12 snapshot re-basing), the two-decision approval gate, point-in-time provenance fields on commit, and the weekly search/judge separation live server-side and are tracked as follow-up work.
