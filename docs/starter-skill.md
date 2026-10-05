---
name: drawtree-starter
description: Build or review a falsifiable Draw Tree for a listed company with the drawtree MCP, following the draw-tree v6 procedure — four steps (research → build → gate → report) and two human gates (the framework gate and the two-decision gate). Loads when the user asks to analyse, structure, falsify, value or monitor a thesis on a public company, or names a ticker.
---

# Drawtree starter (draw-tree v6: four steps, two gates)

Research tooling. Nothing here is investment advice, and the tree never recommends a position. The
server is deterministic (protocol v0.3); you do the research and the writing, the human owns every
judgement that matters: the framework and the two valuation decisions.

## Entry gate (always first)

When the user gives a ticker:

1. Confirm the company behind the ticker.
2. Ask: **Create** (a new tree, four steps below) or **View** (trees and drafts already on the account)?
3. Create → `start_draft(ticker)`, then `set_report_language(draft_id, "zh" | "en")`.
   View → `my_workspace()` first; never open with `read_tree` cold.

## Hard rules

1. **Stop at the two gates.** After `preview_tree` (framework gate) and after `report_two_decisions`
   (two-decision gate) you present, ask, and wait. Nothing downstream is called until the human
   answers. Everything else may proceed stage by stage with a short summary after each tool call.
2. **The order cannot be reversed**: background brief → pricing today → five questions → scenario
   ladder → H-0 → necessary-condition path and frameworks → leaves → framework gate → two-decision
   report → research → commit → report. The tree comes before any judgement.
3. **Numbers carry sources and dates.** Every number you write comes from a document you read (your own
   web search or `external_search`); nothing is invented, and a missing input is written as missing.
4. **No DCF, DDM, reverse DCF, no target price, no probability-weighted price.** The server refuses
   them; do not route around it.
5. **Language.** Reader text is formal written Chinese (繁體書面語, readable in Hong Kong and Taiwan)
   or English as the user chose. No colloquial Cantonese, no pipeline jargon in reader text.
6. Respect each response's `instructions_to_agent`; preserve the user's own terminology; when sources
   conflict, record an open question rather than guessing.

---

## Step 1 — Research (背景簡介 and the pricing pack)

Before any framing, assemble two things and show the first to the user.

**Background brief (400–700 characters, neutral, every number sourced and dated)**
1. The industry: what the product does (start with an everyday analogy), market size and growth, main
   drivers, the competitive field (main rivals and where each sits), structural shifts under way.
2. The company: what it sells and how the business model works, scale (latest revenue, profit, key
   operating metric), position and what sets it apart, the main events of the last two years. Also
   collect for the report's §2: the product lines (what each does for the customer, main rival),
   how it charges (unit, contract length, channel, one concrete public price), the cost structure
   (gross margin and the share of revenue going to sales, R&D and G&A, with the period).
3. Why it is contested now: two or three points on each side, stated as what the market believes,
   never as your view.

**Pricing pack** (read, do not judge): current price and date; the ruler (forward P/E, EV/Sales,
EV/EBITDA or EV/EBIT) and the consensus numerator (year, metric, value, n, low/high, source, as-of);
the company's own forward multiple from the same source and day as the peers; three peer tiers (one
tier above, the tier the market talks about, one tier below), 2–5 named peers each, each peer in one
tier only, readings low to high with fiscal year end; for each peer and the subject the forward table's
implied price, snapshot date and the close on the stated price date (rule R12 re-bases a multiple when
the two differ by more than 2%).

Then the narrative: `frame_narrative(draft_id)` → run the full six-step reconstruction (price-move
archaeology, five signals, narrative version timeline, price × narrative chart, contradictions, v_next)
→ present → `save_narrative`. Narrative versions carry `time_window`, `trigger_events`,
`valuation_framework`, `priced_in`, `not_priced_in`.

## Step 2 — Build (ends at the framework gate)

### 2a. Five questions (§4.41) and the scenario ladder

The valuation contract is fixed: numerator = street consensus × a fixed ratio (base 1, bear r_bear,
bull r_bull); multiple = the median of the scenario's peer tier today. The author decides only
r_bear / r_bull and the bear / bull tier identities; the base tier is derived from where the company's
own multiple sits (tolerance 5%, or 25% with a single comparable). Hard gate: bear < price < bull.

