"""Draw Tree protocol v0.3 — closed vocabularies and frozen constants.

v0.3 is the public form of the methodology running in the maintainer's
research fleet as of 2026-10 (engine `tree_quant/4`, `h0-engine/1`).
Everything here is deterministic data; no I/O, no model calls.

Changes from v0.2 (2026-05):
  - branch weight is DERIVED from `impact_grade` (price-impact of the branch's
    falsification consequence); the reversed-Fibonacci default is retired;
  - kill thresholds raised from 1.0 to 2.0 and `necessity_leaves` added;
  - H-0 conviction is additive log-odds with half credit for positive
    evidence (v4, 2026-07-21), replacing the linear (score+3)/5 map;
  - leaves carry structured `conditions[]` (metric / operator / threshold /
    window / status) and `condition_assessments[]`; the free-text
    observability regex of v0.2 is kept only for migration;
  - evidence is an append-only `evidence_ledger` with closed `tier` and
    `impact` vocabularies;
  - price-implied scenario probabilities (Max-Base convention) are reported
    next to verdict-based ones.
"""
from __future__ import annotations

PROTOCOL_VERSION = "0.3"
ENGINE_VERSION = "h0-engine/1"
BASELINE_SEMANTICS = "tree_quant/4"
CERTIFICATE_VERSION = "h0-derivation/1"

# ---------------------------------------------------------------- verdicts
VERDICT_SIX = (
    "Validated", "Trending positive", "Inconclusive",
    "Trending negative", "Approaching falsification", "Falsified",
)
VERDICT_LEGACY = ("supported", "partially_supported", "challenged")
VERDICT_STRUCTURAL = ("pending",)

VERDICT_SCORES = {
    "Validated": 2, "Trending positive": 1, "Inconclusive": 0,
    "Trending negative": -1, "Approaching falsification": -2, "Falsified": -3,
    "supported": 2, "partially_supported": 0, "challenged": -2, "pending": 0,
}
POSITIVE_VERDICTS = {"Validated", "Trending positive", "supported"}
FALSIFICATION_VERDICTS = {"Falsified", "Approaching falsification", "challenged"}

VERDICT_ICON = {
    "Validated": "✅", "Trending positive": "🟢", "Inconclusive": "⚪",
    "Trending negative": "🟡", "Approaching falsification": "🟠", "Falsified": "✗",
}
# Six-level reading guide keys (one sentence per level on every leaf).
SIX_LEVELS = ("✅ 已驗證", "🟢 趨向正面", "⚪ 未定", "🟡 趨向負面", "🟠 接近證偽", "✗ 已證偽")

# ---------------------------------------------------------------- thresholds
BRANCH_THRESHOLDS = {
    "Validated": 1.5, "Trending positive": 0.5,
    "Trending negative": -0.5, "Approaching falsification": -1.5,
}
H0_THRESHOLDS = dict(BRANCH_THRESHOLDS)
BRANCH_KILL_THRESHOLD = 2.0
H0_KILL_THRESHOLD = 2.0

# ---------------------------------------------------------------- conviction (v4)
CONVICTION_PRIOR = 0.40
CONVICTION_LAMBDA = 1.5          # branch-level sigmoid slope
CONVICTION_CAP = 0.95
CONVICTION_FLOOR = 0.005
UPWARD_CREDIT_DAMP = 0.5         # positive branch contributions count half
CHAIN_SOFTMIN_WEIGHTS = [8, 5, 3, 2, 1]   # legacy `aggregation: chain` only

