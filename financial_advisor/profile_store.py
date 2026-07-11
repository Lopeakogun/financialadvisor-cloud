"""Per-user JSON persistence for financial profiles.

Multi-user demo storage: one JSON file per user under
financial_advisor/data/profiles/, keyed by the sidebar-provided user_id
(see streamlit_app.py). The whole data/ directory is gitignored since it
holds personal financial information.
"""

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
PROFILES_DIR = DATA_DIR / "profiles"

# label: shown to the agent as guidance on what the field means.
# required: whether the coordinator gates other specialists on this field.
# Dict order = the order fields should be asked in; "name" comes first
# since it's also used (via streamlit_app.py's sidebar) as the identity
# key for saved conversation history.
PROFILE_SCHEMA = {
    "name": {"label": "First name (used to greet you and save your conversation history)", "required": True},
    "age": {"label": "Age", "required": True},
    "household_status": {"label": "Household status (single, married, dependents, etc.)", "required": True},
    "income": {"label": "Annual income and how stable it is", "required": True},
    "location": {"label": "State/country of residence", "required": True},
    "risk_tolerance": {"label": "Risk tolerance", "required": True},
    "investment_experience": {"label": "Investment experience", "required": True},
    "time_horizon": {"label": "Investing time horizon", "required": True},
    "expenses": {"label": "Typical monthly expenses", "required": False},
    "assets": {"label": "Current assets (cash, investments, property, etc.)", "required": False},
    "liabilities": {"label": "Current debts/liabilities", "required": False},
    "tax_bracket": {"label": "Approximate tax bracket", "required": False},
    "employment_status": {"label": "Employment status", "required": False},
    "retirement_goals": {"label": "Retirement goals", "required": False},
    "major_life_goals": {"label": "Major life goals (house, education, travel, etc.)", "required": False},
    "liquidity_needs": {"label": "Liquidity needs", "required": False},
}

REQUIRED_FIELDS = [key for key, spec in PROFILE_SCHEMA.items() if spec["required"]]

_UNSAFE_CHARS_RE = re.compile(r"[^a-z0-9_-]")


def _safe_user_id(user_id: str) -> str:
    """Sanitize user_id before it ever touches a filesystem path.

    user_id ultimately comes from free-text input (the sidebar name field,
    open to any visitor on a public deployment), so this guards against
    path traversal / unsafe filenames rather than trusting the caller to
    have already sanitized it.
    """
    cleaned = _UNSAFE_CHARS_RE.sub("", user_id.strip().lower().replace(" ", "_"))
    if not cleaned:
        raise ValueError("user_id must contain at least one alphanumeric character")
    return cleaned[:100]


def _profile_path(user_id: str) -> Path:
    return PROFILES_DIR / f"{_safe_user_id(user_id)}.json"


def load_profile(user_id: str) -> dict:
    path = _profile_path(user_id)
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def profile_exists(user_id: str) -> bool:
    return _profile_path(user_id).exists()


def set_field(user_id: str, field: str, value: str) -> dict:
    """Save one field and return the full updated profile, or {'error': ...}."""
    if field not in PROFILE_SCHEMA:
        return {"error": f"Unknown field '{field}'. Valid fields: {', '.join(PROFILE_SCHEMA)}"}
    profile = load_profile(user_id)
    profile[field] = value
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    with open(_profile_path(user_id), "w") as f:
        json.dump(profile, f, indent=2)
    return profile


def missing_required(profile: dict) -> list:
    return [field for field in REQUIRED_FIELDS if not profile.get(field)]


def is_complete(profile: dict) -> bool:
    return not missing_required(profile)
