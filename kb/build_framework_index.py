"""Convert business-frameworks-kb.md into a structured JSON index.

Parses the markdown structure where each section header introduces a category
and a bulleted list enumerates the frameworks in that category.

Output: kb/frameworks.json — a dict { framework_name: { category, slug, file, tags } }

Tags are heuristic — derived from framework name + category to enable
keyword/BM25 retrieval without needing the full 13 sub-files.

Run:
    python kb/build_framework_index.py path/to/business-frameworks-kb.md
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


CATEGORY_TAGS = {
    "Strategy Process, Problem Solving & Decision-Making": [
        "decision", "process", "structuring", "alignment", "change",
    ],
    "Growth, Innovation & Disruption": [
        "growth", "innovation", "tam", "disruption", "scaling", "platform-launch",
    ],
    "Industry & Market Structure": [
        "industry", "market-structure", "rivalry", "lifecycle", "macro", "ecosystem",
    ],
    "Competitive & Business-Level Strategy": [
        "competitive-position", "moat", "differentiation", "cost-position", "vrio",
        "value-chain", "strategic-group",
    ],
    "Corporate & Portfolio Strategy": [
        "portfolio", "capital-allocation", "diversification", "make-buy", "ma",
        "spinoff",
    ],
    "Business Model & Value Proposition": [
        "business-model", "monetisation", "pricing", "platform", "value-proposition",
    ],
    "Customer, Marketing & Brand": [
        "customer", "brand", "ltv", "nps", "segmentation", "positioning",
    ],
    "Capabilities, Organization & Operating Model": [
        "operating-model", "org-design", "capability", "execution",
    ],
    "Digital, Data, Platforms & Ecosystems": [
        "digital", "platform", "api", "data", "ai", "north-star", "plg",
    ],
    "International & Global Strategy": [
        "international", "global", "market-entry", "fx",
    ],
    "Operations, Supply Chain & Efficiency": [
        "operations", "supply-chain", "lean", "efficiency", "footprint",
    ],
    "Risk, Uncertainty & Scenarios": [
        "risk", "scenario", "tail-risk", "stress-test", "real-options",
    ],
    "Social Impact, ESG & Public Value": [
        "esg", "stakeholder", "social-impact", "sustainability",
    ],
}

# Per-framework hints: which type of leaf hypothesis this framework typically informs
LEAF_AFFINITY = {
    "Porter's Five Forces": "industry-attractiveness",
    "Extended Five Forces": "industry-attractiveness",
    "PESTEL / STEEP / STEEPLE Framework": "macro-tailwind",
    "Industry Life Cycle Model": "lifecycle-stage",
    "S-Curve of Industry / Technology Evolution": "lifecycle-stage",
    "Strategic Inflection Point Framework": "narrative-shift",
    "VRIO / VRIN Analysis": "moat-test",
    "Resource-Based View": "moat-test",
    "Core Competence Framework": "moat-test",
    "Strategic Group Mapping": "identity-test",
    "Business Model Canvas": "business-model-coherence",
    "Two-sided Platform Business Model": "platform-leverage",
    "Network Effects Map": "platform-leverage",
    "Customer Lifetime Value Model": "customer-economics",
    "Net Promoter System": "customer-loyalty",
    "Brand Equity Pyramid": "brand-strength",
    "BCG Growth-Share Matrix": "portfolio-balance",
    "GE-McKinsey Nine-Box Matrix": "portfolio-balance",
    "Capital Allocation Framework": "capital-discipline",
    "McKinsey Three Horizons of Growth": "growth-pipeline",
    "Disruptive Innovation Theory": "disruption-risk",
    "Blue Ocean Strategy Canvas": "differentiation-test",
    "Jobs to Be Done Framework": "demand-validation",
    "Scenario Planning": "tail-risk",
    "Real Options Valuation": "optionality",
    "Decision Tree Analysis": "branching-uncertainty",
    "Black Swan / Barbell Strategy": "tail-risk",
    "AI Value Creation Framework": "ai-monetisation",
    "Product-Led Growth Framework": "growth-engine",
    "AARRR Pirate Metrics Funnel": "growth-engine",
    "Growth Flywheel Framework": "growth-engine",
}


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def parse_kb(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")

    frameworks: dict[str, dict] = {}
    current_category = None
    current_file = None

    cat_re = re.compile(r"^### (.+)$")
    file_re = re.compile(r"^\*\*File:\*\* `([^`]+)`")
    bullet_re = re.compile(r"^- (.+)$")

    for line in text.splitlines():
        m = cat_re.match(line.strip())
        if m:
            heading = m.group(1).strip()
            # Skip non-category headings (How to Use, Per-Framework Structure, etc.)
            if heading in CATEGORY_TAGS:
                current_category = heading
            else:
                current_category = None
            current_file = None
            continue
        m = file_re.match(line.strip())
        if m and current_category:
            current_file = m.group(1).strip()
            continue
        m = bullet_re.match(line.strip())
        if m and current_category:
            name = m.group(1).strip()
            # Trim curly apostrophe variations to a canonical ASCII form for matching
            canonical = name.replace("\u2019", "'")
            slug = slugify(canonical)
            tags = list(CATEGORY_TAGS.get(current_category, []))
            # Add tokens from the framework name itself
            for tok in re.findall(r"[A-Za-z0-9]+", canonical.lower()):
                if len(tok) > 2 and tok not in tags:
                    tags.append(tok)
            frameworks[canonical] = {
                "name": canonical,
                "category": current_category,
                "slug": slug,
                "file": current_file,
                "tags": tags,
                "leaf_affinity": LEAF_AFFINITY.get(canonical),
            }

    return {
        "version": "1.0",
        "framework_count": len(frameworks),
        "categories": list(CATEGORY_TAGS.keys()),
        "frameworks": frameworks,
    }


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: build_framework_index.py path/to/business-frameworks-kb.md")
    md = Path(sys.argv[1])
    out = Path(__file__).parent / "frameworks.json"
    index = parse_kb(md)
    out.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    print(f"Wrote {out} — {index['framework_count']} frameworks across "
          f"{len(index['categories'])} categories")


if __name__ == "__main__":
    main()