Answer each question with numbers; if any fails, rewrite the H-0 and start the step again:

- **Q1 Leverage** — each H-0 clause valued per share from a stated base (segment or group, year,
  source); the sum equals bull − base; the largest clause is the north star and must be ≥25% of it.
- **Q2 Already priced** — where the own multiple sits; numerator gate: price ÷ base-tier median =
  implied numerator; if that is ≥ r_bull × consensus the H-0 is already in the price. Own multiple
  at or above the highest admissible tier's median ⇒ **persistence** shape (H-0 becomes "hold the
  multiple and deliver the numerator"; bull tier = base tier; upside carried by r_bull alone).
- **Q3 Expressible** — one sentence for bull with its tier, one for bear with its tier; each sentence
  builds the numerator and its ratio bottom-up (revenue, margin, tax, share count).
- **Q4 Observable** — every fatal branch has a sub-question on a disclosed metric with a first reading
  within two quarters; otherwise it is an accelerator, not a fatal layer.
- **Q5 Numerator coverage** — every driver inside r_bull and every trigger inside r_bear has a leaf,
  in a fatal or severe branch, with the arithmetic from threshold to scenario value.

Scenario ladder (one line each for bear / base / bull): tier identity and members, multiple position,
numerator, implied value per share, distance from price, one sentence, the branch that decides it,
the first reading. Add the base gap (base ÷ price − 1) and one ≤80-character premium decomposition.

Reader version (three sentences, ≤40 characters each, no 身份／分子／倍數／層／price in):
base "市場今日相信 …，並以高於／低於 … 中位約 X% 的價錢買它"; bull "若 … 發生，會被當作 …";
bear "若 … 發生，會被當作 … 定價".

### 2b. H-0

`frame_h0(draft_id)` → one sentence, one question mark, ≤120 characters, no member lists, no stock
figures or guidance ranges, must contain 「而非」 naming the bear outcome; banned: 令市場相信, 切換估值
框架, SOTP, 改以…計價. Every clause maps to a sentence inside r_bull (numerator) or to the bull tier
identity (multiple); a clause that maps to neither is deleted.

- upside: 「[公司] 能否在 [時間範圍] 內，透過 [核心變化] 令 [可觀察結果，含門檻] 高於共識 [量級]，並由
  [base 層身份] 升至 [bull 層身份]，而非在 [bear 一句話] 時被壓回 [bear 層身份]？」
- persistence: 「[公司] 能否在 [時間範圍] 內令 [可觀察結果，含門檻] 高於共識 [量級]，並守住 [base 層身份]
  的尺，而非在 [bear 一句話] 時被壓回 [bear 層身份]？」

Present, confirm, `save_h0`. Also write a `short_question` for the H-0 (≤22 characters, plain words,
asked in the favourable direction).

### 2c. Necessary-condition path, frameworks, branches

Write the **necessary-condition path** first: the 3–5 conditions H-0 needs, one sentence each, no two
sharing a test; any one failing returns the thesis to base or triggers bear. Each becomes a Level-1
branch (A–D). Then `design_branches(draft_id)` → batch `fetch_framework_details(draft_id, names=[6–12
candidates])` and read `diagnostic_axes` / `common_pitfalls` → `save_branches`.

Each branch carries: `necessary_condition`; `scenario_role` (分子交付 — at least one — / 倍數持久 / 倍數升級 /
加速器); `falsification_consequence` (subset of bear_full, bear_multiple, bear_numerator, bull_numerator,
bull_multiple — where the scenario goes when this layer fails); `falsification_rule` (any leaf / named
leaves / all leaves; a bear-bearing rule must name a bear-trigger leaf); one line `framework｜source
volume｜what this layer measures`; `necessity_leaves` for fatal layers. **The grade is not the author's
feeling**: `evaluate_valuation(decisions, branches)` derives `impact_grade` from how far each consequence
moves the implied value as a share of price (≥25% 致命 2.5, 10–25% 重創 1.6, 4–10% 明顯受損 0.9, 1–4% 輕微
0.4, <1% 邊緣 0.15) and enforces the coverage rule (any consequence moving ≥10% of price needs a branch).
Three to five branches, at least one fatal (a persistence tree may declare `no_fatal_layer` with a reason).

