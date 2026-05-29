"""Static configuration: jurisdictions and feature archetypes.

Day 1 scope: only the EU jurisdiction is exercised by main.py, but all four
are defined here so Day 3 (concurrency across jurisdictions) is pure wiring
with nothing new to design.
"""

from __future__ import annotations

# Per-jurisdiction config.
#
# `include_domains` is where domain expertise is encoded: a curated allowlist
# of official regulator sites is the asset, not the raw API call. This is the
# single clearest answer to the "thin wrapper" question.
JURISDICTIONS: dict[str, dict] = {
    "EU": {
        "name": "European Union",
        "regulator": "the European AI Office and the European Commission",
        "primary_regulation": "the EU AI Act (Regulation (EU) 2024/1689)",
        "include_domains": [
            "eur-lex.europa.eu",
            "digital-strategy.ec.europa.eu",
            "artificialintelligenceact.eu",
        ],
    },
    "US": {
        "name": "United States",
        "regulator": "the Federal Trade Commission, the EEOC and NIST",
        "primary_regulation": (
            "sectoral federal rules and FTC Act guidance "
            "(there is no single federal AI statute)"
        ),
        "include_domains": ["ftc.gov", "nist.gov", "eeoc.gov", "congress.gov"],
    },
    "UK": {
        "name": "United Kingdom",
        "regulator": "the ICO and sector regulators under the UK AI framework",
        "primary_regulation": (
            "the UK pro-innovation AI framework and "
            "UK GDPR / the Data Protection Act 2018"
        ),
        "include_domains": ["gov.uk", "ico.org.uk", "legislation.gov.uk"],
    },
    "SG": {
        "name": "Singapore",
        "regulator": "the Personal Data Protection Commission and IMDA",
        "primary_regulation": (
            "the PDPA and the Model AI Governance Framework"
        ),
        "include_domains": ["pdpc.gov.sg", "imda.gov.sg", "csa.gov.sg"],
    },
}

# The five feature archetypes from the build spec.
#
# Day 1 normalisation is a lookup over these known archetypes. Day 2 adds an
# LLM normalisation step so the engine also accepts free-text feature input.
FEATURE_ARCHETYPES: dict[str, dict] = {
    "resume_screening": {
        "label": "Automated resume / candidate screening",
        "canonical_capability": (
            "an automated system that screens, ranks or filters job "
            "applicants by applying machine learning to their CVs and profiles"
        ),
    },
    "emotion_recognition_hiring": {
        "label": "Biometric or emotion recognition in hiring",
        "canonical_capability": (
            "a system that infers the emotions or personality traits of job "
            "candidates from facial expressions, voice or other biometric data"
        ),
    },
    "deepfake_generation": {
        "label": "Synthetic media / deepfake generation",
        "canonical_capability": (
            "a generative system that creates synthetic image, audio or video "
            "content depicting real or realistic-looking people"
        ),
    },
    "behavioural_scoring": {
        "label": "Behavioural profiling for eligibility scoring",
        "canonical_capability": (
            "a system that profiles individuals from behavioural data to "
            "produce a score that affects their access to credit, services "
            "or benefits"
        ),
    },
    "undisclosed_chatbot": {
        "label": "Customer-facing chatbot without disclosure",
        "canonical_capability": (
            "a customer-facing conversational AI agent that interacts with "
            "people without disclosing that it is an automated system"
        ),
    },
}
