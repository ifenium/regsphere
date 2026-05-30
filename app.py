"""RegSphere Streamlit UI: cross-jurisdictional regulatory divergence engine.

Run with:
    streamlit run app.py

Requires LINKUP_API_KEY in the environment or in a .env file.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from linkup import LinkupClient

from regsphere.config import FEATURE_ARCHETYPES, JURISDICTIONS
from regsphere.divergence import (
    DivergenceMatrix,
    THEME_LABELS,
    build_divergence_matrix,
)
from regsphere.graph import build_graph
from regsphere.linkup_search import (
    normalize_feature_description,
    research_deep_dive,
    ResearchResult,
)
from regsphere.schema import JurisdictionResult, Obligation

# Load environment variables
load_dotenv()

LOGO_PATH = Path(__file__).parent / "RegSphere.svg"

# Brand palette (kept deliberately simple to match the logo)
BRAND_BLUE = "#006FAC"

# Human labels + badge colours for the framework status enum (no raw codes in UI).
FRAMEWORK_LABELS: dict[str, tuple[str, str]] = {
    "SPECIFIC_AI_REGULATION": ("Specific AI regulation", "is-blue"),
    "GENERAL_LAW_APPLIES": ("General law applies", "is-slate"),
    "PROPOSED_LEGISLATION": ("Proposed legislation", "is-amber"),
    "NO_IDENTIFIED_REGULATION": ("No identified regulation", "is-slate"),
}

# Confidence tier -> semantic pill colour.
CONFIDENCE_CLASS: dict[str, str] = {
    "HIGH": "is-green",
    "MEDIUM": "is-amber",
    "LOW": "is-red",
}

# Per-jurisdiction progress wording: characterful but formal, one line per phase.
PROGRESS_PHRASES: dict[str, dict[str, str]] = {
    "EU": {
        "build": "Framing the enquiry under the EU AI Act...",
        "search": "Consulting the AI Office and EUR-Lex...",
    },
    "US": {
        "build": "Mapping the federal patchwork...",
        "search": "Cross-examining FTC, EEOC and NIST guidance...",
    },
    "UK": {
        "build": "Drafting the UK enquiry...",
        "search": "Reviewing ICO guidance and UK statute...",
    },
    "SG": {
        "build": "Preparing the Singapore brief...",
        "search": "Consulting the PDPC and IMDA frameworks...",
    },
}
DEFAULT_PHRASES = {"build": "Building query...", "search": "Searching..."}

# Regional flags shown in the Jurisdictions and Analysis Progress sections.
FLAGS: dict[str, str] = {"EU": "🇪🇺", "US": "🇺🇸", "UK": "🇬🇧", "SG": "🇸🇬"}

# Page configuration
st.set_page_config(
    page_title="RegSphere",
    page_icon=":globe_with_meridians:",
    layout="wide",
)


def load_logo() -> str:
    """Return the inline SVG markup for the RegSphere logo, or an empty string."""
    try:
        return LOGO_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def inject_styles() -> None:
    """Inject the brand theme: thin consistent black borders, calm surfaces, blue accent."""
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700;800&display=swap');

        :root {{
            --rs-blue: {BRAND_BLUE};
            --rs-blue-dark: #005a8c;
            --rs-ink: #0a0a0a;
            --rs-bg: #ffffff;
            --rs-muted: #5b6670;
            --rs-depth: 3px 3px 0 var(--rs-ink);
            --rs-depth-sm: 2px 2px 0 var(--rs-ink);
        }}

        html, body, [class*="css"], .stApp {{
            font-family: 'Hanken Grotesk', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }}

        .stApp {{ background: var(--rs-bg); color: var(--rs-ink); }}

        /* Trim Streamlit's very tall default top/bottom page padding so the
           logo sits near the top (level with the Print button) instead of after
           a large gap, and there is no big empty space below the content. */
        [data-testid="stMainBlockContainer"], .block-container {{
            padding-top: 2.5rem !important;
            padding-bottom: 2rem !important;
        }}

        /* Remove Streamlit's entire top header bar. It is otherwise an empty
           strip that takes space AND overlays (with a high z-index) the
           top-left mini-logo and the top-right Print button, hiding them.
           This also removes the Deploy button, overflow menu, "Running..."
           status widget and the thin decoration bar in one go. */
        [data-testid="stHeader"] {{ display: none !important; }}
        [data-testid="stToolbar"] {{ display: none !important; }}
        [data-testid="stStatusWidget"] {{ display: none !important; }}
        [data-testid="stDecoration"] {{ display: none !important; }}

        /* Scroll mini-logo (injected by inject_chrome): bare logo, no box */
        #rs-minilogo {{
            position: fixed; top: 0.55rem; left: 1rem; z-index: 999999;
            opacity: 0; transform: translateY(-10px);
            transition: opacity 0.25s ease, transform 0.25s ease;
            pointer-events: none;
        }}
        #rs-minilogo.visible {{ opacity: 1; transform: translateY(0); }}
        #rs-minilogo svg {{ height: 26px; width: auto; display: block; }}

        /* Injected top-right toolbar: Copy / Download / Print (inject_chrome) */
        #rs-toolbar {{
            position: fixed; top: 0.6rem; right: 1rem; z-index: 999999;
            display: flex; gap: 0.5rem; align-items: center;
        }}
        #rs-toolbar button {{
            border-radius: 8px; box-shadow: var(--rs-depth-sm);
            font-family: 'Hanken Grotesk', 'Inter', -apple-system, sans-serif;
            font-weight: 700; font-size: 0.82rem;
            padding: 0.4rem 0.95rem; cursor: pointer;
        }}
        /* Print: pastel orange */
        #rs-print-btn {{ background: #f4a261; color: #5a2e0c; border: 1px solid #d98a3f; }}
        #rs-print-btn:hover {{ background: #f0935f; }}
        /* Copy / Download Markdown: blue, the colour-wheel complement of orange */
        #rs-copy-btn, #rs-dl-btn {{ background: #6fa8dc; color: #0a2a44; border: 1px solid #4f8fc9; }}
        #rs-copy-btn:hover, #rs-dl-btn:hover {{ background: #5b97cf; }}
        @media print {{
            #rs-toolbar, #rs-minilogo, .rs-fade {{ display: none !important; }}
        }}

        /* Headings */
        h1, h2, h3, h4 {{ color: var(--rs-ink); font-weight: 800; letter-spacing: -0.01em; }}

        /* Brand header (inline: logo + tagline) */
        .rs-head {{
            display: flex;
            align-items: center;
            gap: 1rem;
            flex-wrap: wrap;
            margin-bottom: 1.4rem;
        }}
        .rs-head .rs-logo svg {{ max-width: 230px; width: 100%; height: auto; display: block; }}
        .rs-head .rs-tag {{
            font-size: 0.95rem;
            font-weight: 600;
            color: var(--rs-muted);
            border-left: 1px solid var(--rs-ink);
            padding-left: 1rem;
            line-height: 1.3;
            max-width: 300px;
        }}

        /* Keep the left Setup column pinned while the results column scrolls */
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-setup) {{
            position: sticky;
            top: 3rem;  /* clears the fixed scroll mini-logo so they don't overlap */
            align-self: flex-start;
        }}

        /* Blue scroll-cue fade pinned to the bottom of the viewport */
        .rs-fade {{
            position: fixed; left: 0; right: 0; bottom: 0; height: 72px;
            background: linear-gradient(to top, rgba(0, 111, 172, 0.18), rgba(0, 111, 172, 0));
            pointer-events: none; z-index: 999;
            opacity: 1; transition: opacity 0.25s ease;
        }}
        .rs-fade.rs-fade-hidden {{ opacity: 0; }}
        .rs-fade-chev {{
            text-align: center; color: var(--rs-blue);
            font-size: 1.25rem; line-height: 72px;
        }}

        /* Source-verification disclaimer (persistent, under the header) */
        .rs-disclaimer {{
            display: flex; align-items: flex-start; gap: 0.55rem;
            border: 1px solid var(--rs-blue);
            border-left: 4px solid var(--rs-blue);
            border-radius: 8px;
            background: #dceaf6;
            color: #103a52;
            font-size: 0.83rem;
            font-weight: 500;
            padding: 0.6rem 0.9rem;
            margin: -0.4rem 0 1.4rem;
        }}
        .rs-disclaimer b {{ color: var(--rs-blue-dark); }}
        .rs-disclaimer-ico {{ color: var(--rs-blue-dark); font-size: 1rem; line-height: 1.4; flex-shrink: 0; }}

        /* Completed-analysis summary bar (collapsed Analysis Progress) */
        .rs-summary {{
            display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem 0.75rem;
            border: 1px solid var(--rs-ink);
            border-radius: 8px;
            box-shadow: var(--rs-depth-sm);
            background: #fff;
            padding: 0.55rem 0.9rem;
            margin-bottom: 1rem;
        }}
        .rs-summary-ico {{ color: #1f9d57; font-weight: 800; }}
        .rs-summary-text {{ font-weight: 700; }}
        .rs-chips {{ display: flex; flex-wrap: wrap; gap: 0.35rem; margin-left: auto; }}
        .rs-chip {{
            border: 1px solid var(--rs-blue);
            background: #e6f1f8; color: var(--rs-blue-dark);
            border-radius: 50px; padding: 0.05rem 0.55rem;
            font-size: 0.74rem; font-weight: 600;
        }}
        .rs-chip b {{ font-weight: 800; margin-left: 0.15rem; }}

        /* Config card: target ONLY the keyed setup container */
        .st-key-setup {{
            border: 1px solid var(--rs-ink) !important;
            border-radius: 12px !important;
            box-shadow: var(--rs-depth) !important;
            background: #fff !important;
        }}
        .st-key-setup [data-testid="stVerticalBlock"] {{ gap: 0.55rem; }}
        /* Tighter dividers inside Setup so sections sit closer (some space,
           not a large gap) around the Jurisdictions and Analyze separators. */
        .st-key-setup hr {{ margin: 0.15rem 0 !important; }}

        /* Feature-input segmented control: full width, options stretch equally */
        [data-testid="stButtonGroup"] {{ width: 100%; }}
        [data-testid="stButtonGroup"] > div:has(> button) {{ display: flex; width: 100%; gap: 0.4rem; }}
        [data-testid="stButtonGroup"]:has(> button) {{ display: flex; gap: 0.4rem; }}
        [data-testid="stButtonGroup"] button {{ flex: 1 1 0; }}
        /* Selected segment: dark blue + white, matching the Analyze button */
        [data-testid="stButtonGroup"] button[kind="segmented_controlActive"] {{
            background: var(--rs-blue) !important;
            color: #fff !important;
            border-color: var(--rs-blue) !important;
        }}
        [data-testid="stButtonGroup"] button[kind="segmented_controlActive"] * {{
            color: #fff !important;
        }}
        [data-testid="stButtonGroup"] button[kind="segmented_control"] {{
            background: #fff;
            color: var(--rs-ink);
        }}
        /* Fixed per-option colours, applied in EVERY state: "Preset archetypes"
           (1st) stays blue even when Custom is selected; "Custom description"
           (2nd) carries the Print-page orange and its bold (700) weight. */
        [data-testid="stButtonGroup"] button:nth-of-type(1),
        [data-testid="stButtonGroup"] > div:nth-of-type(1) button {{
            background: var(--rs-blue) !important;
            color: #fff !important;
            border-color: var(--rs-blue) !important;
            opacity: 1 !important;
        }}
        [data-testid="stButtonGroup"] button:nth-of-type(1) *,
        [data-testid="stButtonGroup"] > div:nth-of-type(1) button * {{
            color: #fff !important;
        }}
        /* "Custom description" (2nd segment): permanently #f4a261 with black
           text in EVERY state (default, hover, focus, selected) — never dimmed
           and never the blue/white active treatment. */
        [data-testid="stButtonGroup"] button:nth-of-type(2),
        [data-testid="stButtonGroup"] button:nth-of-type(2):hover,
        [data-testid="stButtonGroup"] button:nth-of-type(2):focus,
        [data-testid="stButtonGroup"] button:nth-of-type(2)[kind="segmented_controlActive"],
        [data-testid="stButtonGroup"] > div:nth-of-type(2) button {{
            background: #f4a261 !important;
            color: var(--rs-ink) !important;
            border-color: #d98a3f !important;
            font-weight: 700 !important;
            opacity: 1 !important;
        }}
        [data-testid="stButtonGroup"] button:nth-of-type(2) *,
        [data-testid="stButtonGroup"] button:nth-of-type(2)[kind="segmented_controlActive"] *,
        [data-testid="stButtonGroup"] > div:nth-of-type(2) button * {{
            color: var(--rs-ink) !important;
        }}

        /* Feature input / Feature archetype labels match the Jurisdictions title */
        [data-testid="stButtonGroup"] [data-testid="stWidgetLabel"] p,
        [data-testid="stSelectbox"] [data-testid="stWidgetLabel"] p,
        [data-testid="stTextArea"] [data-testid="stWidgetLabel"] p {{
            font-size: 1.05rem;
            font-weight: 800;
        }}

        /* Jurisdiction header: title + live count */
        .rs-jur-head {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin: 0.2rem 0 0.4rem;
        }}
        .rs-jur-head .rs-jur-title {{ font-weight: 800; font-size: 1.05rem; }}
        .rs-jur-head .rs-jur-count {{
            font-weight: 700;
            font-size: 0.78rem;
            color: #fff;
            background: var(--rs-blue);
            border: 1px solid var(--rs-blue);
            border-radius: 50px;
            padding: 0.05rem 0.55rem;
        }}

        /* Preview (pre-run placeholder) */
        .rs-preview-head {{
            display: flex; align-items: center; gap: 0.4rem;
            font-weight: 700; color: var(--rs-muted);
            margin-bottom: 1rem;
        }}
        .rs-preview-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 1rem;
        }}
        .rs-skel-card {{
            border: 1px solid var(--rs-ink);
            border-radius: 10px;
            box-shadow: var(--rs-depth);
            background: #fff;
            padding: 1rem 1.1rem;
        }}
        .rs-skel-head {{
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 0.35rem;
        }}
        .rs-skel-title {{ font-weight: 800; font-size: 1rem; }}
        .rs-skel-badge {{
            font-size: 0.66rem; font-weight: 700; color: var(--rs-muted);
            border: 2px solid #d7dde2; border-radius: 50px;
            padding: 0.05rem 0.5rem; background: #f4f6f8;
            text-transform: uppercase; letter-spacing: 0.04em;
        }}
        .rs-skel-meta {{
            font-size: 0.78rem; color: var(--rs-muted);
            margin-bottom: 0.8rem; min-height: 2.3rem; line-height: 1.35;
        }}
        .rs-skel-bar {{
            height: 0.55rem; border-radius: 50px;
            background: #eceff2; margin-bottom: 0.45rem;
        }}
        .rs-skel-bar.w90 {{ width: 90%; }}
        .rs-skel-bar.w75 {{ width: 75%; }}
        .rs-skel-bar.w60 {{ width: 60%; }}
        .rs-preview-foot {{
            margin-top: 1.2rem; font-size: 0.85rem; color: var(--rs-muted);
            text-align: center; line-height: 1.4;
        }}
        .rs-scroll-cue {{
            text-align: center; font-size: 1.3rem;
            color: var(--rs-muted); margin-top: 0.4rem;
        }}
        @media (max-width: 900px) {{
            .rs-preview-grid {{ grid-template-columns: 1fr; }}
            /* Once the two columns stack vertically the left card must NOT stay
               pinned, or it floats over the results column as you scroll. */
            [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has(.st-key-setup) {{
                position: static !important;
                top: auto !important;
            }}
        }}

        /* Phone layout: keep the fixed toolbar off the logo, give the page top
           room to clear it, shrink the brand header, and let the matrix scroll. */
        @media (max-width: 640px) {{
            /* Hide the scroll mini-logo entirely on phones: it otherwise
               re-enters mid-scroll and overlaps the top-left content. */
            #rs-minilogo {{ display: none !important; }}
            #rs-toolbar {{
                top: 0.4rem; right: 0.5rem; gap: 0.3rem;
                flex-wrap: wrap; justify-content: flex-end; max-width: 66vw;
            }}
            #rs-toolbar button {{
                font-size: 0.68rem; padding: 0.26rem 0.55rem;
                box-shadow: 1px 1px 0 var(--rs-ink);
            }}
            [data-testid="stMainBlockContainer"], .block-container {{
                padding-top: 4rem !important;
            }}
            .rs-head {{ gap: 0.5rem; margin-bottom: 1rem; }}
            .rs-head .rs-logo svg {{ max-width: 150px; }}
            .rs-head .rs-tag {{
                border-left: none; padding-left: 0;
                font-size: 0.8rem; max-width: 100%;
            }}
            .rs-matrix {{ min-width: 420px; }}
            .rs-matrix th, .rs-matrix td {{ padding: 0.45rem 0.5rem; font-size: 0.8rem; }}
        }}

        /* Status + alert surfaces: thin border + subtle depth */
        [data-testid="stExpander"],
        [data-testid="stStatus"],
        [data-testid="stNotification"],
        .stAlert {{
            border: 1px solid var(--rs-ink) !important;
            border-radius: 10px !important;
            box-shadow: var(--rs-depth-sm) !important;
        }}
        [data-testid="stExpander"] summary {{ font-weight: 600; }}

        /* Buttons: thin border with tactile dark-border depth */
        .stButton > button {{
            border: 1px solid var(--rs-ink);
            border-radius: 8px;
            box-shadow: var(--rs-depth-sm);
            background: #fff;
            color: var(--rs-ink);
            font-weight: 600;
            transition: transform 0.08s ease, box-shadow 0.08s ease, background 0.12s ease, color 0.12s ease;
        }}
        .stButton > button:hover {{
            background: #f3f6f8;
            border-color: var(--rs-ink);
            color: var(--rs-blue);
            transform: translate(-1px, -1px);
            box-shadow: 3px 3px 0 var(--rs-ink);
        }}
        .stButton > button:active {{
            transform: translate(2px, 2px);
            box-shadow: 0 0 0 var(--rs-ink);
        }}
        .stButton > button[kind="primary"] {{
            background: var(--rs-blue);
            color: #fff;
            border-color: var(--rs-blue);
        }}
        .stButton > button[kind="primary"]:hover {{
            background: var(--rs-blue-dark); color: #fff; border-color: var(--rs-blue-dark);
        }}

        /* Inputs */
        .stTextArea textarea,
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div {{
            border: 1px solid var(--rs-ink) !important;
            border-radius: 8px !important;
            background: #fff !important;
        }}

        /* Sidebar (unused in the two-column layout, kept light) */
        [data-testid="stSidebar"] {{
            background: #fff;
            border-right: 1px solid var(--rs-ink);
        }}

        /* Tabs */
        .stTabs [data-baseweb="tab-list"] {{ gap: 0.4rem; }}
        .stTabs [data-baseweb="tab"] {{
            border: 1px solid var(--rs-ink);
            border-radius: 8px 8px 0 0;
            background: #fff;
            font-weight: 600;
            padding: 0.35rem 0.9rem;
        }}
        .stTabs [aria-selected="true"] {{
            background: var(--rs-blue);
            border-color: var(--rs-blue);
            color: #fff !important;
        }}

        /* Matrix scroll wrapper: lets the table scroll sideways on narrow
           screens instead of crushing the columns. */
        .rs-matrix-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}

        /* Divergence matrix: collapsed grid so every line (incl. left) renders */
        .rs-matrix {{
            border-collapse: collapse;
            width: 100%;
            border: 1px solid var(--rs-ink);
            border-radius: 10px;
            overflow: hidden;
            box-shadow: var(--rs-depth);
        }}
        .rs-matrix th, .rs-matrix td {{
            border: 1px solid var(--rs-ink);
            padding: 0.6rem 0.8rem;
            text-align: center;
            font-size: 0.88rem;
        }}
        .rs-matrix th {{ background: #f3f6f8; color: var(--rs-ink); font-weight: 700; }}
        .rs-matrix th.rs-theme-head, .rs-matrix td.rs-theme {{ text-align: left; font-weight: 600; }}
        .rs-cell-on {{ background: var(--rs-blue); color: #fff; font-weight: 700; }}
        .rs-cell-off {{ background: #fff; color: #c2c8cd; }}

        /* Obligation card */
        .rs-oblig {{
            border: 1px solid var(--rs-ink);
            border-radius: 8px;
            box-shadow: var(--rs-depth-sm);
            background: #fff;
            padding: 0.85rem 1rem;
            margin-bottom: 0.7rem;
        }}
        .rs-oblig-ref {{ font-weight: 700; color: var(--rs-blue); margin-bottom: 0.3rem; }}
        .rs-oblig-sum {{ color: var(--rs-ink); margin-bottom: 0.6rem; line-height: 1.45; }}
        .rs-meta {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.5rem; }}
        .rs-pill {{
            border: 1px solid #c9d1d8;
            border-radius: 50px;
            padding: 0.08rem 0.6rem;
            font-size: 0.72rem;
            font-weight: 600;
            background: #fff;
            color: var(--rs-muted);
        }}
        .rs-src {{
            display: inline-block;
            font-weight: 600;
            color: var(--rs-blue);
            text-decoration: none;
            border-bottom: 1px solid var(--rs-blue);
        }}
        .rs-src:hover {{ color: var(--rs-blue-dark); }}

        /* Dividers: subtle + tight */
        hr {{ border: none; border-top: 1px solid #e3e8ec; margin: 0.55rem 0; }}

        /* Semantic colour modifiers (shared by pills + badges) */
        .is-green {{ background: #e7f6ee; border-color: #1f9d57; color: #166b3c; }}
        .is-amber {{ background: #fef3e2; border-color: #d98a1f; color: #8a5a12; }}
        .is-red {{ background: #fdeaea; border-color: #d65a5a; color: #a23434; }}
        .is-blue {{ background: #e6f1f8; border-color: var(--rs-blue); color: var(--rs-blue-dark); }}
        .is-slate {{ background: #eef1f4; border-color: #9aa6b1; color: #51616f; }}

        /* Detailed-results metadata header */
        .rs-meta-row {{ display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin: 0.3rem 0 0.7rem; }}
        .rs-badge {{ font-size: 0.82rem; font-weight: 700; border-radius: 50px; padding: 0.18rem 0.75rem; border: 1px solid; }}
        .rs-label {{ font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--rs-muted); margin-top: 0.3rem; }}

        /* Note / summary card (white surface, blue left accent) */
        .rs-note {{
            border: 1px solid var(--rs-ink);
            border-left: 4px solid var(--rs-blue);
            border-radius: 8px;
            background: #fff;
            padding: 0.85rem 1rem;
            color: var(--rs-ink);
            line-height: 1.5;
            font-size: 0.92rem;
            margin: 0.4rem 0 0.6rem;
            box-shadow: var(--rs-depth-sm);
        }}
        .rs-note .rs-note-ico {{ color: var(--rs-blue); font-weight: 800; margin-right: 0.45rem; }}
        /* Feature-description note: warm yellow in the Print-button style
           (solid warm fill, amber border, hard offset shadow). */
        .rs-note.is-feature {{
            background: rgba(255, 255, 18, 0.1);
            border: 1px solid #e0b020;
            border-left: 4px solid #e0a52e;
            color: #5a4310;
        }}
        .rs-note.is-feature .rs-note-ico {{ color: #8a5a12; }}

        /* Quiet section label */
        .rs-section-label {{
            font-size: 0.78rem; font-weight: 700; text-transform: uppercase;
            letter-spacing: 0.05em; color: var(--rs-muted); margin: 0.9rem 0 0.5rem;
        }}

        /* Accordions (native <details>) */
        .rs-acc {{
            border: 1px solid var(--rs-ink);
            border-radius: 8px;
            background: #fff;
            margin-bottom: 0.6rem;
            overflow: hidden;
            box-shadow: var(--rs-depth-sm);
        }}
        .rs-acc > summary {{
            list-style: none;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 0.6rem;
            padding: 0.75rem 0.95rem;
            font-weight: 600;
        }}
        .rs-acc > summary::-webkit-details-marker {{ display: none; }}
        .rs-acc-title {{ flex: 1; }}
        .rs-acc-count {{
            background: var(--rs-blue); color: #fff; font-weight: 700;
            font-size: 0.72rem; border-radius: 50px; padding: 0.05rem 0.55rem;
        }}
        .rs-chev {{ transition: transform 0.15s ease; color: var(--rs-muted); font-size: 1.1rem; line-height: 1; }}
        .rs-acc[open] .rs-chev {{ transform: rotate(90deg); }}
        .rs-acc[open] > summary {{ border-bottom: 1px solid #e3e8ec; }}
        .rs-acc-body {{ padding: 0.85rem 0.95rem 0.2rem; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_chrome(export_md: str = "") -> None:
    """Inject the scroll mini-logo and the top-right toolbar.

    Done from a (same-origin) component iframe because Streamlit strips <script>
    from st.markdown. The script reaches window.parent.document to add a fixed
    top-left mini-logo (toggled by an IntersectionObserver on the header) and a
    top-right toolbar holding Copy Markdown / Download .md (only when results
    exist) and Print page. Guarded against duplicate nodes; the export buttons'
    handlers are rebound each run so the markdown stays current.
    """
    svg = load_logo()
    if not svg:
        return
    components.html(
        f"""
        <script>
        (function() {{
          try {{
            const svg = {json.dumps(svg)};
            const md = {json.dumps(export_md)};
            const doc = window.parent.document;
            const win = window.parent;
            if (!doc.getElementById('rs-minilogo')) {{
              const m = doc.createElement('div');
              m.id = 'rs-minilogo';
              m.innerHTML = svg;
              doc.body.appendChild(m);
            }}
            let bar = doc.getElementById('rs-toolbar');
            if (!bar) {{
              bar = doc.createElement('div');
              bar.id = 'rs-toolbar';
              doc.body.appendChild(bar);
            }}
            if (md) {{
              if (!doc.getElementById('rs-print-btn')) {{
                const b = doc.createElement('button');
                b.id = 'rs-print-btn';
                b.textContent = 'Print page';
                b.onclick = function() {{ win.print(); }};
                bar.appendChild(b);
              }}
              let c = doc.getElementById('rs-copy-btn');
              if (!c) {{
                c = doc.createElement('button');
                c.id = 'rs-copy-btn';
                bar.insertBefore(c, bar.firstChild);
              }}
              c.textContent = 'Copy Markdown';
              c.onclick = function() {{
                win.navigator.clipboard.writeText(md).then(function() {{
                  c.textContent = 'Copied!';
                  setTimeout(function() {{ c.textContent = 'Copy Markdown'; }}, 1500);
                }});
              }};
              let d = doc.getElementById('rs-dl-btn');
              if (!d) {{
                d = doc.createElement('button');
                d.id = 'rs-dl-btn';
                if (c.nextSibling) {{ bar.insertBefore(d, c.nextSibling); }} else {{ bar.appendChild(d); }}
              }}
              d.textContent = 'Download .md';
              d.onclick = function() {{
                const blob = new win.Blob([md], {{ type: 'text/markdown' }});
                const url = win.URL.createObjectURL(blob);
                const a = doc.createElement('a');
                a.href = url; a.download = 'regsphere_analysis.md';
                doc.body.appendChild(a); a.click(); a.remove();
                win.URL.revokeObjectURL(url);
              }};
            }} else {{
              // No results yet: keep the toolbar empty. Print / Copy / Download
              // only appear once an analysis has completed and results exist.
              ['rs-print-btn', 'rs-copy-btn', 'rs-dl-btn'].forEach(function(id) {{
                const e = doc.getElementById(id);
                if (e) {{ e.remove(); }}
              }});
            }}
            function attach() {{
              const head = doc.querySelector('.rs-head');
              const mini = doc.getElementById('rs-minilogo');
              if (head && mini && window.parent.IntersectionObserver) {{
                if (window.parent.__rsObs) {{ window.parent.__rsObs.disconnect(); }}
                const IO = window.parent.IntersectionObserver;
                const obs = new IO(function(entries) {{
                  entries.forEach(function(e) {{
                    mini.classList.toggle('visible', !e.isIntersecting);
                  }});
                }}, {{ root: null, threshold: 0 }});
                obs.observe(head);
                window.parent.__rsObs = obs;
                return true;
              }}
              return false;
            }}
            function bindFade() {{
              // Hide the bottom scroll-cue fade once the page is fully scrolled.
              // The handler re-queries .rs-fade each time so it survives reruns
              // (Streamlit replaces the node); listeners are bound only once.
              if (!win.__rsFadeUpdate) {{
                win.__rsFadeUpdate = function() {{
                  const f = doc.querySelector('.rs-fade');
                  if (!f) return;
                  const el = doc.scrollingElement || doc.documentElement;
                  const atBottom =
                    el.scrollHeight - (win.scrollY + win.innerHeight) <= 4;
                  f.classList.toggle('rs-fade-hidden', atBottom);
                }};
                win.addEventListener('scroll', win.__rsFadeUpdate, {{ passive: true }});
                win.addEventListener('resize', win.__rsFadeUpdate, {{ passive: true }});
              }}
              win.__rsFadeUpdate();
              return !!doc.querySelector('.rs-fade');
            }}
            function styleSegments() {{
              // Colour the Feature-input segments directly with inline
              // !important styles (beats every Streamlit rule) and match by
              // button text so it never depends on DOM order or class names.
              // "Preset archetypes" -> blue/white; "Custom description" ->
              // permanent #f4a261 with black text, in every state.
              const btns = doc.querySelectorAll('[data-testid="stButtonGroup"] button');
              btns.forEach(function(b) {{
                const t = (b.textContent || '').trim().toLowerCase();
                let bg = null, fg = null, bd = null;
                if (t === 'custom description') {{ bg = '#f4a261'; fg = '#000000'; bd = '#d98a3f'; }}
                else if (t === 'preset archetypes') {{ bg = '#006FAC'; fg = '#ffffff'; bd = '#006FAC'; }}
                if (bg) {{
                  b.style.setProperty('background', bg, 'important');
                  b.style.setProperty('border-color', bd, 'important');
                  b.style.setProperty('color', fg, 'important');
                  b.style.setProperty('opacity', '1', 'important');
                  if (t === 'custom description') {{
                    b.style.setProperty('font-weight', '700', 'important');
                  }}
                  b.querySelectorAll('*').forEach(function(c) {{
                    c.style.setProperty('color', fg, 'important');
                  }});
                }}
              }});
              // Re-apply after Streamlit re-renders the buttons (e.g. on toggle).
              // Observe only childList/subtree (not attributes) to avoid looping
              // on our own inline-style writes.
              if (!win.__rsSegObs && win.MutationObserver) {{
                win.__rsSegObs = new win.MutationObserver(function() {{ styleSegments(); }});
                win.__rsSegObs.observe(doc.body, {{ childList: true, subtree: true }});
              }}
              return btns.length > 0;
            }}
            let tries = 0;
            (function go() {{
              const ok = attach() && bindFade() && styleSegments();
              if (!ok && tries++ < 10) {{ setTimeout(go, 200); }}
            }})();
          }} catch (err) {{ /* same-origin guard; ignore */ }}
        }})();
        </script>
        """,
        height=0,
    )


def render_header() -> None:
    """Render the logo and tagline inline at the top of the content column."""
    logo = load_logo()
    tagline = "Cross-jurisdictional regulatory divergence engine"
    if logo:
        st.markdown(
            f'<div class="rs-head"><div class="rs-logo">{logo}</div>'
            f'<div class="rs-tag">{tagline}</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.title("RegSphere")
        st.caption(tagline)

    st.markdown(
        '<div class="rs-disclaimer"><span class="rs-disclaimer-ico">&#9888;</span>'
        "<span><b>Verify before you rely.</b> RegSphere reports regulations with "
        "citations, not legal advice. Open every linked source and do your own "
        "due diligence before acting on any result.</span></div>",
        unsafe_allow_html=True,
    )


def _set_all_jurisdictions(value: bool) -> None:
    """Callback for the Select all / None controls."""
    for code in JURISDICTIONS:
        st.session_state[f"jur_{code}"] = value


def render_config_panel() -> dict:
    """Render the configuration card and return the user's selections."""
    # Initialise jurisdiction toggles once (all on by default).
    for code in JURISDICTIONS:
        st.session_state.setdefault(f"jur_{code}", True)

    with st.container(border=True, key="setup"):
        st.markdown("#### Setup")

        # Feature input mode: segmented either/or switch
        mode_label = st.segmented_control(
            "Feature input",
            options=["Preset archetypes", "Custom description"],
            default="Preset archetypes",
            key="feature_mode_seg",
            width="stretch",
        )
        feature_mode = "custom" if mode_label == "Custom description" else "preset"

        if feature_mode == "preset":
            feature_options = {
                key: data["label"] for key, data in FEATURE_ARCHETYPES.items()
            }
            selected_feature = st.selectbox(
                "Feature archetype",
                options=list(feature_options.keys()),
                format_func=lambda x: feature_options[x],
            )
            st.markdown(
                '<div class="rs-note is-feature"><span class="rs-note-ico">&#9432;</span>'
                f'{html.escape(FEATURE_ARCHETYPES[selected_feature]["canonical_capability"])}'
                "</div>",
                unsafe_allow_html=True,
            )
            custom_feature_text = None
        else:
            selected_feature = None
            custom_feature_text = st.text_area(
                "Describe your AI feature",
                placeholder="e.g., An AI system that analyzes customer support calls to detect frustration and automatically escalate to human agents",
                height=120,
            )
            if custom_feature_text:
                st.caption(
                    "Your description is refined by Linkup's prompt optimizer "
                    "before analysis. Try Linkup yourself at "
                    "[app.linkup.so](https://app.linkup.so)."
                )
                if st.button("Preview optimized prompt", use_container_width=True):
                    with st.spinner("Optimizing with Linkup..."):
                        client = LinkupClient()
                        optimized = asyncio.run(
                            normalize_feature_description(client, custom_feature_text)
                        )
                    st.session_state["custom_optimized_src"] = custom_feature_text
                    st.session_state["custom_optimized"] = optimized

                # Show the optimized prompt once it matches the current text
                if (
                    st.session_state.get("custom_optimized_src") == custom_feature_text
                    and st.session_state.get("custom_optimized")
                ):
                    st.markdown(
                        '<div class="rs-label">Optimized prompt (used for analysis)</div>'
                        '<div class="rs-note is-feature"><span class="rs-note-ico">&#9432;</span>'
                        f'{html.escape(st.session_state["custom_optimized"])}</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.warning("Please describe your AI feature.")

        st.markdown("---")

        # Jurisdictions: title + live count, then Select all / None, then checkboxes
        selected_count = sum(
            1 for code in JURISDICTIONS if st.session_state.get(f"jur_{code}", True)
        )
        st.markdown(
            '<div class="rs-jur-head">'
            '<span class="rs-jur-title">Jurisdictions</span>'
            f'<span class="rs-jur-count">{selected_count} of {len(JURISDICTIONS)}</span>'
            "</div>",
            unsafe_allow_html=True,
        )
        col_all, col_none = st.columns(2)
        col_all.button(
            "Select all",
            use_container_width=True,
            on_click=_set_all_jurisdictions,
            args=(True,),
        )
        col_none.button(
            "None",
            use_container_width=True,
            on_click=_set_all_jurisdictions,
            args=(False,),
        )

        selected_jurisdictions = []
        for code, data in JURISDICTIONS.items():
            label = f'{FLAGS.get(code, "")} {data["name"]} ({code})'.strip()
            if st.checkbox(label, key=f"jur_{code}"):
                selected_jurisdictions.append(code)

        if not selected_jurisdictions:
            st.warning("Select at least one jurisdiction.")

        st.markdown("---")

        run_disabled = not selected_jurisdictions or (
            feature_mode == "custom" and not custom_feature_text
        )
        run_button = st.button(
            "Analyze",
            type="primary",
            disabled=run_disabled,
            use_container_width=True,
        )

    return {
        "feature_mode": feature_mode,
        "selected_feature": selected_feature,
        "custom_feature_text": custom_feature_text,
        "selected_jurisdictions": selected_jurisdictions,
        "run_button": run_button,
    }


def render_preview(selected_jurisdictions: list[str]) -> None:
    """Render placeholder result cards before the first analysis run.

    Deliberately neutral: it names the jurisdiction and its primary regulation
    but assigns NO verdict. The product never emits legal conclusions, least of
    all before any analysis has run.
    """
    st.markdown(
        '<div class="rs-preview-head">&#128065;&nbsp; Preview &mdash; press '
        "<b>Analyze</b> to generate the full report</div>",
        unsafe_allow_html=True,
    )

    codes = selected_jurisdictions or list(JURISDICTIONS.keys())
    cards = []
    for code in codes:
        data = JURISDICTIONS[code]
        name = html.escape(data["name"])
        reg = html.escape(data["primary_regulation"])
        cards.append(
            '<div class="rs-skel-card">'
            '<div class="rs-skel-head">'
            f'<span class="rs-skel-title">{name}</span>'
            '<span class="rs-skel-badge">Pending</span>'
            "</div>"
            f'<div class="rs-skel-meta">{reg}</div>'
            '<div class="rs-skel-bar w90"></div>'
            '<div class="rs-skel-bar w75"></div>'
            '<div class="rs-skel-bar w60"></div>'
            "</div>"
        )
    st.markdown(
        f'<div class="rs-preview-grid">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="rs-preview-foot">Each jurisdiction shows its framework '
        "status, key obligations with citations, and where it diverges from the "
        "others.</div>",
        unsafe_allow_html=True,
    )


def check_api_key() -> bool:
    """Check if LINKUP_API_KEY is configured."""
    return bool(os.getenv("LINKUP_API_KEY"))


async def run_single_jurisdiction(
    feature_key: str,
    jurisdiction: str,
    status_container: Any,
    custom_capability: str | None = None,
) -> JurisdictionResult:
    """Run the agent for one jurisdiction with status updates."""
    phrases = PROGRESS_PHRASES.get(jurisdiction, DEFAULT_PHRASES)
    flag = FLAGS.get(jurisdiction, "")
    status_container.update(
        label=f"{flag} {jurisdiction}: {phrases['build']}", state="running"
    )

    graph = build_graph()
    initial_state = {
        "feature_key": feature_key,
        "jurisdiction": jurisdiction,
        "attempt": 0,
        "log": [],
    }

    # Add custom capability if provided
    if custom_capability:
        initial_state["custom_capability"] = custom_capability

    status_container.update(
        label=f"{flag} {jurisdiction}: {phrases['search']}", state="running"
    )
    final_state = await graph.ainvoke(initial_state)

    result = final_state["parsed"]
    obligation_count = len(result.obligations)

    # Update with expandable content
    status_container.update(
        label=f"{flag} {jurisdiction}: {obligation_count} obligation(s) found",
        state="complete",
        expanded=True,
    )

    # Write summary content inside the status container
    with status_container:
        fw_label, _ = FRAMEWORK_LABELS.get(
            result.applicable_framework_status,
            (result.applicable_framework_status.replace("_", " ").title(), "is-slate"),
        )
        st.caption(f"**Framework:** {fw_label}")
        if result.regulation_classification:
            st.caption(f"**Classification:** {result.regulation_classification}")
        if obligation_count > 0:
            st.caption("**Obligations:**")
            for o in result.obligations[:5]:  # Show first 5
                st.caption(f"- {o.legal_reference}: {o.obligation_summary[:80]}...")
            if obligation_count > 5:
                st.caption(f"_...and {obligation_count - 5} more (see Detailed Results below)_")

    return result


async def run_analysis(
    feature_key: str,
    jurisdictions: list[str],
    status_containers: dict[str, Any],
    custom_capability: str | None = None,
) -> list[JurisdictionResult]:
    """Run analysis across all selected jurisdictions concurrently."""
    tasks = [
        run_single_jurisdiction(feature_key, j, status_containers[j], custom_capability)
        for j in jurisdictions
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle any exceptions
    processed_results = []
    for j, result in zip(jurisdictions, results):
        if isinstance(result, Exception):
            status_containers[j].update(
                label=f"{j}: Error - {str(result)[:50]}",
                state="error",
            )
        else:
            processed_results.append(result)

    return processed_results


def render_divergence_matrix(matrix: DivergenceMatrix) -> None:
    """Render the divergence matrix as a black-bordered grid."""
    st.subheader("Divergence Matrix")

    header_cells = "".join(
        f"<th>{html.escape(j)}</th>" for j in matrix.jurisdictions
    )
    rows = []
    for theme in matrix.themes:
        cells = []
        for j in matrix.jurisdictions:
            cell = matrix.get_cell(theme, j)
            if cell.has_obligations:
                cells.append(f'<td class="rs-cell-on">{cell.count}</td>')
            else:
                cells.append('<td class="rs-cell-off">--</td>')
        label = html.escape(THEME_LABELS.get(theme, theme))
        rows.append(f'<tr><td class="rs-theme">{label}</td>{"".join(cells)}</tr>')

    table = (
        '<div class="rs-matrix-wrap">'
        '<table class="rs-matrix">'
        f'<tr><th class="rs-theme-head">Theme</th>{header_cells}</tr>'
        f'{"".join(rows)}'
        "</table>"
        "</div>"
    )
    st.markdown(table, unsafe_allow_html=True)

    # Divergence summary: state WHAT diverges (which jurisdictions impose
    # obligations under each theme and which do not), not just the theme names.
    summary = matrix.divergence_summary()
    divergent = summary["themes_with_divergence"]
    if divergent:
        st.markdown("**Where jurisdictions diverge**")
        for theme in divergent:
            have = [
                j for j in matrix.jurisdictions
                if matrix.get_cell(theme, j).has_obligations
            ]
            lack = [j for j in matrix.jurisdictions if j not in have]
            label = THEME_LABELS.get(theme, theme)
            st.markdown(
                f"- **{label}:** obligations in {', '.join(have)}; "
                f"none identified in {', '.join(lack)}"
            )


def obligation_card_html(obligation: Obligation) -> str:
    """Return the HTML for a single obligation card (no rendering side effect)."""
    conf = (obligation.confidence or "").upper()
    conf_cls = CONFIDENCE_CLASS.get(conf, "is-slate")
    conf_label = f"{conf.title()} confidence" if conf else "Confidence n/a"

    pills = [f'<span class="rs-pill {conf_cls}">{html.escape(conf_label)}</span>']
    if obligation.enforcement_status:
        status = obligation.enforcement_status.replace("_", " ").title()
        pills.append(f'<span class="rs-pill">{html.escape(status)}</span>')
    if obligation.source_verified:
        pills.append('<span class="rs-pill is-green">Verified</span>')
    else:
        pills.append(
            '<span class="rs-pill is-amber" title="The source URL was returned by '
            "the search but could not be independently fetched. Open the link to "
            'verify manually.">Source not fetched</span>'
        )
    if obligation.enforcement_date:
        pills.append(
            f'<span class="rs-pill">Effective {html.escape(str(obligation.enforcement_date))}</span>'
        )

    source = ""
    if obligation.source_url:
        safe_url = html.escape(obligation.source_url, quote=True)
        source = f'<a class="rs-src" href="{safe_url}" target="_blank">Source &#8599;</a>'

    return (
        '<div class="rs-oblig">'
        f'<div class="rs-oblig-ref">{html.escape(obligation.legal_reference or "")}</div>'
        f'<div class="rs-oblig-sum">{html.escape(obligation.obligation_summary or "")}</div>'
        f'<div class="rs-meta">{"".join(pills)}</div>'
        f"{source}"
        "</div>"
    )


def accordion_html(title: str, count: int, cards: str) -> str:
    """Return a native <details> accordion with a pill count and rotating chevron."""
    return (
        '<details class="rs-acc"><summary>'
        f'<span class="rs-acc-title">{html.escape(title)}</span>'
        f'<span class="rs-acc-count">{count}</span>'
        '<span class="rs-chev">&#8250;</span></summary>'
        f'<div class="rs-acc-body">{cards}</div></details>'
    )


async def run_deep_dive(
    jurisdiction: str,
    feature_key: str,
) -> ResearchResult:
    """Run a deep dive research investigation for a jurisdiction."""
    jconf = JURISDICTIONS[jurisdiction]
    if feature_key == "_custom":
        capability = st.session_state.get(
            "custom_capability", "the described AI capability"
        )
    else:
        capability = FEATURE_ARCHETYPES[feature_key]["canonical_capability"]

    query = (
        f"Conduct a thorough investigation of all regulatory requirements, "
        f"guidance documents, enforcement actions, and compliance frameworks "
        f"from {jconf['regulator']} that apply to {capability}. "
        f"Include any recent updates, draft proposals, or pending legislation. "
        f"Focus on {jconf['primary_regulation']} and related sector-specific rules."
    )

    client = LinkupClient()
    return await research_deep_dive(
        client=client,
        query=query,
        include_domains=jconf["include_domains"],
    )


def render_deep_dive_result(result: ResearchResult) -> None:
    """Render a deep dive research result."""
    if result.status == "error" or result.status == "failed":
        st.error(f"Deep dive failed: {result.error}")
        return

    if result.status == "timeout":
        st.warning("Deep dive timed out. Try again later.")
        return

    if not result.answer:
        st.info("The deep dive returned no answer. Try again later.")
        return

    st.write(result.answer)

    if result.sources:
        with st.expander(f"Sources ({len(result.sources)})"):
            for source in result.sources:
                if isinstance(source, dict):
                    title = source.get("title", source.get("name", "Source"))
                    url = source.get("url", source.get("link", ""))
                    if url:
                        st.markdown(f"- [{title}]({url})")
                    else:
                        st.markdown(f"- {title}")
                else:
                    st.markdown(f"- {source}")


def results_to_markdown(
    results: list[JurisdictionResult],
    matrix: DivergenceMatrix,
) -> str:
    """Serialize the detailed results into a copy-pasteable Markdown document."""
    lines: list[str] = ["# RegSphere analysis", ""]
    for r in results:
        jname = JURISDICTIONS.get(r.jurisdiction, {}).get("name", r.jurisdiction)
        fw_label, _ = FRAMEWORK_LABELS.get(
            r.applicable_framework_status,
            (r.applicable_framework_status.replace("_", " ").title(), ""),
        )
        lines.append(f"## {jname} ({r.jurisdiction})")
        lines.append(f"- **Framework:** {fw_label}")
        lines.append(f"- **Overall confidence:** {r.overall_confidence or 'n/a'}")
        if r.regulation_classification:
            lines.append(f"- **Classification:** {r.regulation_classification}")
        if r.notes:
            lines.append(f"- **Notes:** {r.notes}")
        lines.append("")
        if not r.obligations:
            lines.append("_No obligations identified._")
            lines.append("")
            continue
        lines.append("### Obligations")
        for o in r.obligations:
            status = (o.enforcement_status or "").replace("_", " ").title()
            verified = "verified" if o.source_verified else "source not fetched"
            lines.append(
                f"- **{o.legal_reference}** "
                f"({status}; {o.confidence} confidence; {verified})"
            )
            lines.append(f"  - {o.obligation_summary}")
            if o.enforcement_date:
                lines.append(f"  - Effective: {o.enforcement_date}")
            if o.source_url:
                lines.append(f"  - Source: {o.source_url}")
        lines.append("")

    divergent = matrix.divergence_summary()["themes_with_divergence"]
    if divergent:
        lines.append("## Where jurisdictions diverge")
        for theme in divergent:
            have = [
                j for j in matrix.jurisdictions
                if matrix.get_cell(theme, j).has_obligations
            ]
            lack = [j for j in matrix.jurisdictions if j not in have]
            lines.append(
                f"- **{THEME_LABELS.get(theme, theme)}:** obligations in "
                f"{', '.join(have)}; none identified in {', '.join(lack)}"
            )
        lines.append("")
    return "\n".join(lines)


def render_deep_dive_panel(results: list[JurisdictionResult]) -> None:
    """Run a requested deep dive and render completed ones, below the tabs.

    Kept out of the tabs deliberately: Streamlit resets to the first tab on
    each rerun, so a spinner or result rendered inside a tab would be hidden.
    """
    requested = st.session_state.pop("deep_dive_request", None)
    if requested:
        jname = JURISDICTIONS.get(requested, {}).get("name", requested)
        with st.spinner(
            f"Running deep dive for {jname}. Linkup's research endpoint can take "
            "a few minutes; keep this tab open."
        ):
            feature_key = st.session_state.get("feature_key", "resume_screening")
            st.session_state[f"deep_dive_result_{requested}"] = asyncio.run(
                run_deep_dive(requested, feature_key)
            )

    shown_any = False
    for r in results:
        key = f"deep_dive_result_{r.jurisdiction}"
        if key in st.session_state:
            if not shown_any:
                st.markdown("---")
                shown_any = True
            jname = JURISDICTIONS.get(r.jurisdiction, {}).get("name", r.jurisdiction)
            st.markdown(f"#### Deep dive: {jname}")
            render_deep_dive_result(st.session_state[key])


def render_detailed_results(
    results: list[JurisdictionResult],
    matrix: DivergenceMatrix,
) -> None:
    """Render detailed results with per-jurisdiction tabs.

    The Markdown copy/download lives in the fixed top-right toolbar (see
    inject_chrome), beside Print.
    """
    st.subheader("Detailed Results")

    # Create tabs for each jurisdiction
    tabs = st.tabs(matrix.jurisdictions)

    for tab, result in zip(tabs, results):
        with tab:
            # Framework + confidence as human-readable badges (no raw enum codes)
            fw = result.applicable_framework_status
            fw_label, fw_cls = FRAMEWORK_LABELS.get(
                fw, (fw.replace("_", " ").title(), "is-slate")
            )
            conf = (result.overall_confidence or "").upper()
            conf_cls = CONFIDENCE_CLASS.get(conf, "is-slate")
            conf_label = f"{conf.title()} confidence" if conf else "Confidence n/a"
            st.markdown(
                '<div class="rs-meta-row">'
                f'<span class="rs-badge {fw_cls}">{html.escape(fw_label)}</span>'
                f'<span class="rs-pill {conf_cls}">{html.escape(conf_label)}</span>'
                "</div>",
                unsafe_allow_html=True,
            )

            if result.regulation_classification:
                st.markdown(
                    '<div class="rs-label">Classification</div>'
                    '<div style="margin-bottom:0.5rem;">'
                    f"{html.escape(result.regulation_classification)}</div>",
                    unsafe_allow_html=True,
                )

            if result.notes:
                st.markdown(
                    '<div class="rs-note"><span class="rs-note-ico">&#9432;</span>'
                    f"{html.escape(result.notes)}</div>",
                    unsafe_allow_html=True,
                )

            # Deep dive trigger. The run and result render below the tabs (see
            # render_deep_dive_panel) so they stay visible after the rerun.
            jname = JURISDICTIONS.get(result.jurisdiction, {}).get(
                "name", result.jurisdiction
            )
            if st.button(
                f"Deep dive into {jname} regulations",
                key=f"deep_dive_{result.jurisdiction}",
                help="Thorough investigation via Linkup's research endpoint (can take a few minutes)",
            ):
                st.session_state["deep_dive_request"] = result.jurisdiction

            # Empty state
            if not result.obligations:
                if result.applicable_framework_status == "NO_IDENTIFIED_REGULATION":
                    st.warning(
                        "No specific regulation identified for this feature "
                        "in this jurisdiction."
                    )
                elif result.overall_confidence == "LOW":
                    st.warning(
                        "Low confidence result. The search may not have found "
                        "all relevant regulations."
                    )
                else:
                    st.info("No obligations found.")
                continue

            # Obligations grouped into native accordions (custom HTML)
            st.markdown(
                '<div class="rs-section-label">Obligations by theme</div>',
                unsafe_allow_html=True,
            )

            accordions = []
            for theme in matrix.themes:
                cell = matrix.get_cell(theme, result.jurisdiction)
                if cell.has_obligations:
                    cards = "".join(obligation_card_html(o) for o in cell.obligations)
                    accordions.append(
                        accordion_html(
                            THEME_LABELS.get(theme, theme), cell.count, cards
                        )
                    )

            # Obligations that didn't match any theme
            themed = set()
            for theme in matrix.themes:
                for o in matrix.get_cell(theme, result.jurisdiction).obligations:
                    themed.add(id(o))
            unthemed = [o for o in result.obligations if id(o) not in themed]
            if unthemed:
                cards = "".join(obligation_card_html(o) for o in unthemed)
                accordions.append(
                    accordion_html("Other obligations", len(unthemed), cards)
                )

            st.markdown("".join(accordions), unsafe_allow_html=True)

    # Deep dive runs and results live BELOW the tabs so they remain visible no
    # matter which tab Streamlit shows after a rerun.
    render_deep_dive_panel(results)


def render_analysis_summary(results: list[JurisdictionResult]) -> None:
    """Compact one-line summary of a completed analysis with per-jurisdiction chips."""
    total = sum(len(r.obligations) for r in results)
    n = len(results)
    chips = "".join(
        f'<span class="rs-chip">{FLAGS.get(r.jurisdiction, "")} '
        f"{html.escape(r.jurisdiction)}<b>{len(r.obligations)}</b></span>"
        for r in results
    )
    st.markdown(
        '<div class="rs-summary">'
        '<span class="rs-summary-ico">&#10003;</span>'
        f'<span class="rs-summary-text">Analysis complete: {total} '
        f'obligation{"s" if total != 1 else ""} across {n} '
        f'jurisdiction{"s" if n != 1 else ""}</span>'
        f'<span class="rs-chips">{chips}</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def main() -> None:
    inject_styles()

    # Check API key
    if not check_api_key():
        render_header()
        st.error(
            "LINKUP_API_KEY is not set. Please add it to your .env file or "
            "set it as an environment variable."
        )
        st.stop()

    # Brand header spans the full width at the top so the logo sits top-left on
    # every layout. (Inside the right column it stacked below Setup on mobile.)
    render_header()

    left, right = st.columns([1, 2.2], gap="large")

    with left:
        cfg = render_config_panel()

    with right:
        # Trigger a run when Analyze is pressed
        if cfg["run_button"] and cfg["selected_jurisdictions"]:
            feature_mode = cfg["feature_mode"]
            custom_feature_text = cfg["custom_feature_text"]
            selected_feature = cfg["selected_feature"]
            selected_jurisdictions = cfg["selected_jurisdictions"]

            # Handle custom feature normalization. Reuse the previewed prompt if
            # it matches the current text; otherwise optimize now.
            if feature_mode == "custom" and custom_feature_text:
                if (
                    st.session_state.get("custom_optimized_src") == custom_feature_text
                    and st.session_state.get("custom_optimized")
                ):
                    normalized_capability = st.session_state["custom_optimized"]
                else:
                    with st.spinner("Optimizing your feature description with Linkup..."):
                        client = LinkupClient()
                        normalized_capability = asyncio.run(
                            normalize_feature_description(client, custom_feature_text)
                        )
                st.session_state["custom_capability"] = normalized_capability

            # Per-jurisdiction live progress, held in a placeholder so it can
            # collapse to a one-line summary once the run finishes.
            progress_area = st.empty()
            with progress_area.container():
                st.subheader("Analysis Progress")
                status_containers = {}
                pcols = st.columns(len(selected_jurisdictions))
                for i, j in enumerate(selected_jurisdictions):
                    with pcols[i]:
                        status_containers[j] = st.status(
                            f"{FLAGS.get(j, '')} {j}: Starting...", state="running"
                        )

            # No outer spinner: the per-jurisdiction st.status panels already
            # show live progress, so a second "Running..." animation is noise.
            if feature_mode == "custom":
                feature_key_to_use = "_custom"
                custom_cap = st.session_state.get(
                    "custom_capability", custom_feature_text
                )
            else:
                feature_key_to_use = selected_feature
                custom_cap = None

            results = asyncio.run(
                run_analysis(
                    feature_key_to_use,
                    selected_jurisdictions,
                    status_containers,
                    custom_cap,
                )
            )

            if not results:
                st.error(
                    "All jurisdiction analyses failed. Check your API key and try again."
                )
                st.stop()

            # Collapse the verbose live progress now that the run is done
            progress_area.empty()

            st.session_state["results"] = results
            st.session_state["feature_key"] = feature_key_to_use

        # Display results if available, otherwise the pre-run preview
        if st.session_state.get("results"):
            results = st.session_state["results"]

            render_analysis_summary(results)
            matrix = build_divergence_matrix(results)
            render_divergence_matrix(matrix)
            st.markdown("---")
            render_detailed_results(results, matrix)
        else:
            render_preview(cfg["selected_jurisdictions"])

    # Blue scroll-cue fade, hinting there is content below the fold
    st.markdown(
        '<div class="rs-fade"><div class="rs-fade-chev">&#8964;</div></div>',
        unsafe_allow_html=True,
    )

    # Scroll mini-logo + top-right toolbar (Copy/Download Markdown + Print).
    # The Markdown is built once here so the toolbar's export buttons are live.
    export_md = ""
    if st.session_state.get("results"):
        _res = st.session_state["results"]
        export_md = results_to_markdown(_res, build_divergence_matrix(_res))
    inject_chrome(export_md)


if __name__ == "__main__":
    main()
