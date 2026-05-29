"""RegSphere entry point: run the agent across all four jurisdictions.

Usage:
    python main.py                              # defaults to resume_screening
    python main.py emotion_recognition_hiring   # any archetype key
    python main.py --eu-only resume_screening   # single jurisdiction for debugging

All four jurisdictions run concurrently via asyncio.gather.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

from dotenv import load_dotenv

from regsphere.config import FEATURE_ARCHETYPES, JURISDICTIONS
from regsphere.graph import build_graph
from regsphere.schema import JurisdictionResult


async def run_jurisdiction(
    graph, feature_key: str, jurisdiction: str
) -> JurisdictionResult:
    """Run the agent graph for one jurisdiction and return the parsed result."""
    initial_state = {
        "feature_key": feature_key,
        "jurisdiction": jurisdiction,
        "attempt": 0,
        "log": [],
    }
    final_state = await graph.ainvoke(initial_state)
    return final_state["parsed"]


async def run_all(
    feature_key: str,
    jurisdictions: list[str] | None = None,
) -> list[JurisdictionResult]:
    """Run the agent across multiple jurisdictions concurrently."""
    if jurisdictions is None:
        jurisdictions = list(JURISDICTIONS.keys())

    graph = build_graph()
    start = time.time()

    results = await asyncio.gather(
        *[run_jurisdiction(graph, feature_key, j) for j in jurisdictions],
        return_exceptions=True,
    )

    elapsed = time.time() - start
    print(f"\n{'=' * 72}")
    print(f"FEATURE: {FEATURE_ARCHETYPES[feature_key]['label']}")
    print(f"JURISDICTIONS: {', '.join(jurisdictions)}")
    print(f"COMPLETED IN: {elapsed:.1f}s")
    print(f"{'=' * 72}")

    parsed_results: list[JurisdictionResult] = []
    for j, r in zip(jurisdictions, results):
        if isinstance(r, Exception):
            print(f"\n[{j}] ERROR: {r}")
        else:
            parsed_results.append(r)
            print(f"\n{r.summary()}")
            print("-" * 72)

    # Print a quick cross-jurisdiction comparison table
    if len(parsed_results) > 1:
        print_comparison(parsed_results)

    # Write JSON — same {"feature":…, "results":[…]} shape as the Streamlit UI.
    output_path = "regsphere_output.json"
    dump = {
        "feature": feature_key,
        "label": FEATURE_ARCHETYPES[feature_key]["label"],
        "results": [_result_to_dict(r) for r in parsed_results],
    }
    with open(output_path, "w") as f:
        json.dump(dump, f, indent=2, default=str)
    print(f"\nFull results written to {output_path}")

    return parsed_results


def print_comparison(results: list[JurisdictionResult]) -> None:
    """Print a compact cross-jurisdiction comparison."""
    print(f"\n{'=' * 72}")
    print("CROSS-JURISDICTION COMPARISON")
    print(f"{'=' * 72}")

    # Header row
    codes = [r.jurisdiction for r in results]
    header = f"{'':30s}" + "".join(f"{c:>12s}" for c in codes)
    print(header)
    print("-" * len(header))

    # Framework status
    row = f"{'Framework status':30s}"
    for r in results:
        short = {
            "SPECIFIC_AI_REGULATION": "AI reg",
            "GENERAL_LAW_APPLIES": "General",
            "PROPOSED_LEGISLATION": "Proposed",
            "NO_IDENTIFIED_REGULATION": "None",
        }.get(r.applicable_framework_status, r.applicable_framework_status[:10])
        row += f"{short:>12s}"
    print(row)

    # Obligation count
    row = f"{'Obligations found':30s}"
    for r in results:
        row += f"{len(r.obligations):>12d}"
    print(row)

    # Verified count
    row = f"{'Sources verified':30s}"
    for r in results:
        v = sum(1 for o in r.obligations if o.source_verified)
        row += f"{f'{v}/{len(r.obligations)}':>12s}"
    print(row)

    # Overall confidence
    row = f"{'Confidence':30s}"
    for r in results:
        row += f"{r.overall_confidence:>12s}"
    print(row)

    # Classification
    row = f"{'Classification':30s}"
    for r in results:
        cls = r.regulation_classification or "(none)"
        row += f"{cls[:12]:>12s}"
    print(row)

    # Divergence flags
    statuses = set(r.applicable_framework_status for r in results)
    if len(statuses) > 1:
        print(
            f"\n** DIVERGENCE DETECTED: framework statuses differ across "
            f"jurisdictions: {', '.join(statuses)}"
        )

    print(f"{'=' * 72}")


def _result_to_dict(r: JurisdictionResult) -> dict:
    """Serialise a JurisdictionResult to a plain dict for JSON output."""
    return {
        "jurisdiction": r.jurisdiction,
        "applicable_framework_status": r.applicable_framework_status,
        "regulation_classification": r.regulation_classification,
        "overall_confidence": r.overall_confidence,
        "notes": r.notes,
        "obligations": [
            {
                "obligation_summary": o.obligation_summary,
                "legal_reference": o.legal_reference,
                "enforcement_status": o.enforcement_status,
                "enforcement_date": o.enforcement_date,
                "source_url": o.source_url,
                "source_verified": o.source_verified,
                "confidence": o.confidence,
            }
            for o in r.obligations
        ],
    }


def main() -> None:
    load_dotenv()

    if not os.getenv("LINKUP_API_KEY"):
        raise SystemExit(
            "LINKUP_API_KEY is not set. Copy .env.example to .env and add "
            "your key, or export LINKUP_API_KEY in your shell."
        )

    # Parse args
    args = sys.argv[1:]
    eu_only = "--eu-only" in args
    args = [a for a in args if not a.startswith("--")]

    feature_key = args[0] if args else "resume_screening"
    if feature_key not in FEATURE_ARCHETYPES:
        valid = ", ".join(FEATURE_ARCHETYPES)
        raise SystemExit(f"Unknown feature '{feature_key}'. Choose from: {valid}")

    jurisdictions = ["EU"] if eu_only else None
    asyncio.run(run_all(feature_key, jurisdictions))


if __name__ == "__main__":
    main()