import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "moon-or-doom/1.0")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SUBREDDIT = os.getenv("SUBREDDIT", "ASTSpaceMobile")
DB_PATH = os.getenv("DB_PATH", "moon_or_doom.db")

# Scraper tuning
POST_LIMIT = int(os.getenv("POST_LIMIT", "50"))
COMMENT_LIMIT = int(os.getenv("COMMENT_LIMIT", "5"))
MAX_POST_CHARS = 2000
MAX_COMMENT_CHARS = 500
MAX_BUNDLE_CHARS = 50000

# Profile weights: JSON mapping of Reddit usernames to importance weights (0-1).
# The general public collectively receives (1 - sum of weights).
# Example: '{"expert_user": 0.3, "insider_dev": 0.2}' -> general public gets 0.5
_raw_weights = os.getenv("PROFILE_WEIGHTS", "{}")
PROFILE_WEIGHTS = json.loads(_raw_weights)

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")


def validate_scraper():
    """Validate that all required env vars for scraping are set."""
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)
    alpha_sum = sum(PROFILE_WEIGHTS.values())
    if alpha_sum >= 1.0:
        print(f"Error: PROFILE_WEIGHTS sum to {alpha_sum}, must be < 1.0")
        sys.exit(1)
