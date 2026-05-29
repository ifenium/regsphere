"""Divergence computation: theme tagging and cross-jurisdictional matrix.

Day 4 feature. Tags each obligation into a fixed theme taxonomy using
keyword matching (rule-based, no LLM), then builds a theme-by-jurisdiction
matrix to surface where regulations diverge.

The divergence computation is deterministic code, not an LLM call. This is
intentional: the comparison logic is transparent and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import JurisdictionResult, Obligation

# Theme taxonomy with keyword patterns for rule-based matching.
# Keys are theme identifiers; values are lists of lowercase keywords/phrases.
# An obligation matches a theme if any keyword appears in its summary.
THEME_TAXONOMY: dict[str, list[str]] = {
    "prohibition": [
        "prohibit",
        "banned",
        "forbidden",
        "not permitted",
        "shall not",
        "must not deploy",
        "unacceptable",
        "illegal",
    ],
    "transparency_disclosure": [
        "disclos",  # matches disclose, disclosure, disclosed
        "transparen",  # matches transparent, transparency
        "inform",
        "notify the",
        "labelling",
        "labeling",
        "watermark",
        "clearly indicate",
        "made aware",
        "right to know",
    ],
    "conformity_assessment": [
        "conformity assessment",
        "audit",
        "certification",
        "third-party assessment",
        "third party assessment",
        "independent review",
        "compliance check",
        "notified body",
        "ce marking",
    ],
    "human_oversight": [
        "human oversight",
        "human-in-the-loop",
        "human in the loop",
        "human review",
        "human intervention",
        "manual review",
        "human control",
        "human supervision",
        "override",
        "human decision",
    ],
    "data_governance": [
        "data governance",
        "data quality",
        "training data",
        "data protection",
        "data minimisation",
        "data minimization",
        "bias",
        "fairness",
        "non-discrimination",
        "representative data",
        "dataset",
    ],
    "registration_notification": [
        "register",
        "registration",
        "notification",
        "notify authority",
        "eu database",
        "national database",
        "market surveillance",
        "report to",
        "filing",
    ],
}

# Display labels for themes (user-friendly names)
THEME_LABELS: dict[str, str] = {
    "prohibition": "Prohibition",
    "transparency_disclosure": "Transparency / Disclosure",
    "conformity_assessment": "Conformity Assessment / Audit",
    "human_oversight": "Human Oversight",
    "data_governance": "Data Governance",
    "registration_notification": "Registration / Notification",
}


def tag_obligation(obligation: Obligation) -> set[str]:
    """Return the set of themes that apply to an obligation.

    Uses keyword matching against the obligation_summary field.
    An obligation can match multiple themes (e.g., a rule requiring
    both transparency and human oversight).

    Returns an empty set if no themes match, which is a valid outcome
    (not all obligations fit the taxonomy).
    """
    text = obligation.obligation_summary.lower()
    matched = set()
    for theme, keywords in THEME_TAXONOMY.items():
        for kw in keywords:
            if kw in text:
                matched.add(theme)
                break  # one match is enough for this theme
    return matched


@dataclass
class MatrixCell:
    """One cell in the divergence matrix: a (theme, jurisdiction) pair."""

    theme: str
    jurisdiction: str
    obligations: list[Obligation] = field(default_factory=list)

    @property
    def has_obligations(self) -> bool:
        return len(self.obligations) > 0

    @property
    def count(self) -> int:
        return len(self.obligations)


@dataclass
class DivergenceMatrix:
    """The theme-by-jurisdiction divergence matrix.

    Rows are themes (from THEME_TAXONOMY), columns are jurisdictions.
    Each cell contains the obligations matching that theme for that jurisdiction.
    """

    themes: list[str]
    jurisdictions: list[str]
    cells: dict[tuple[str, str], MatrixCell] = field(default_factory=dict)
    # Per-jurisdiction metadata
    framework_status: dict[str, str] = field(default_factory=dict)
    overall_confidence: dict[str, str] = field(default_factory=dict)

    def get_cell(self, theme: str, jurisdiction: str) -> MatrixCell:
        """Get the cell for a theme-jurisdiction pair."""
        key = (theme, jurisdiction)
        if key not in self.cells:
            self.cells[key] = MatrixCell(theme=theme, jurisdiction=jurisdiction)
        return self.cells[key]

    def theme_label(self, theme: str) -> str:
        """User-friendly label for a theme."""
        return THEME_LABELS.get(theme, theme)

    def divergence_summary(self) -> dict[str, Any]:
        """Compute divergence statistics.

        Returns a dict with:
        - themes_with_divergence: themes where jurisdictions differ
        - coverage_by_jurisdiction: how many themes each jurisdiction covers
        - uncovered_themes: themes with no obligations in any jurisdiction
        """
        themes_with_divergence = []
        for theme in self.themes:
            jurisdictions_with_theme = [
                j for j in self.jurisdictions if self.get_cell(theme, j).has_obligations
            ]
            # Divergence if some but not all jurisdictions have the theme
            if 0 < len(jurisdictions_with_theme) < len(self.jurisdictions):
                themes_with_divergence.append(theme)

        coverage = {}
        for j in self.jurisdictions:
            coverage[j] = sum(
                1 for t in self.themes if self.get_cell(t, j).has_obligations
            )

        uncovered = [
            t
            for t in self.themes
            if not any(self.get_cell(t, j).has_obligations for j in self.jurisdictions)
        ]

        return {
            "themes_with_divergence": themes_with_divergence,
            "coverage_by_jurisdiction": coverage,
            "uncovered_themes": uncovered,
        }


def build_divergence_matrix(
    results: list[JurisdictionResult],
) -> DivergenceMatrix:
    """Build the divergence matrix from jurisdiction results.

    Each obligation is tagged with themes and placed into the appropriate
    matrix cells. The matrix then shows, for each theme, which jurisdictions
    impose obligations and which do not.
    """
    themes = list(THEME_TAXONOMY.keys())
    jurisdictions = [r.jurisdiction for r in results]

    matrix = DivergenceMatrix(themes=themes, jurisdictions=jurisdictions)

    for result in results:
        matrix.framework_status[result.jurisdiction] = result.applicable_framework_status
        matrix.overall_confidence[result.jurisdiction] = result.overall_confidence

        for obligation in result.obligations:
            matched_themes = tag_obligation(obligation)
            for theme in matched_themes:
                cell = matrix.get_cell(theme, result.jurisdiction)
                cell.obligations.append(obligation)

    return matrix