# ---------------------------------------------------------------- impact grades
# Branch weight == log-odds unit. Grade is derived from the price impact of the
# branch's falsification consequence (see GRADE_BANDS), never authored.
IMPACT_GRADES = {"致命": 2.5, "重創": 1.6, "明顯受損": 0.9, "輕微": 0.4, "邊緣": 0.15}
GRADE_BANDS = ((0.25, "致命"), (0.10, "重創"), (0.04, "明顯受損"), (0.01, "輕微"), (0.0, "邊緣"))
LEGACY_GRADE_MAP = {8: "致命", 5: "重創", 3: "明顯受損", 2: "輕微", 1: "邊緣"}
GRADE_DISPLAY = {"致命": "極高", "重創": "高", "明顯受損": "中", "輕微": "低", "邊緣": "極低"}
GRADE_EN = {"致命": "fatal", "重創": "severe", "明顯受損": "material", "輕微": "minor", "邊緣": "marginal"}

# ---------------------------------------------------------------- roles
BRANCH_ROLES = ("分子交付", "倍數持久", "倍數升級", "加速器")
BRANCH_ROLES_EN = {"分子交付": "numerator delivery", "倍數持久": "multiple persistence",
                   "倍數升級": "multiple upgrade", "加速器": "accelerator"}
LEAF_ROLES = ("bull 驅動", "bear 觸發", "兩者", "輔助")
LEAF_NATURE = ("machine", "judge", "text")
FALSIFICATION_CONSEQUENCES = ("bear_full", "bear_multiple", "bear_numerator", "bull_numerator", "bull_multiple")
BRANCH_AGGREGATION = ("portfolio",)          # `chain` is legacy-only and rejected in v0.3

# ---------------------------------------------------------------- conditions (§8)
CONDITION_KINDS = ("falsification", "verification", "deadline")
CONDITION_STATUS = ("open", "breached", "met", "superseded", "expired_unfulfilled")
CONDITION_OPERATORS = ("<", "<=", ">", ">=", "==", "qoq_decline", "streak_decline")
SCALAR_OPERATORS = ("<", "<=", ">", ">=", "==")
ASSESSMENTS = ("not_met", "approaching", "met", "superseded")
SUPERSEDED_REASON_MIN = 8

# ---------------------------------------------------------------- evidence
EVIDENCE_TIERS = ("filing", "earnings", "trade_press", "news", "synthetic")
EVIDENCE_TIERS_EXTRA = ("audit", "analysis", "data", "vendor_primary", "primary")   # seen in fleet; accepted with warning
EVIDENCE_IMPACT = ("supports", "challenges", "neutral")
EVIDENCE_IMPACT_LEGACY = {"contradicts": "challenges", "against": "challenges", "refutes": "challenges"}
SOURCED_TIERS = ("news", "earnings", "filing", "trade_press")   # dated rows in these tiers need a URL (E6)
SOURCE_TIERS = ("primary", "wire", "trade", "aggregator", "other")   # search-side; only primary/wire settle a condition alone
SETTLING_SOURCE_TIERS = ("primary", "wire")

# ---------------------------------------------------------------- structure limits
BRANCH_COUNT_MIN, BRANCH_COUNT_MAX = 3, 5
SHORT_QUESTION_MAX = 22
H0_QUESTION_MAX = 120
WEIGHT_RATIONALE_PREFIX = "§1.5 衝擊評級："

# ---------------------------------------------------------------- scenarios
SCENARIOS = ("bull", "base", "bear")
SCENARIO_LABELS_ZH = {"bull": "樂觀", "base": "基準", "bear": "悲觀"}
BANNED_VALUATION_METHODS = ("DCF", "DDM", "Reverse DCF", "Reverse-DCF", "reverse_dcf", "dcf", "ddm")


def grade_from_pct(pct_of_price: float) -> str:
    """Impact grade from the largest move (÷ price) a falsification consequence causes."""
    for lo, grade in GRADE_BANDS:
        if pct_of_price >= lo:
            return grade
    return "邊緣"


def weight_for_grade(grade: str) -> float:
    return IMPACT_GRADES[grade]


def grade_for_legacy_weight(weight) -> str | None:
    try:
        return LEGACY_GRADE_MAP.get(int(float(weight)))
    except (TypeError, ValueError):
        return None