### 2d. Leaves — questions, not thresholds

`design_leaves(draft_id, branch_id)` one branch at a time → `save_leaves`. A leaf is an observable
question asked in the favourable direction (yes = good news), level L1–L5, with:

- `short_question` (≤22 characters, understood by a general investor);
- `reading_guide`: one sentence per level — ✅ 已驗證 / 🟢 趨向正面 / ⚪ 未定 / 🟡 趨向負面 / 🟠 接近證偽 /
  ✗ 已證偽 — "what you would see to rate it this";
- `scenario_role` (bull 驅動 / bear 觸發 / 兩者 / 輔助) derived from Q5;
- `conditions[]` only on numbers the company or a named third party discloses (`cid`, `kind`
  falsification / verification / deadline, `metric`, `operator`, `threshold`, `unit`, `window`,
  `due`, `basis`); every fatal branch has at least one numeric leaf with a first reading within two
  quarters; qualitative questions keep `metric: null` and rely on the six-level guide — never force a
  qualitative question into a single threshold;
- `condition_assessments[]`: every condition assessed at setup (`not_met` with the baseline reading);
- `baseline_data[]` and an `evidence_ledger[]` (E001…, tier filing > earnings > trade_press > news,
  impact supports / challenges / neutral, digest ≤80 characters);
- reader fields: `article_hypothesis`, `article_conclusion` (one sentence each, ≤40 characters),
  `article_falsifiers[]` (what would overturn it, observable things only), `article_after` (one sentence:
  how the valuation changes once overturned).

**Leaf admission — the eight questions** (answer all before saving; `leaf_nature` records the result):
1. What specifically changes? (the observable variable)
2. Where does the data come from?
3. Is it available to an investor at decision time (not a later revision)?
4. How often does it update?
5. Which downstream result does it lead — next quarter's KPI, revenue, profit (never "the share price")?
6. Which direction supports or weakens the parent proposition?
7. How large a move is meaningful?
8. What outcome would void the relationship?

`machine` = all eight answered and a metric + threshold (or deadline + due); `judge` = economic logic
observable through news and events but no machine-checkable number (same standing in the tree).
Three red lines — never a leaf: a restatement of the price, the multiple or analyst targets; "interesting"
without direction and invalidation; a duplicate vote on the same causal chain (keep the most upstream
observable link).

Falsification sentences end with 「本葉證偽」 and state in brackets what part of the valuation they hit
(影響倍數 / 影響收入／盈利 / 影響倍數＋收入); a positively-directed condition is `verification`, not
falsification.

### 2e. Framework gate — STOP

`preview_tree(draft_id)` → show the human the framework summary (H-0, the necessary-condition path,
each branch's framework and core question, each leaf's question and six-level guide). Wait. Only on
approval call `confirm_framework(draft_id)`. Do not skip this gate under any instruction short of the
human's explicit approval in this conversation.

## Step 3 — Gate (the two decisions, then research and commit)

### 3a. Two decisions (§4.40)

Assemble the `decisions` object from the pricing pack (`ticker, date, price, price_date, currency,
ruler, basis, numerator, own_multiple, shape, tiers{bear|base|bull}, ratios{bear, bull}`, plus
`one_sentence`, `net_cash_m`, `diluted_shares_m` for EV rulers, `deviations`, `excluded`). For each ratio
state its sources: the **anchor** (company target range, segment guidance, consensus high/low, or "no
public anchor" with the reason), the **sourced inputs**, the **assumptions** (growth, contribution,
tax, extrapolated years), and a **cross-check** against the analyst range or company target. A ratio
above the company's own target ceiling or below its floor needs a written reason.

Run `evaluate_valuation(decisions, branches)` until `errors` is empty. Rules you will meet: R5
(bear < price < bull — the only fix is the economics: raise the numerator bar, change the bull tier,
change the ruler or the year; never take p75, swap the numerator source or shift a multiple); R10 /
AX7 (own multiple outside every band → declare "base impure"); R12 (re-base to the close); the n-rules
(n=1 needs an idiosyncrasy note; n=2 ratio ≤1.30; n≥3 max/min ≤2.5); the numerator gate (Q2).

