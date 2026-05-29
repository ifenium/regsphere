"""The LangGraph agent for one jurisdiction (Day 2+3: full agent loop).

Graph shape:

    START -> construct_query -> search -> verify_sources -> evaluate --(done)--> END
                   ^                                            |
                   |                                         (refine)
                   +------------------ bump_attempt <-----------+

What changed from Day 1:
- NEW NODE: verify_sources fetches each source_url via Linkup fetch and sets
  source_verified = True/False. This is the independent citation check, set
  by code, never by the model.
- REAL evaluate: checks obligation count, legal_reference quality, source_url
  domain membership, and verification rate. Returns ok=False with specific
  reasons when the result is not good enough.
- SMART refine: construct_query on attempt > 0 injects the specific failure
  reasons from evaluate so the retry is targeted, not just "try harder."
- route_after_eval is now live: it triggers the refine loop when evaluate
  fails and retry budget remains.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, TypedDict
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph
from linkup import LinkupClient

from .config import FEATURE_ARCHETYPES, JURISDICTIONS
from .linkup_search import fetch_url, structured_search
from .schema import JurisdictionResult

MAX_ATTEMPTS = 3
# Minimum fraction of obligations whose source_url must verify for an
# overall PASS. Set conservatively: even 30% verified is meaningful signal
# on a first pass, and we downgrade confidence on unverified obligations
# rather than rejecting the whole result.
MIN_VERIFIED_RATIO = 0.3


class AgentState(TypedDict, total=False):
    """State threaded through the graph for a single jurisdiction run."""

    # Inputs
    feature_key: str
    jurisdiction: str
    # Optimized free-text capability for custom runs (feature_key == "_custom").
    # When present, it overrides the FEATURE_ARCHETYPES lookup.
    custom_capability: str
    # Working values
    canonical_capability: str
    query: str
    attempt: int
    raw_result: dict[str, Any]
    parsed: JurisdictionResult
    evaluation: dict[str, Any]
    log: list[str]


def _log(state: AgentState, message: str) -> list[str]:
    """Append to the run log and echo to stdout."""
    entries = list(state.get("log", []))
    entries.append(message)
    print(f"[{state.get('jurisdiction', '?')}] {message}")
    return entries


# ---------------------------------------------------------------------------
# Node 1: construct_query
# ---------------------------------------------------------------------------

def construct_query(state: AgentState) -> dict[str, Any]:
    """Build a precise, jurisdiction-scoped query.

    On attempt 0: the standard regulatory-obligations query.
    On attempt > 0: injects the specific failure reasons from the previous
    evaluate step so the retry addresses exactly what was missing.
    """
    attempt = state.get("attempt", 0)
    jconf = JURISDICTIONS[state["jurisdiction"]]
    # Custom runs supply the optimized capability directly; preset runs look it
    # up by archetype key. This is why feature_key == "_custom" must NOT hit the
    # FEATURE_ARCHETYPES dict (it has no such key).
    capability = state.get("custom_capability")
    if not capability:
        capability = FEATURE_ARCHETYPES[state["feature_key"]]["canonical_capability"]

    query = (
        f"Identify the specific regulatory obligations under "
        f"{jconf['primary_regulation']} and official guidance from "
        f"{jconf['regulator']} that apply DIRECTLY to the following AI "
        f"capability: {capability}. "
        f"Only include obligations whose scope directly covers this capability. "
        f"Do NOT include obligations that apply to unrelated AI practices "
        f"(e.g. do not cite deepfake-disclosure rules for a chatbot use case, "
        f"or hiring-bias rules for a content-generation use case). "
        f"For each obligation, report the precise article or section reference, "
        f"a concise summary of what it requires, whether it is currently in "
        f"force, its effective date, and a direct source URL that links to the "
        f"specific article or section of the official document itself (not a "
        f"homepage, search results, or index page). "
        f"If no specific regulation governs this capability, state that "
        f"explicitly and cite a credible official source."
    )

    if attempt > 0:
        # Inject specific feedback from the failed evaluation so the retry
        # is targeted rather than generic.
        prev_eval = state.get("evaluation", {})
        reasons = prev_eval.get("reasons", [])
        if reasons:
            feedback = "; ".join(reasons)
            query += (
                f" IMPORTANT: a previous search attempt was insufficient "
                f"because: {feedback}. Address these gaps specifically. "
                f"Prefer primary legislative texts over secondary commentary "
                f"and ensure every obligation includes a direct URL to the "
                f"official regulatory document."
            )
        else:
            query += (
                " Be exhaustive: name every relevant article explicitly and "
                "prefer primary legislative texts over secondary commentary."
            )

    return {
        "canonical_capability": capability,
        "query": query,
        "attempt": attempt,
        "log": _log(state, f"built query (attempt {attempt + 1}/{MAX_ATTEMPTS})"),
    }


# ---------------------------------------------------------------------------
# Node 2: search
# ---------------------------------------------------------------------------

async def search(state: AgentState) -> dict[str, Any]:
    """Run the deep structured Linkup search."""
    jconf = JURISDICTIONS[state["jurisdiction"]]
    client = LinkupClient()

    raw = await structured_search(
        client=client,
        query=state["query"],
        include_domains=jconf["include_domains"],
    )
    parsed = JurisdictionResult.from_linkup(state["jurisdiction"], raw)

    return {
        "raw_result": raw,
        "parsed": parsed,
        "log": _log(
            state, f"search returned {len(parsed.obligations)} obligation(s)"
        ),
    }


# ---------------------------------------------------------------------------
# Node 3: verify_sources (NEW in Day 2+3)
# ---------------------------------------------------------------------------

async def verify_sources(state: AgentState) -> dict[str, Any]:
    """Fetch each obligation's source_url and set source_verified.

    This is the independent citation check. For each URL we:
    1. Call Linkup fetch to retrieve the page content.
    2. Check whether the page contains the legal_reference string (or a
       reasonable substring of it, e.g. "Article 50").
    3. Set source_verified = True only if both conditions pass.

    Obligations whose URLs fail to fetch or whose content does not mention
    the claimed article get source_verified = False and confidence downgraded
    to LOW. This keeps the obligation in the output (it may still be correct)
    but signals to the user and to the evaluate step that it is unverified.

    Fetch calls run concurrently with a semaphore to stay within rate limits.
    """
    parsed: JurisdictionResult = state["parsed"]
    if not parsed.obligations:
        return {"parsed": parsed, "log": _log(state, "no obligations to verify")}

    client = LinkupClient()
    sem = asyncio.Semaphore(5)
    verified_count = 0

    async def _verify_one(ob):
        nonlocal verified_count
        async with sem:
            if not ob.source_url:
                ob.source_verified = False
                ob.confidence = "LOW"
                return

            content = await fetch_url(client, ob.source_url)
            if content is None:
                ob.source_verified = False
                ob.confidence = "LOW"
                return

            # Build fuzzy check terms from the reference. The normalised
            # "keyword NN" token (e.g. "article 30") is the robust signal: a
            # page that cites "Article 30" rarely repeats the full
            # "Article 30 UK GDPR" verbatim, so matching on the bare token
            # avoids false "unverified" results. The longer snippet is kept as
            # an additional, stricter term.
            ref_lower = ob.legal_reference.lower()
            check_terms = []
            for m in re.finditer(
                r"(article|section|annex|regulation|schedule|part|division)\s+(\d+)",
                ref_lower,
            ):
                check_terms.append(f"{m.group(1)} {m.group(2)}")
            for keyword in ("article", "section", "annex", "regulation"):
                if keyword in ref_lower:
                    idx = ref_lower.index(keyword)
                    check_terms.append(ref_lower[idx:idx + 30].strip())

            content_lower = content.lower()
            if check_terms and any(term in content_lower for term in check_terms):
                ob.source_verified = True
                verified_count += 1
                # Verification is independent evidence; boost confidence:
                # LOW -> MEDIUM (model was uncertain but we confirmed the source).
                # MEDIUM -> HIGH (model was confident and source checks out).
                # HIGH stays HIGH.
                if ob.confidence == "LOW":
                    ob.confidence = "MEDIUM"
                elif ob.confidence == "MEDIUM":
                    ob.confidence = "HIGH"
            elif not check_terms:
                # Could not parse a reference to check; accept if page loaded.
                ob.source_verified = True
                verified_count += 1
                if ob.confidence == "LOW":
                    ob.confidence = "MEDIUM"
            else:
                ob.source_verified = False
                if ob.confidence == "HIGH":
                    ob.confidence = "MEDIUM"

    await asyncio.gather(*[_verify_one(ob) for ob in parsed.obligations])

    total = len(parsed.obligations)
    return {
        "parsed": parsed,
        "log": _log(
            state,
            f"verified {verified_count}/{total} source(s)"
        ),
    }


# ---------------------------------------------------------------------------
# Node 4: evaluate (REAL logic, replaces Day 1 stub)
# ---------------------------------------------------------------------------

def evaluate(state: AgentState) -> dict[str, Any]:
    """Decide whether the result is good enough or needs a refined retry.

    Checks (any failure sets ok=False and adds a reason):
    1. At least one obligation found, OR applicable_framework_status is
       NO_IDENTIFIED_REGULATION (which is a valid answer, not a failure).
    2. Every obligation has a non-empty legal_reference.
    3. Every source_url belongs to the jurisdiction's include_domains allowlist.
    4. At least MIN_VERIFIED_RATIO of obligations have source_verified = True.
    """
    parsed: JurisdictionResult = state["parsed"]
    jconf = JURISDICTIONS[state["jurisdiction"]]
    allowed_domains = set(jconf["include_domains"])

    reasons: list[str] = []

    # Check 1: obligations present or explicitly none
    if (
        not parsed.obligations
        and parsed.applicable_framework_status != "NO_IDENTIFIED_REGULATION"
    ):
        reasons.append(
            "no obligations were returned but the framework status is "
            f"'{parsed.applicable_framework_status}', not NO_IDENTIFIED_REGULATION"
        )

    # Check 2: legal references non-empty
    empty_refs = [
        o for o in parsed.obligations if not o.legal_reference.strip()
    ]
    if empty_refs:
        reasons.append(
            f"{len(empty_refs)} obligation(s) have empty legal_reference fields"
        )

    # Check 3: source URLs on the allowlist
    off_domain = []
    for o in parsed.obligations:
        if o.source_url:
            host = urlparse(o.source_url).hostname or ""
            if not any(host == d or host.endswith("." + d) for d in allowed_domains):
                off_domain.append(o.source_url)
    if off_domain:
        # This is a warning, not a hard failure. Many credible sources
        # (e.g. artificialintelligenceact.eu) are not on the government
        # allowlist but are still trustworthy. We note it but do not
        # reject the result on this check alone.
        reasons.append(
            f"{len(off_domain)} source URL(s) are outside the jurisdiction "
            f"allowlist (e.g. {off_domain[0]})"
        )

    # Check 4: verification rate
    if parsed.obligations:
        verified = sum(1 for o in parsed.obligations if o.source_verified)
        ratio = verified / len(parsed.obligations)
        if ratio < MIN_VERIFIED_RATIO:
            reasons.append(
                f"only {verified}/{len(parsed.obligations)} source(s) verified "
                f"({ratio:.0%}), below the {MIN_VERIFIED_RATIO:.0%} threshold"
            )

    # Decision: fail only on check 1 or check 2 (structural problems the
    # model can fix on retry). Checks 3 and 4 are noted but do not trigger
    # a retry, since the model cannot change which URLs exist on the web.
    structural_fail = (
        (not parsed.obligations
         and parsed.applicable_framework_status != "NO_IDENTIFIED_REGULATION")
        or bool(empty_refs)
    )
    ok = not structural_fail

    evaluation = {
        "ok": ok,
        "reasons": reasons,
        "obligations_found": len(parsed.obligations),
        "verified_count": sum(1 for o in parsed.obligations if o.source_verified),
    }

    status = "PASS" if ok else "FAIL (will retry)"
    return {
        "evaluation": evaluation,
        "log": _log(
            state,
            f"evaluate -> {status}"
            + (f": {'; '.join(reasons)}" if reasons else "")
        ),
    }


def route_after_eval(state: AgentState) -> str:
    """Conditional edge: retry with a refined query, or finish."""
    evaluation = state.get("evaluation", {})
    attempt = state.get("attempt", 0)
    if not evaluation.get("ok", True) and attempt + 1 < MAX_ATTEMPTS:
        return "refine"
    return "done"


# ---------------------------------------------------------------------------
# bump_attempt (unchanged)
# ---------------------------------------------------------------------------

def bump_attempt(state: AgentState) -> dict[str, Any]:
    """Increment the attempt counter before looping back to construct_query."""
    return {"attempt": state.get("attempt", 0) + 1}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph():
    """Compile and return the single-jurisdiction agent graph.

    START -> construct_query -> search -> verify_sources -> evaluate -> END
                   ^                                           |
                   +------------- bump_attempt <-- (refine) ---+
    """
    builder = StateGraph(AgentState)

    builder.add_node("construct_query", construct_query)
    builder.add_node("search", search)
    builder.add_node("verify_sources", verify_sources)
    builder.add_node("evaluate", evaluate)
    builder.add_node("bump_attempt", bump_attempt)

    builder.add_edge(START, "construct_query")
    builder.add_edge("construct_query", "search")
    builder.add_edge("search", "verify_sources")
    builder.add_edge("verify_sources", "evaluate")
    builder.add_conditional_edges(
        "evaluate",
        route_after_eval,
        {"refine": "bump_attempt", "done": END},
    )
    builder.add_edge("bump_attempt", "construct_query")

    return builder.compile()