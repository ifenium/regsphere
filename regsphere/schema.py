"""The Linkup structured-output schema and the typed result objects.

Design note worth keeping in the submission: the schema sent to Linkup
contains only fields Linkup can extract from the web. `source_verified` is
deliberately NOT in it. That field is set by our own fetch-based
verification step (Day 3), never by the model. Keeping the model's job
(extract) separate from our job (verify) is a core robustness property of
the design, not an accident.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# JSON schema STRING passed to Linkup's `structured_output_schema` parameter.
# Linkup expects a JSON schema serialised as a string (see the structured
# output guide), so we build the dict and json.dumps it once at import time.
LINKUP_SCHEMA: str = json.dumps(
    {
        "type": "object",
        "properties": {
            "applicable_framework_status": {
                "type": "string",
                "enum": [
                    "SPECIFIC_AI_REGULATION",
                    "GENERAL_LAW_APPLIES",
                    "PROPOSED_LEGISLATION",
                    "NO_IDENTIFIED_REGULATION",
                ],
                "description": (
                    "Whether a dedicated AI regime, only general law, a "
                    "pending proposal, or nothing identified governs the "
                    "feature in this jurisdiction."
                ),
            },
            "regulation_classification": {
                "type": "string",
                "description": (
                    "The classification the cited regulation itself assigns "
                    "to this capability, paraphrased from the source text "
                    "(for example a risk tier defined by the regulation). "
                    "Empty string if no formal classification exists. This "
                    "is a fact reported about the regulation, not a legal "
                    "conclusion drawn by the system."
                ),
            },
            "obligations": {
                "type": "array",
                "description": (
                    "Each concrete obligation the regulation imposes on the "
                    "feature. Empty array if none are identified."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "obligation_summary": {
                            "type": "string",
                            "description": "Concise description of what the obligation requires.",
                        },
                        "legal_reference": {
                            "type": "string",
                            "description": (
                                "Specific article or section, e.g. "
                                "'EU AI Act Article 50'."
                            ),
                        },
                        "enforcement_status": {
                            "type": "string",
                            "enum": [
                                "IN_FORCE",
                                "ADOPTED_NOT_YET_IN_FORCE",
                                "PROPOSED",
                                "DRAFT",
                            ],
                            "description": (
                                "Current legal status of this obligation. "
                                "This, not a date filter, is how the engine "
                                "reasons about recency."
                            ),
                        },
                        "enforcement_date": {
                            "type": "string",
                            "description": (
                                "ISO date the obligation takes or took "
                                "effect. Empty string if not stated."
                            ),
                        },
                        "source_url": {
                            "type": "string",
                            "description": (
                                "Direct link to the official regulatory text "
                                "or guidance supporting this obligation."
                            ),
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["HIGH", "MEDIUM", "LOW"],
                            "description": "Model confidence in this obligation.",
                        },
                    },
                    "required": [
                        "obligation_summary",
                        "legal_reference",
                        "enforcement_status",
                        "source_url",
                        "confidence",
                    ],
                },
            },
            "overall_confidence": {
                "type": "string",
                "enum": ["HIGH", "MEDIUM", "LOW"],
                "description": "Overall confidence in this jurisdiction's result.",
            },
            "notes": {
                "type": "string",
                "description": "Any caveats, ambiguities or context worth flagging.",
            },
        },
        "required": [
            "applicable_framework_status",
            "obligations",
            "overall_confidence",
        ],
    }
)


@dataclass
class Obligation:
    """One regulatory obligation attaching to a feature in one jurisdiction."""

    obligation_summary: str
    legal_reference: str
    enforcement_status: str
    source_url: str
    confidence: str
    enforcement_date: str = ""
    # Set ONLY by the Day 3 fetch-based verification step, never by the model.
    source_verified: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Obligation":
        return cls(
            obligation_summary=d.get("obligation_summary", ""),
            legal_reference=d.get("legal_reference", ""),
            enforcement_status=d.get("enforcement_status", "DRAFT"),
            source_url=d.get("source_url", ""),
            confidence=d.get("confidence", "LOW"),
            enforcement_date=d.get("enforcement_date", ""),
            source_verified=False,
        )


@dataclass
class JurisdictionResult:
    """The parsed, typed result for one jurisdiction."""

    jurisdiction: str
    applicable_framework_status: str
    regulation_classification: str
    overall_confidence: str
    notes: str
    obligations: list[Obligation] = field(default_factory=list)

    @classmethod
    def from_linkup(cls, jurisdiction: str, raw: dict[str, Any]) -> "JurisdictionResult":
        """Wrap a raw Linkup structured result into a typed object.

        `jurisdiction` is injected by us; Linkup is not asked to return it.
        """
        return cls(
            jurisdiction=jurisdiction,
            applicable_framework_status=raw.get(
                "applicable_framework_status", "NO_IDENTIFIED_REGULATION"
            ),
            regulation_classification=raw.get("regulation_classification", ""),
            overall_confidence=raw.get("overall_confidence", "LOW"),
            notes=raw.get("notes", ""),
            obligations=[
                Obligation.from_dict(o) for o in raw.get("obligations", [])
            ],
        )

    def summary(self) -> str:
        """Human-readable summary for the Day 1 CLI output."""
        lines = [
            f"Jurisdiction: {self.jurisdiction}",
            f"Framework status: {self.applicable_framework_status}",
            f"Regulation classification: {self.regulation_classification or '(none stated)'}",
            f"Overall confidence: {self.overall_confidence}",
            f"Obligations found: {len(self.obligations)}",
        ]
        for i, o in enumerate(self.obligations, 1):
            lines.append(
                f"  {i}. [{o.enforcement_status}] {o.legal_reference}: "
                f"{o.obligation_summary}"
            )
            lines.append(
                f"     source: {o.source_url or '(none)'}  "
                f"(verified: {o.source_verified}, confidence: {o.confidence})"
            )
        if self.notes:
            lines.append(f"Notes: {self.notes}")
        return "\n".join(lines)
