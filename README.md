# Financial Advisor (multi-agent, Gemini/cloud)

A multi-agent financial/investment advisor built on Google's [Agent
Development Kit](https://github.com/google/adk-python) (ADK), running on
Google's hosted **Gemini** API (via Vertex AI) with a Streamlit chat front
end, deployable to Streamlit Community Cloud.

This is a cloud-deployable fork of a sibling project that runs the same
multi-agent design entirely locally on open-source models via Ollama (no
API keys, nothing leaves the machine). That variant can't be hosted on
Streamlit Community Cloud, since a hosted container has no route to
`localhost` on a laptop — this fork swaps the model backend for Gemini,
which is reachable from a hosted container, in exchange for needing a GCP
service account.

**Educational demo only — not licensed financial advice.**

## Architecture

```
financial_advisor/
  agent.py                    root_agent: "financial_coordinator" (deterministic gate) ->
                               user_profile | financial_dashboard | specialist_router
  config.py                   Gemini model config (gemini-3.5-flash by default)
  models.py                   GlobalGemini — Gemini via Vertex AI, pinned to the 'global' endpoint
  profile_store.py            per-user JSON persistence + schema for the financial profile
  dashboard_store.py          per-user JSON persistence + computed metrics (net worth, cash flow,
                               savings rate) + budgeting/investing guidance (50/30/20, emergency-
                               fund-first) + spending-category breakdown with guideline checks
  wisdom_store.py              curated, attributed personal-finance principles (Dave Ramsey, Bogle,
                                Buffett, the 4% rule, etc.) — hand-authored, not LLM recall
  tools/
    market_data.py            yfinance-backed: price, fundamentals, history, market overview
    profile_tools.py          get_profile / update_profile_field, backed by profile_store.py
    dashboard_tools.py        get_dashboard_status / update_dashboard_field, backed by dashboard_store.py
    wisdom_tools.py            get_financial_wisdom, backed by wisdom_store.py
    web_search_tools.py        search_financial_advice — DuckDuckGo search (no API key), filtered to
                                a trusted-domain allowlist, plus callbacks that force real grounding
                                and strip fabricated citations
  sub_agents/
    user_profile/               friendly onboarding agent + deterministic capture callbacks
    financial_dashboard/        deterministic field-capture + summary, then an optional spending-
                                 breakdown stage, wrapping an LLM for follow-ups
    risk_profiler/               assesses risk tolerance
    portfolio_analyst/           allocation / diversification analysis
    market_research/             ticker + broad-market lookups
streamlit_app.py               chat UI: ADK Runner + DatabaseSessionService, sidebar name field as
                                the multi-user identity gate (see below)
```

`root_agent` is a small custom `BaseAgent` (`FinancialCoordinator`), not a
plain LLM agent — each turn it checks completeness directly in Python and
deterministically routes to the first unfinished stage:

1. **`user_profile`** — required profile fields still missing.
2. **`financial_dashboard`** — required dashboard inputs missing, or the
   optional spending-category breakdown hasn't been offered yet.
3. **`specialist_router`** — once onboarding is resolved: an LLM agent
   that calls `risk_profiler` / `portfolio_analyst` / `market_research`
   **as a tool** (ADK's `AgentTool`) and answers from the result.

Routing/completeness gating is deterministic Python, not an LLM decision —
an earlier instruction-based version ("call get_profile, then branch") was
unreliable on small local models, which skipped straight to whatever
specialist a question superficially matched. See "Known limitations" for
what's still LLM-judged versus guaranteed by construction.

### Multi-user identity

Many independent visitors can hit the same deployed instance at once, so
identity can't come from a single global saved profile — that would show
every visitor whoever's name was saved last. Instead, the sidebar has a
plain `st.text_input("Your name", ...)`, separate from the chat itself,
and everything downstream is keyed off it:

- `user_id = raw_name.strip().lower().replace(" ", "_")` is both the ADK
  session's `user_id` and the filename key for that person's data
  (`financial_advisor/data/profiles/<user_id>.json`,
  `dashboards/<user_id>.json`; sanitized in `profile_store._safe_user_id`
  before it ever touches a filesystem path, since it's free text from any
  visitor).
- A **new** name creates a fresh profile and a deterministic session
  (`session_id = f"{APP_NAME}_{user_id}"`); the app auto-sends a "hi" so
  the agent greets you and starts onboarding instead of an empty chat box.
- A name **matching an existing profile** resumes that exact session —
  same `session_id`, full prior conversation and saved data restored.
- Every tool/callback reads the user_id from ADK's own context
  (`callback_context.user_id` / `tool_context.user_id` / `ctx.user_id`),
  never from a shared global — that's what actually enforces isolation,
  not just the sidebar UI. Verified locally with two distinct names in
  the same process: fully isolated data, no bleed between them, and
  reconnecting under the first name resumed its session with full history.

This mirrors the identity model used by a sibling ADK/Streamlit project
(a college admissions coach).

## Setup

1. **Get a GCP service account with Vertex AI access** (`roles/aiplatform.user`).
2. **Place secrets locally** (never committed — see `.gitignore`):
   - `secrets/gcp_service_account.json` — the service account key JSON.
   - `.streamlit/secrets.toml` — same content, Streamlit's TOML format:

     ```toml
     GOOGLE_CLOUD_PROJECT = "your-project-id"

     [gcp_service_account]
     type = "service_account"
     project_id = "your-project-id"
     private_key_id = "..."
     private_key = "..."
     client_email = "..."
     client_id = "..."
     auth_uri = "https://accounts.google.com/o/oauth2/auth"
     token_uri = "https://oauth2.googleapis.com/token"
     auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
     client_x509_cert_url = "..."
     universe_domain = "googleapis.com"
     ```

   - `financial_advisor/.env` — for `adk web`/`adk run` (CLI tools don't
     read `.streamlit/secrets.toml`):

     ```bash
     GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/secrets/gcp_service_account.json
     GOOGLE_CLOUD_PROJECT=your-project-id
     ADK_MODEL=gemini-3.5-flash
     ADK_COORDINATOR_MODEL=gemini-3.5-flash
     ```
3. **Create a virtualenv and install dependencies:**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub — `secrets/` and `.streamlit/secrets.toml`
   stay out of git via `.gitignore`, so the key never touches the repo.
2. On [share.streamlit.io](https://share.streamlit.io), create a new app
   pointing at this repo, `streamlit_app.py` as the entry point.
3. In the app's **Settings → Secrets**, paste the same TOML shown above.
   `streamlit_app.py` reads it via `st.secrets` and bridges it into the
   environment variables ADK's Gemini client expects.

## Running locally

**Option A — ADK's own dev UI** (best for inspecting agent transfers/tool calls):

```bash
adk web
```

**Option B — Streamlit app** (same UI deployed to Streamlit Community Cloud):

```bash
streamlit run streamlit_app.py
```

## Notes

- **Budgeting/investing guidance** (`dashboard_store.compute_guidance`) is
  two standard, widely-cited rules of thumb, not personalized advice: a
  50/30/20 needs/wants/savings split, and prioritizing a 6-month emergency
  fund before the full "savings" share goes to investing. Never
  recommends saving more than `monthly_income - monthly_expenses` actually
  leaves over.
- **Financial-guru/book citations** (`wisdom_store.py`) are hand-authored,
  paraphrased, attributed summaries (Dave Ramsey's Baby Steps, Bogle/
  Buffett on index investing, the Bogleheads three-fund portfolio, the 4%
  rule, etc.) — not the model's own recall.
- **Web search** (`search_financial_advice`) uses `ddgs` (DuckDuckGo, no
  API key) restricted to a trusted-domain allowlist (Investopedia,
  NerdWallet, Bogleheads, IRS.gov, SEC.gov, etc.), falling back to
  unfiltered results only if nothing from the allowlist comes back.
  Returns short `{title, url, snippet}` entries, never full page content.
- **Gemini 3.x is only served from Vertex AI's `global` location**, not
  regional endpoints — `models.py`'s `GlobalGemini` builds its
  `google.genai.Client` with `location="global"` explicitly; a regional
  location silently fails to serve `gemini-3.5-flash`.
- **Multi-user, not single-local-user**, unlike the sibling local-Ollama
  project — see "Multi-user identity" above.
- **Streamlit's rerun model needs a persistent event loop, not
  `asyncio.run()` per call.** Streamlit re-executes the whole script every
  interaction; a bare `asyncio.run(...)` tears down and recreates the
  event loop each time, but the cached `Runner`/`DatabaseSessionService`
  hold `aiosqlite` connections bound to whichever loop created them —
  causing intermittent "attached to a different event loop" / closed-loop
  errors. Fixed with one event loop, created once (`@st.cache_resource`)
  and run forever in a background daemon thread; all async work goes
  through `run_sync()` (`asyncio.run_coroutine_threadsafe`) instead of
  `asyncio.run()`. Verified with a live headless run (see "Verification").
- **Gemini 3.x requires a `thought_signature` on every function-call part**,
  including ones the app fabricates itself. `web_search_tools.ground_if_ungrounded`
  synthesizes a `function_call` Part to force a real search when the model
  skips one — that part never had a real signature, and Gemini rejected
  the next turn once it was replayed back as conversation history (`400
  INVALID_ARGUMENT: Function call is missing a thought_signature`, seen
  live on the deployed app). Fixed by setting
  `thought_signature=SKIP_THOUGHT_SIGNATURE_VALIDATOR` (a sentinel ADK
  ships in `google.adk.utils.content_utils` for exactly this case — a
  model/tool-call part the app synthesizes rather than one Gemini
  actually produced) on that Part. Verified across a 3-turn conversation
  that reproduces the original failure shape (forced search, then two
  follow-ups replaying it as history) with no errors.
- **The GCP service account key is the one real secret in this repo.**
  `secrets/gcp_service_account.json` and `.streamlit/secrets.toml` are
  both gitignored — the key only ever lives on disk locally or in
  Streamlit Cloud's own Secrets store, never in git.
- **Personal data stays local/server-side and gitignored.**
  `financial_advisor/data/` (`profiles/<user_id>.json`,
  `dashboards/<user_id>.json`, `sessions.db`) and `financial_advisor/.env`
  are excluded via `.gitignore`. On Streamlit Cloud this data lives only
  in that app's container filesystem — never in git, though it also isn't
  backed up across a redeploy the way a real database would be.

## Verification

- **Secrets never committed**: audited full local git history (not just
  current state) for `secrets/`, `.streamlit/secrets.toml`, and
  `financial_advisor/.env` — zero matches, including in unreachable/
  dangling git objects. Cross-checked against GitHub's own tree API
  (not just local state). Confirmed clean both before and after the
  multi-user changes below.
- **Multi-user isolation**: ran two distinct identities ("jordan", "sam")
  through the live agent in the same process. Each got a fully separate
  profile/dashboard file with zero data bleed; reconnecting under a name
  already used resumed the exact same session, full prior history intact.
- **Event loop fix**: confirmed the app boots and serves cleanly under a
  real `streamlit run` (not just a bare Python import, which doesn't
  exercise Streamlit's session/rerun machinery the same way).
- **Gemini/Vertex AI connectivity**: live end-to-end run confirmed auth,
  tool-calling, and real synthesized responses all work.

## Known limitations

This is a demo, not production-grade agent routing.

- **Specialist routing is still an LLM decision**, not deterministic:
  `specialist_router` correctly calls the right specialist most of the
  time, but can occasionally answer directly from its own knowledge
  instead of calling a specialist — including, in earlier local-model
  testing, fabricating plausible-but-wrong market index numbers instead of
  calling `market_research`. Mitigated by an explicit instruction against
  answering market questions from memory, plus (on the specialists
  themselves) an `after_model_callback` that detects an ungrounded
  response and forces a real tool call. Not closed at the router level —
  if you see it answer directly when you expected a specialist, that's
  this known gap, not a bug.
- **Citation behavior**: agents don't name a source unless asked, and even
  then only one literally present in a tool result — added after earlier
  testing showed the model blending one real citation with several
  invented ones when asked to name sources. A deterministic
  `strip_unrequested_citations` pass is a safety net on top of the
  instruction, not a complete guarantee.
- **Deterministic capture is best-effort, not full NLU.** Profile/
  dashboard field capture (`capture_profile_fields`,
  `ask_missing_dashboard_fields`) handles clean batch replies and
  reasonably clear prose via a positional pass + context-anchored
  fallback, but unusual phrasings can still slip through. One known edge
  case: answering every onboarding question in a single rapid-fire
  message on literally the first turn can mis-segment and save part of a
  sentence as the `name` field, since segment count won't match the
  missing-field count.
- **LLM-judgment findings (routing, grounding, citations) were
  characterized against a local Gemma fine-tune on Ollama**, not
  independently re-verified against Gemini beyond the basic sanity check
  in "Verification" above. Gemini is a substantially stronger model and
  may not exhibit the same failure rates, or could have different ones —
  treat the above as *what kinds* of failures to watch for, not as
  measured Gemini behavior. The deterministic logic (onboarding/dashboard
  capture, completeness gating, multi-user isolation) is plain Python, so
  it isn't model-dependent and carries over exactly.
- **`adk web`'s dropdown lists any directory containing a file literally
  named `agent.py`.** Sub-agent modules are named `<name>_agent.py`
  instead to avoid cluttering it with non-functional entries — keep that
  convention for any new sub-agent.
