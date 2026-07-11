import asyncio
import json
import os
import tempfile
import threading

import streamlit as st
from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

load_dotenv("financial_advisor/.env")

# Google Cloud credentials (Streamlit secrets → env vars). Works both locally
# (.streamlit/secrets.toml, gitignored — never commit it) and on Streamlit
# Community Cloud (paste the same TOML into the app's Secrets settings).
# financial_advisor/.env's GOOGLE_APPLICATION_CREDENTIALS (loaded above)
# covers non-Streamlit use (`adk web` / `adk run`), which st.secrets doesn't.
if "gcp_service_account" in st.secrets:
    _key = dict(st.secrets["gcp_service_account"])
    _tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(_key, _tmp)
    _tmp.flush()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _tmp.name

if "GOOGLE_CLOUD_PROJECT" in st.secrets:
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", st.secrets["GOOGLE_CLOUD_PROJECT"])

from financial_advisor.agent import root_agent  # noqa: E402
from financial_advisor.dashboard_store import DASHBOARD_SCHEMA  # noqa: E402
from financial_advisor.dashboard_store import compute_guidance as compute_dashboard_guidance  # noqa: E402
from financial_advisor.dashboard_store import compute_spending_breakdown  # noqa: E402
from financial_advisor.dashboard_store import compute_summary as compute_dashboard_summary  # noqa: E402
from financial_advisor.dashboard_store import load_dashboard  # noqa: E402
from financial_advisor.dashboard_store import missing_required as dashboard_missing_required  # noqa: E402
from financial_advisor.profile_store import DATA_DIR, load_profile  # noqa: E402
from financial_advisor.profile_store import missing_required as profile_missing_required  # noqa: E402
from financial_advisor.profile_store import set_field as set_profile_field  # noqa: E402

APP_NAME = "financial_advisor"
DB_PATH = DATA_DIR / "sessions.db"

st.set_page_config(page_title="Financial Advisor", page_icon="\U0001f4b0")
st.title("\U0001f4b0 Financial Advisor")
st.caption(
    "Multi-agent demo (onboarding, financial dashboard, risk profiler, "
    "portfolio analyst, market research) running on Google's Gemini API. "
    "Educational use only — not licensed financial advice."
)


# ── persistent event loop ────────────────────────────────────────────────
# Streamlit re-executes the entire script on every interaction. A bare
# `asyncio.run(...)` per call creates and tears down a NEW event loop each
# time, but the cached Runner/DatabaseSessionService (below) hold onto
# resources (aiosqlite connections) bound to whichever loop created them —
# so later calls intermittently fail with "attached to a different event
# loop" / the loop being closed. Caching one persistent loop, running
# forever in a background thread, and submitting all async work to it
# fixes that: everything always runs on the same loop the cached objects
# were created on.
@st.cache_resource
def _get_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop


def run_sync(coro):
    """Submit a coroutine to the persistent cached event loop and block until done."""
    return asyncio.run_coroutine_threadsafe(coro, _get_loop()).result()


@st.cache_resource
def get_session_service() -> DatabaseSessionService:
    os.makedirs(DATA_DIR, exist_ok=True)
    return DatabaseSessionService(db_url=f"sqlite+aiosqlite:///{DB_PATH}")


session_service = get_session_service()
runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)


async def _get_or_create_session(user_id: str):
    session_id = f"{APP_NAME}_{user_id}"
    session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    if session is None:
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
    return session


async def run_agent(user_id: str, session_id: str, text: str) -> str:
    content = types.Content(role="user", parts=[types.Part(text=text)])
    final_text = "(no response)"
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text or final_text
    return final_text


def _completion_widget(label: str, missing: list) -> None:
    """Only shows once a stage is complete — the chat itself carries the
    conversational weight of onboarding, so the sidebar doesn't spoil it
    by listing every still-unanswered question up front."""
    if missing:
        return
    st.subheader(label)
    st.caption("Complete.")


