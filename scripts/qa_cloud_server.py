"""Synthetic-only browser QA server. Never use this entry point for a company workspace."""

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
if (
    os.environ.get("ALLOW_SYNTHETIC_CLOUD_HARNESS") != "SYNTHETIC_ONLY_NO_NETWORK"
    or os.environ.get("GROQ_API_KEY") != "gsk_SYNTHETIC_BROWSER_TEST_ONLY_NOT_REAL"
    or "browser-qa-" not in os.environ.get("DATABASE_URL", "")
    or os.environ.get("RESIMPLI_MODE") != "fixture"
):
    raise RuntimeError("This synthetic harness requires an explicitly isolated fixture test workspace and a dummy key")

from app.main import app  # noqa: E402
from app.services import cloud_ai  # noqa: E402
from app import routes_intelligence  # noqa: E402
from app.services.ai import FACT_KEYS  # noqa: E402
from app.services.groq_client import CloudAnalysis, CloudDraft, SUPPORTED_MODELS  # noqa: E402


class SyntheticGroq:
    """No HTTP transport exists here. Test results are not real Groq verification."""

    def __init__(self, settings):
        pass

    def close(self):
        pass

    def models(self):
        return [{"id": id, "label": label} for id, label in SUPPORTED_MODELS.items()]

    def complete(self, purpose, records, flags):
        first = records[0]
        if purpose == "draft":
            greeting = "Hi {{seller_first_name}}," if flags["has_name_placeholder"] else "Hello,"
            subject = " about {{property_address}}" if flags["has_address_placeholder"] else ""
            body = (
                greeting
                + " I’m following up on your callback request"
                + subject
                + ". What would be a convenient time to talk?"
                if flags["callback_requested"]
                else greeting
                + " Are you still considering selling"
                + subject
                + "? What would you like to clarify before deciding on a next step?"
            )
            return CloudDraft(
                body=body,
                evidence=[first["ref"]],
                quote=first["text"],
                review_note="Synthetic QA response, not actual Groq generation. Human review remains required.",
            ), {"total_tokens": 110}
        facts = {key: {"value": None, "category": "unknown", "evidence": [], "quote": None} for key in FACT_KEYS}
        motivation = next((r for r in records if "seller_motivation" in r.get("label", "")), None)
        if motivation:
            facts["seller_motivation"] = {
                "value": motivation["text"],
                "category": "explicit",
                "evidence": [motivation["ref"]],
                "quote": motivation["text"],
            }
        unique = []
        seen = set()
        for record in records:
            if record["text"] in seen:
                continue
            seen.add(record["text"])
            unique.append({"text": record["text"], "evidence": [record["ref"]], "quote": record["text"]})
            if len(unique) >= 3:
                break
        output = CloudAnalysis.model_validate(
            {
                "summary": {"text": first["text"], "evidence": [first["ref"]], "quote": first["text"]},
                "facts": facts,
                "organized_notes": unique,
                "missing_information": ["Confirm the preferred callback timing against the original record."],
                "conflicts": [],
            }
        )
        return output, {"prompt_tokens": 90, "completion_tokens": 120, "total_tokens": 210}


cloud_ai.GroqClient = SyntheticGroq
routes_intelligence.GroqClient = SyntheticGroq
app.state.synthetic_cloud_fixture = True
