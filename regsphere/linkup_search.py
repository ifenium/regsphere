"""Thin async wrappers around Linkup search, fetch, and research endpoints.

This module is just the retrieval primitive. All of the agent logic (query
construction, evaluation, the refine loop) lives in graph.py. Keeping the
API call this thin makes it obvious that the intelligence is in the graph,
not in the wrapper.

Day 3 adds fetch_url() for source verification.
Day 5 adds research_deep_dive() for single-jurisdiction deep investigation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from linkup import LinkupClient

from .schema import LINKUP_SCHEMA


def _to_dict(response: Any) -> dict[str, Any]:
    """Normalise a Linkup structured response into a plain dict.

    Depending on the installed SDK version, a `structured` response may come
    back as a plain dict or as a pydantic-style object exposing model_dump().
    This handles both so the rest of the code can assume a dict.
    """
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "__dict__"):
        return dict(vars(response))
    raise TypeError(f"Unexpected Linkup response type: {type(response)!r}")


def _extract_text(response: Any) -> str:
    """Extract text content from a Linkup fetch response.

    The fetch response structure varies by SDK version. This handles
    common shapes: direct string, dict with 'content' or 'text', or
    object with those attributes.
    """
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        return response.get("content", response.get("text", response.get("markdown", str(response))))
    if hasattr(response, "markdown"):
        return str(response.markdown)
    if hasattr(response, "content"):
        return str(response.content)
    if hasattr(response, "text"):
        return str(response.text)
    return str(response)


async def structured_search(
    client: LinkupClient,
    query: str,
    include_domains: list[str],
) -> dict[str, Any]:
    """Run one deep, structured, domain-scoped Linkup search.

    - depth="deep": agentic multi-step search and scrape, needed because a
      regulatory question is not a single-shot lookup.
    - output_type="structured": forces the result into our JSON schema so
      jurisdictions are directly comparable downstream.
    - include_domains: pins retrieval to the jurisdiction's official sources.

    Note on the parameter name: the Python SDK uses snake_case
    (`include_domains`) for the API's `includeDomains`. If a future SDK
    version renames it, this function is the single place to change.
    """
    response = await client.async_search(
        query=query,
        depth="deep",
        output_type="structured",
        structured_output_schema=LINKUP_SCHEMA,
        include_domains=include_domains,
    )
    return _to_dict(response)


async def fetch_url(client: LinkupClient, url: str) -> str | None:
    """Fetch the content of a URL via Linkup's fetch endpoint.

    Used by the verify_sources node to check whether a source URL actually
    contains the claimed legal reference.

    Returns the page text content, or None if the fetch fails.
    """
    if not url:
        return None

    async def _try(render_js: bool) -> str | None:
        try:
            return _extract_text(await client.async_fetch(url=url, render_js=render_js))
        except Exception:
            # Fetch failures are expected (dead links, paywalls, etc.)
            return None

    # First attempt without JS rendering (fast). If it comes back empty or
    # suspiciously short, retry with JS rendering: some official sites
    # (e.g. ico.org.uk) serve their content via client-side scripts.
    content = await _try(render_js=False)
    if not content or len(content) < 200:
        retried = await _try(render_js=True)
        if retried and (not content or len(retried) > len(content)):
            content = retried
    return content


# --- Prompt optimization (Day 5) ---------------------------------------------

async def normalize_feature_description(
    client: LinkupClient,
    user_input: str,
) -> str:
    """Normalize a user's free-text feature description into a canonical capability.

    Uses Linkup's search with sourcedAnswer to refine vague user input into
    a precise, searchable AI capability description. This helps ensure
    consistent query quality regardless of how users phrase their input.

    Args:
        client: The Linkup client instance.
        user_input: The user's free-text feature description.

    Returns:
        A normalized, expanded capability description suitable for regulatory search.
    """
    prompt = (
        f"Rewrite the following AI feature description into a precise, formal "
        f"capability statement suitable for regulatory analysis. Include what "
        f"the system does, what data it processes, and who it affects. "
        f"Keep it to 2-3 sentences. Feature: {user_input}"
    )

    try:
        response = await client.async_search(
            query=prompt,
            depth="standard",  # Fast, just need reformulation
            output_type="sourcedAnswer",
        )

        # Extract the answer text
        if hasattr(response, "answer"):
            return response.answer
        if isinstance(response, dict):
            return response.get("answer", response.get("text", user_input))
        return user_input  # Fallback to original if parsing fails

    except Exception:
        # If normalization fails, use the original input
        return user_input


# --- Research endpoint (Day 5 stretch) ---------------------------------------

@dataclass
class ResearchResult:
    """Result from a Linkup research deep dive."""

    query: str
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"
    error: str | None = None


async def research_deep_dive(
    client: LinkupClient,
    query: str,
    include_domains: list[str] | None = None,
    poll_interval: float = 3.0,
    max_wait: float = 480.0,
) -> ResearchResult:
    """Run a deep research investigation using Linkup's research endpoint.

    This uses mode="investigate" for thorough exploration of a topic,
    suitable for deep dives into a single jurisdiction's regulatory landscape.

    Args:
        client: The Linkup client instance.
        query: The research question to investigate.
        include_domains: Optional domain allowlist to restrict sources.
        poll_interval: Seconds between status checks (default 3s).
        max_wait: Maximum seconds to wait for completion (default 480s / 8 min).
            Investigate-mode research on a restricted domain allowlist routinely
            runs ~5-6 minutes, so the budget must stay well above that.

    Returns:
        ResearchResult with the answer and supporting sources.
    """
    try:
        # Create the research task
        task = await client.async_research(
            query=query,
            output_type="sourcedAnswer",
            mode="investigate",
            reasoning_depth="M",  # Medium depth - balance between speed and thoroughness
            include_domains=include_domains,
        )

        # Poll for completion
        elapsed = 0.0
        while task.status in ("pending", "processing") and elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            task = await client.async_get_research(task.id)

        # Handle result
        if task.status == "failed":
            return ResearchResult(
                query=query,
                answer="",
                status="failed",
                error=task.error or "Research task failed",
            )

        if task.status != "completed":
            return ResearchResult(
                query=query,
                answer="",
                status="timeout",
                error=f"Research timed out after {max_wait}s",
            )

        # Extract answer and sources from output
        output = task.output
        if output is None:
            return ResearchResult(
                query=query,
                answer="No results returned",
                status="completed",
            )

        # Handle different output formats
        if hasattr(output, "model_dump"):
            output = output.model_dump()
        elif not isinstance(output, dict):
            output = {"answer": str(output)}

        answer = output.get("answer", output.get("text", str(output)))
        sources = output.get("sources", [])

        return ResearchResult(
            query=query,
            answer=answer,
            sources=sources if isinstance(sources, list) else [],
            status="completed",
        )

    except Exception as e:
        return ResearchResult(
            query=query,
            answer="",
            status="error",
            error=str(e),
        )
