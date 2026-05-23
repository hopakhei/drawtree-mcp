"""Parse the narrative-detection skill's structured handoff block.

Format expected (from narrative-detection skill v2.0):

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    NARRATIVE HANDOFF — for Hypothesis Tree Construction
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    {Company} {Name} | {Ticker} | {Date}

    [Current Market Story]
    {2-3 sentences}

    [Where the Market May Be Wrong]
    Error Type: {one of six}
    Hypothesis: {The market assumes X, but in reality Y. If Y holds, the
                 valuation framework should shift from A to B.}

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import re


SIX_ERROR_TYPES = [
    "Identity Mislabel",
    "Permanence Assumption Error",
    "Life Cycle Mismatch",
    "Narrative Inertia",
    "Discrete Event Mispricing",
    "Macro Narrative Contagion",
]


def parse_handoff(text: str) -> dict:
    """Return a structured dict; raise ValueError on missing required fields."""
    if not text or not text.strip():
        raise ValueError("empty handoff block")

    # Header line: "{Company Name} | {TICKER} | {Date}".
    # Restricted to a single line (no newlines within the company name) to
    # avoid greedy capture of the ━━━ banner above it.
    header_re = re.compile(
        r"^\s*([^|\n]+?)\s*\|\s*([A-Z0-9.\-]+)\s*\|\s*(\S[^\n]*?)\s*$",
        re.MULTILINE,
    )
    m = header_re.search(text)
    if not m:
        raise ValueError("could not find header line 'Company | TICKER | Date'")
    company = m.group(1).strip()
    ticker = m.group(2).strip()
    date = m.group(3).strip()

    # [Current Market Story] block — captures until next [ section or End block
    story_re = re.compile(
        r"\[Current Market Story\]\s*(.+?)(?=\n\s*\[Where|━{4,})",
        re.DOTALL,
    )
    s = story_re.search(text)
    market_story = s.group(1).strip() if s else ""

    # [Where the Market May Be Wrong] block
    wrong_re = re.compile(
        r"\[Where the Market May Be Wrong\]\s*(.+?)(?=━{4,}|$)",
        re.DOTALL,
    )
    w = wrong_re.search(text)
    wrong_block = w.group(1).strip() if w else ""

    # Inside wrong_block: Error Type and Hypothesis
    err_re = re.compile(r"Error Type\s*:\s*(.+?)(?=\n|$)")
    hyp_re = re.compile(r"Hypothesis\s*:\s*(.+?)(?=\n\s*$|\Z)", re.DOTALL)
    em = err_re.search(wrong_block)
    hm = hyp_re.search(wrong_block)
    error_type_raw = em.group(1).strip() if em else ""
    hypothesis = hm.group(1).strip() if hm else ""

    # Normalize error type (allow loose match)
    error_type = ""
    for canonical in SIX_ERROR_TYPES:
        if canonical.lower() in error_type_raw.lower():
            error_type = canonical
            break
    if not error_type and error_type_raw:
        error_type = error_type_raw  # leave as-is, but flag

    # Try to split hypothesis into "X / Y / framework_from / framework_to"
    # Format: "The market assumes X, but in reality Y. If Y holds, the
    #          valuation framework should shift from A to B."
    parsed_hyp = parse_hypothesis_sentence(hypothesis)

    if not market_story or not error_type or not hypothesis:
        raise ValueError(
            f"handoff block missing required fields: "
            f"market_story={'ok' if market_story else 'MISSING'}, "
            f"error_type={'ok' if error_type else 'MISSING'}, "
            f"hypothesis={'ok' if hypothesis else 'MISSING'}"
        )

    return {
        "ticker": ticker,
        "company": company,
        "date": date,
        "market_story": market_story,
        "error_type": error_type,
        "error_type_recognised": error_type in SIX_ERROR_TYPES,
        "hypothesis": hypothesis,
        "hypothesis_parsed": parsed_hyp,
    }


def parse_hypothesis_sentence(sentence: str) -> dict:
    """Split 'The market assumes X, but in reality Y. If Y holds, the
    valuation framework should shift from A to B.'"""
    out = {"market_assumes": "", "in_reality": "", "framework_from": "", "framework_to": ""}
    # First clause
    # Tolerate newlines + arbitrary whitespace around 'but in reality' / 'If'.
    s = re.sub(r"\s+", " ", sentence)
    m1 = re.search(
        r"market assumes\s+(.+?)[,.]?\s+but in reality\s+(.+?)[,.]?\s+If\b",
        s, re.IGNORECASE,
    )
    if m1:
        out["market_assumes"] = m1.group(1).strip().rstrip(".,")
        out["in_reality"] = m1.group(2).strip().rstrip(".,")
    # Framework shift clause
    m2 = re.search(
        r"shift from\s+(.+?)\s+to\s+(.+?)(?:\.|$)",
        s, re.IGNORECASE,
    )
    if m2:
        out["framework_from"] = m2.group(1).strip().rstrip(".,")
        out["framework_to"] = m2.group(2).strip().rstrip(".,")
    return out


def derive_root_question(parsed_handoff: dict) -> str:
    """Convert a parsed narrative handoff into an H-0 root question.

    The narrative-detection skill's hypothesis is declarative; H-0 needs to be a
    yes/no question that the tree resolves. Convert:
        'The market assumes X, but in reality Y. If Y holds, framework
         shifts from A to B.'
    to:
        'Will {Y} hold over the next N quarters, forcing a re-rating from A to B?'
    """
    p = parsed_handoff.get("hypothesis_parsed") or {}
    in_reality = p.get("in_reality", "").strip().rstrip(".")
    fw_from = p.get("framework_from", "").strip()
    fw_to = p.get("framework_to", "").strip()
    if in_reality and fw_from and fw_to:
        return (
            f"Will {in_reality} hold over the next 4 quarters, forcing a "
            f"re-rating from {fw_from} to {fw_to}?"
        )
    if in_reality:
        return f"Will {in_reality} hold over the next 4 quarters?"
    return parsed_handoff.get("hypothesis", "")
