import os
import sys
from dotenv import load_dotenv

load_dotenv()

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
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

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")


def validate_scraper():
    """Validate that all required env vars for scraping are set."""
    missing = []
    if not REDDIT_CLIENT_ID:
        missing.append("REDDIT_CLIENT_ID")
    if not REDDIT_CLIENT_SECRET:
        missing.append("REDDIT_CLIENT_SECRET")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)