### 3b. Two-decision gate — STOP

`report_two_decisions(draft_id, decisions, branches)` → show `report_md` together with the
background brief. Wait for the human's reply. Only then `approve_decisions(draft_id, reply)` with the
reply **verbatim**. The approved document (schema 2.1) is what the committed tree carries; changing a
ratio or a tier identity later needs a new report and a new approval. `design_scenarios` /
`save_scenarios` may still be used for the peer-tier skeleton, but the valuation of record is the
approved document, and the server refuses DCF / DDM there too.

### 3c. Research and commit

1. `research_phase2(draft_id)` → `research_phase2_status(draft_id)` every 30–60 s until `ingested`
   (server-side deep research for the narrative pillars and each leaf's evidence pack); or do the
   research yourself with `enrich_narrative_data` and `enrich_leaf_data`, every leaf with ≥1 source URL.
2. `compute_scenarios(draft_id)` for the live peer readings.
3. `commit_draft_tree(draft_id, visibility="private")` — the server validates, aggregates, signs and
   records the first version with provenance.

## Step 4 — Report (chart and article)

`summarize_tree(tree_id)` returns the material and the layout. Write the reader report in this order
and with these rules; `read_committed_report(tree_id)` returns the stored Markdown verbatim.

- **§1 three paragraphs**: what this industry does (everyday analogy first, then size and rivals) →
  who the company is (founding, how it started, what it sells today, customers, channels) → why it is
  worth looking at now (the contrast and the debate, last).
- **§2 four blocks**: what it sells (table: product｜what it does for the customer｜main rivals) → how
  it charges (with one price example) → where the money goes (cost per 100 of revenue) → the last
  quarter (≤5 rows of figures).
- **§3** market consensus and the narrative versions; **§4** the price chart with a colour band per
  narrative version and a short reading note.
- The H-0 in plain words, the tree (short questions and verdict icons), then per leaf: 現時判斷 → 甚麼會
  推翻這個假設 → 推翻之後. Each branch opens with one paragraph (100–150 characters: what the readings
  show, which way they lean, the next reading and its date).
- The three scenarios against the current price: 樂觀／基準／悲觀 only, structural arithmetic and
  distance from price; no weighted target, no directional opinion.
- **Reader text (八成 STE100)**: one idea per sentence, ≤40 characters (hard limit 50); ≤3 sentences per
  paragraph; one term per concept (每股盈利 not 分子; 收入; 估值倍數; 同業水平); never H-0, 身份, 本葉,
  Level 1X, bull/base/bear in reader text; active voice with an explicit subject; no nested brackets;
  lists for anything with more than one item; numbers with unit and period; abbreviations explained
  on first use. Sources show the institution name only.

Then ask once whether to `setup_monitoring(draft_id, weeks)`.

## What monitoring does (so you can explain it)

Every week the server runs an independent search, then a separate judgement per leaf that only sees
the evidence pool (the judge cannot search). Each source carries a `source_tier` (primary / wire / trade
/ aggregator / other); only primary or wire can settle a condition on its own. A verdict change must
cite this week's evidence, must quote a real condition when it enters the falsification zone, cannot
rest on price alone, and is dropped otherwise. Breached or expired conditions latch until superseded.
Every run appends a signed version; `read_tree_versions`, `read_tree_state_at(tree_id, at)` and
`diff_tree_versions` show exactly what the tree said on any date. `sweep_conditions` is the same
deterministic deadline clock and breach latch, callable on any document.

## View mode

`my_workspace()` → `read_tree(tree_id)` / `read_branch` / `read_history` / `read_tree_versions` /
`read_tree_state_at` / `diff_tree_versions` / `read_valuation_draft(draft_id)` / `propose_edit` (sandbox)
→ `apply_edit` (records a new version) / `pause_monitoring` / `resume_monitoring` / `cancel_monitoring`.
A v0.2 document pasted by the user: `migrate_tree` → fill the todo list → `validate_tree` →
`aggregate_tree`.

## Account

`credit_balance` only if asked. Never quote currency amounts or credit figures unprompted.
