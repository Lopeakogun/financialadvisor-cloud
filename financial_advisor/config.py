import os

from .models import GlobalGemini

# Cloud variant: uses Google's hosted Gemini API (via Vertex AI) instead of a
# local Ollama server, so the app has no dependency on a machine that must
# stay on and reachable — it can run on Streamlit Community Cloud. Auth is
# via a GCP service account (see streamlit_app.py's credential bridging and
# secrets/README.md), not a local model file.
#
# Unlike the local Gemma fine-tunes this project's sibling (non-cloud) repo
# ships, Gemini's tool-calling is reliable enough that the coordinator
# doesn't need a bigger model than the sub-agents.
SUB_AGENT_MODEL = os.getenv("ADK_MODEL", "gemini-3.5-flash")
COORDINATOR_MODEL = os.getenv("ADK_COORDINATOR_MODEL", "gemini-3.5-flash")


def get_model() -> GlobalGemini:
    """Build the Gemini model used by sub-agents."""
    return GlobalGemini(model=SUB_AGENT_MODEL)


def get_coordinator_model() -> GlobalGemini:
    """Build the Gemini model used by the root coordinator."""
    return GlobalGemini(model=COORDINATOR_MODEL)
