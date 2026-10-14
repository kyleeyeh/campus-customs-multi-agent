"""Central configuration for Campus Customs Multi-Agent Operations.

Everything environment- or model-related lives here so there is exactly one
place to look. In particular: this project talks to exactly ONE model.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root = the folder containing this app/ package.
ROOT = Path(__file__).resolve().parent.parent

# Load .env from the project folder first, then fall back to the class root
# (the key lives one level up in this student's setup).
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

# --- Model -----------------------------------------------------------------
# The assignment permits exactly one model. Do not add others, do not fall
# back to another model on error, and do not import a model name from
# anywhere outside this file.
MODEL = "gpt-6-luna"

# This model family rejects `max_tokens` and requires `max_completion_tokens`.
# Passing the wrong one yields a confusing 400 from the Azure backend.
MAX_COMPLETION_TOKENS = 1500

PORTKEY_BASE_URL = "https://api.portkey.ai/v1"


def portkey_api_key() -> str:
    key = os.environ.get("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError(
            "PORTKEY_API_KEY not found. Put it in .env at the project root "
            "(see .env.example)."
        )
    return key


# --- Database --------------------------------------------------------------
# campus_customs.db is the pristine original and is NEVER written to.
# All tools read and write the working copy.
ORIGINAL_DB = ROOT / "data" / "campus_customs.db"
WORKING_DB = ROOT / "data" / "campus_customs_new.db"

# --- Human in the loop -----------------------------------------------------
APPROVER_NAME = "Kyle Yeh"
