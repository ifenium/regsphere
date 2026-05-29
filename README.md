# RegSphere

A cross-jurisdictional regulatory divergence engine for AI and automated-decision product features. Describe a feature, and RegSphere reports the regulatory obligations that attach to it in each jurisdiction, each tied to a specific legal reference and an independently verified source, then computes where the jurisdictions diverge.

It reports facts about regulations with citations. It never emits a legal conclusion such as "banned" or "allowed", and it never tells you your feature is illegal.

## What it does

For one feature it runs four jurisdictions (EU, US, UK, SG) concurrently. Each run is a LangGraph agent that constructs a jurisdiction-scoped query, runs a deep structured Linkup search pinned to that jurisdiction's official sources, independently fetches every cited URL to verify the legal reference, evaluates the result, and refines on a targeted retry when needed. It then computes a theme-by-jurisdiction divergence matrix and shows where the regimes differ.

```
streamlit run app.py     # full UI: presets or custom feature, divergence matrix, per-jurisdiction detail, deep dive, markdown export
python main.py           # CLI: concurrent 4-jurisdiction run, comparison table and divergence matrix
python main.py emotion_recognition_hiring
python main.py deepfake_generation
python main.py behavioural_scoring
python main.py undisclosed_chatbot
```

## Setup

```
pip install -r requirements.txt
cp .env.example .env        # then add your LINKUP_API_KEY
streamlit run app.py
```

Confirm the wiring without an API key:

```
python -c "from regsphere.graph import build_graph; build_graph(); print('graph OK')"
```

## Deploy to Streamlit Community Cloud

1. Push this folder to a new public GitHub repository.
2. On [share.streamlit.io](https://share.streamlit.io), create a new app from that repo.
3. Set the main file path to `app.py`.
4. Under **Advanced settings -> Secrets**, add your key (TOML format):

   ```
   LINKUP_API_KEY = "your-linkup-api-key-here"
   ```

   Streamlit exposes secrets as environment variables, so `app.py` reads it with no code change. Never commit `.env` or a real key to the repo.

## Why this is not a thin wrapper

A single parameterised search call is a wrapper regardless of how many parameters it takes. RegSphere is the agent loop around the call:

- **construct, search, verify, evaluate, refine** as distinct nodes, with targeted feedback injected into the retry.
- Three Linkup endpoints each doing a separate job: `search` (extraction), `fetch` (independent citation verification), `research` (optional deep dive).
- Per-jurisdiction trusted-source allowlists (`include_domains`) encode the domain expertise. The curated allowlist is the asset, not the API call.
- Cross-jurisdictional comparison is the whole product, not a feature.

## Architecture

A LangGraph state machine, one run per jurisdiction, all four run concurrently via `asyncio.gather`:

```
START -> construct_query -> search -> verify_sources -> evaluate --(done)--> END
               ^                                            |
               +------------------ bump_attempt <--(refine)-+
```

- **construct_query** normalises the feature into a canonical capability and fills a jurisdiction-specific template naming the correct regulator and primary regulation. On a refine pass it injects the specific failure reasons from evaluate. The raw feature is never passed straight to the API.
- **search** runs a deep, structured Linkup search scoped with `include_domains`, parsed into typed `JurisdictionResult` / `Obligation` objects.
- **verify_sources** fetches each obligation's `source_url` via Linkup `fetch` and checks the page for the claimed reference, setting `source_verified` in code. It retries with JS rendering for script-heavy sites.
- **evaluate** checks obligation presence, non-empty legal references, source domains, and verification rate, and triggers a targeted retry on structural failure.
- **bump_attempt** increments the retry counter (max 3 attempts).

## Design notes

- `source_verified` is **not** in the schema sent to Linkup. It is set only by the fetch-based verification step, never by the model. The model extracts; verifying citations is the engine's job. Obligations whose source cannot be independently fetched are surfaced honestly as "source not fetched", not hidden.
- Recency is handled by the `enforcement_status` field (`IN_FORCE`, `ADOPTED_NOT_YET_IN_FORCE`, `PROPOSED`, `DRAFT`), reasoned about explicitly, not by a date filter on page age.
- Divergence is computed deterministically in code (no LLM call) by tagging obligations into a fixed theme taxonomy and comparing across jurisdictions.

## Files

```
app.py                        Streamlit UI (run with: streamlit run app.py)
main.py                       CLI entry point, concurrent 4-jurisdiction runner
requirements.txt
.env.example
.streamlit/config.toml        brand theme
regsphere/
  config.py                   jurisdictions (domain allowlists) and feature archetypes
  schema.py                   Linkup JSON schema + typed dataclasses
  linkup_search.py            async wrappers: structured_search, fetch_url, research_deep_dive
  graph.py                    the LangGraph agent (all nodes and graph builder)
  divergence.py               theme taxonomy, obligation tagging, divergence matrix
```