# ── sidebar: identity + per-user dashboard summary ──────────────────────
# Every visitor to a deployed instance shares the same server process, so
# identity can't come from a single global saved profile (that would show
# everyone whoever's name was saved last). Instead — same pattern as the
# sibling college-admissions app — a name typed here becomes the user_id:
# a new name gets a brand new profile, a name matching an existing one
# resumes it, entirely independent of any other visitor's session.
with st.sidebar:
    st.markdown("## \U0001f4b0 Financial Advisor")
    st.caption("Your personal AI investing & budgeting coach")
    st.divider()

    raw_name = st.text_input(
        "Your name",
        placeholder="Enter a name to save your progress",
        help="Each name gets its own persistent profile — a returning name resumes where you left off.",
    )
    user_id = raw_name.strip().lower().replace(" ", "_") if raw_name.strip() else None

    if user_id:
        if st.session_state.get("last_user_id") != user_id:
            # New name in this browser (first-ever visitor, or someone
            # typed a different name) — (re)bind identity, load whatever
            # history already exists under that name, and pre-fill the
            # profile's name field the first time this user_id is seen.
            session = run_sync(_get_or_create_session(user_id))
            st.session_state["last_user_id"] = user_id
            st.session_state["session_id"] = session.id
            st.session_state["messages"] = []
            for event in session.events:
                if event.content and event.content.parts and event.author:
                    text = "".join(part.text or "" for part in event.content.parts)
                    if text:
                        role = "user" if event.author == "user" else "assistant"
                        st.session_state["messages"].append({"role": role, "content": text})

            profile = load_profile(user_id)
            if not profile.get("name"):
                set_profile_field(user_id, "name", raw_name.strip()[:50])
            # Brand new visitor (no prior turns) — queue an agent-initiated
            # greeting instead of dropping them into a blank chat box.
            st.session_state["needs_greeting"] = not st.session_state["messages"]

        profile = load_profile(user_id)
        profile_missing = profile_missing_required(profile)
        _completion_widget("Your profile", profile_missing)

        if not profile_missing:
            dashboard = load_dashboard(user_id)
            dash_missing = dashboard_missing_required(dashboard)
            if not dash_missing:
                st.divider()
            _completion_widget("Financial dashboard", dash_missing)

            if not dash_missing:
                summary = compute_dashboard_summary(dashboard)
                guidance = compute_dashboard_guidance(dashboard)
                col1, col2 = st.columns(2)
                if "net_worth" in summary:
                    col1.metric("Net worth", f"${summary['net_worth']:,.0f}")
                if "monthly_cash_flow" in summary:
                    col2.metric("Monthly cash flow", f"${summary['monthly_cash_flow']:,.0f}")
                if "savings_rate_pct" in summary:
                    col1.metric("Savings rate", f"{summary['savings_rate_pct']:.1f}%")
                if "emergency_fund_months" in summary:
                    col2.metric("Emergency fund", f"{summary['emergency_fund_months']:.1f} mo")
                if "recommended_investing_amount" in guidance:
                    col1.metric(
                        "Suggested investing",
                        f"${guidance['recommended_investing_amount']:,.0f}/mo",
                        help=f"~{guidance['recommended_investing_pct']:.1f}% of monthly income",
                    )
                if "emergency_fund_monthly_contribution" in guidance:
                    col2.metric(
                        "Suggested to emergency fund",
                        f"${guidance['emergency_fund_monthly_contribution']:,.0f}/mo",
                        help=f"~{guidance['emergency_fund_pct_of_income']:.1f}% of monthly income",
                    )

                breakdown = compute_spending_breakdown(dashboard)
                if breakdown:
                    with st.expander("Spending breakdown", expanded=False):
                        for field, amount in breakdown["categories"].items():
                            label = DASHBOARD_SCHEMA[field]["label"].split(" (")[0]
                            pct = breakdown["categories_pct_of_income"][field]
                            st.caption(f"{label}: ${amount:,.0f}/mo ({pct:.1f}% of income)")
                        if breakdown.get("housing_over_guideline"):
                            st.caption(f"⚠️ Housing is {breakdown['housing_pct_of_income']:.1f}% of income (guideline: ≤30%)")
                        if breakdown.get("debt_to_income_over_guideline"):
                            st.caption(f"⚠️ Debt-to-income is {breakdown['debt_to_income_pct']:.1f}% (guideline: ≤36%)")

        st.divider()
        if st.button("\U0001f5d1 Clear chat history", use_container_width=True):
            st.session_state["messages"] = []
            st.session_state["needs_greeting"] = True
            st.rerun()


# ── main area ─────────────────────────────────────────────────────────────
if not user_id:
    st.markdown("## Welcome to Financial Advisor \U0001f4b0")
    st.markdown(
        "Your personal AI coach for budgeting, investing basics, risk "
        "tolerance, and portfolio questions.\n\n"
        "**Enter your name in the sidebar to get started.**  \n"
        "Your profile is saved so you can pick up where you left off."
    )
    st.stop()

session_id = st.session_state["session_id"]

for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Auto-greet a brand new visitor (agent speaks first) instead of leaving
# them staring at an empty chat box.
if st.session_state.get("needs_greeting"):
    st.session_state["needs_greeting"] = False
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                opening = run_sync(run_agent(user_id, session_id, "hi"))
            except Exception as e:
                opening = (
                    f"Error talking to the agent: {e}\n\n"
                    "Make sure Google Cloud credentials are configured — "
                    "either .streamlit/secrets.toml locally, or the app's "
                    "Secrets settings if this is deployed on Streamlit "
                    "Community Cloud. See README.md for setup."
                )
        st.markdown(opening)
    st.session_state["messages"].append({"role": "assistant", "content": opening})
    st.rerun()

if prompt := st.chat_input("Ask about investing, risk, or a stock..."):
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response_text = run_sync(run_agent(user_id, session_id, prompt))
            except Exception as e:
                response_text = (
                    f"Error talking to the agent: {e}\n\n"
                    "Make sure Google Cloud credentials are configured — "
                    "either .streamlit/secrets.toml locally, or the app's "
                    "Secrets settings if this is deployed on Streamlit "
                    "Community Cloud. See README.md for setup."
                )
        st.markdown(response_text)
    st.session_state["messages"].append({"role": "assistant", "content": response_text})
