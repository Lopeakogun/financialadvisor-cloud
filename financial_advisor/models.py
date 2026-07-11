from functools import cached_property

from google.adk.models import Gemini
from google.genai import Client


class GlobalGemini(Gemini):
    """Gemini via Vertex AI, pinned to the 'global' endpoint.

    The gemini-3 series (including gemini-3.5-flash) is only served from
    Vertex AI's 'global' location, not regional endpoints — confirmed
    working in the sibling college-admissions project, which uses the same
    GCP project/service account as this app.
    """

    @cached_property
    def api_client(self) -> Client:
        return Client(vertexai=True, location="global")
