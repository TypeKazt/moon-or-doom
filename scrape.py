#!/usr/bin/env python3
"""Scraper: fetch Reddit posts, analyze with Claude, store in SQLite."""

import json
import sys
from datetime import datetime, timezone

import anthropic
import praw

import config
import db

SYSTEM_PROMPT = """\
You are a sentiment analyst specializing in theta gang / covered call options strategy.
You analyze Reddit posts about a stock to help covered call sellers make decisions.

Key framing for your analysis:
- BULLISH for covered call sellers means: stable or slow upward movement, high IV (good premiums), \
no imminent catalysts that could cause sharp moves
- BEARISH for covered call sellers means: risk of sharp upward move (assignment risk) or sharp \
downward move (underlying losses), upcoming binary events
- Flat/boring price action is GOOD for theta sellers
- High implied volatility is GOOD (more premium) as long as it's not from an imminent catalyst

For covered_call_recommendation:
- "sell": Safe to sell covered calls, stable conditions, good premium environment
- "cautious": Can sell but use conservative strikes (further OTM, shorter DTE)
- "hold": Don't sell covered calls right now, major catalyst imminent or extreme uncertainty\
"""

USER_PROMPT_TEMPLATE = """\
Analyze these Reddit posts from r/{subreddit} (fetched {timestamp}).

{post_bundle}

Respond with ONLY valid JSON (no markdown fencing) in this exact structure:
{{
  "week_sentiment": "bullish" | "bearish" | "neutral",
  "week_score": <-100 to +100>,
  "week_summary": "<1-2 sentence summary of near-term sentiment>",
  "month_sentiment": "bullish" | "bearish" | "neutral",
  "month_score": <-100 to +100>,
  "month_summary": "<1-2 sentence summary of medium-term outlook>",
  "quarter_sentiment": "bullish" | "bearish" | "neutral",
  "quarter_score": <-100 to +100>,
  "quarter_summary": "<1-2 sentence summary of longer-term thesis>",
  "covered_call_recommendation": "sell" | "cautious" | "hold",
  "covered_call_reasoning": "<2-3 sentences explaining the recommendation>",
  "important_dates": [
    {{
      "event_date": "YYYY-MM-DD" or null,
      "estimated_quarter": "Q1 2025" or null,
      "event_type": "<earnings|launch|fcc|partnership|conference|other>",
      "description": "<what the event is>"
    }}
  ]
}}\
"""


def fetch_posts(subreddit_name):
    """Fetch hot and new posts from a subreddit via PRAW."""
    reddit = praw.Reddit(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT,
    )
    subreddit = reddit.subreddit(subreddit_name)

    seen_ids = set()
    posts = []

    for listing in [subreddit.hot(limit=config.POST_LIMIT), subreddit.new(limit=config.POST_LIMIT)]:
        for submission in listing:
            if submission.fullname in seen_ids:
                continue
            seen_ids.add(submission.fullname)

            # Gather top comments
            submission.comment_sort = "best"
            submission.comments.replace_more(limit=0)
            comments = []
            for comment in submission.comments[: config.COMMENT_LIMIT]:
                body = (comment.body or "")[:config.MAX_COMMENT_CHARS]
                if body.strip():
                    comments.append({"author": str(comment.author), "body": body, "score": comment.score})

            posts.append({
                "id": submission.fullname,
                "subreddit": subreddit_name,
                "title": submission.title,
                "selftext": (submission.selftext or "")[:config.MAX_POST_CHARS],
                "author": str(submission.author),
                "score": submission.score,
                "num_comments": submission.num_comments,
                "created_utc": submission.created_utc,
                "url": submission.url,
                "comments": comments,
            })

    return posts


def build_text_bundle(posts):
    """Build a text bundle from posts for the Claude prompt."""
    lines = []
    total = 0
    for p in posts:
        block = f"### [{p['score']} pts] {p['title']}\n"
        if p["selftext"]:
            block += p["selftext"] + "\n"
        for c in p.get("comments", []):
            block += f"  > [{c['score']} pts] {c['author']}: {c['body']}\n"
        block += "\n"

        if total + len(block) > config.MAX_BUNDLE_CHARS:
            break
        lines.append(block)
        total += len(block)
    return "".join(lines)


def analyze_with_claude(subreddit, post_bundle):
    """Send the post bundle to Claude and get structured sentiment analysis."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    user_prompt = USER_PROMPT_TEMPLATE.format(
        subreddit=subreddit,
        timestamp=timestamp,
        post_bundle=post_bundle,
    )

    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = message.content[0].text
    # Strip markdown fencing if Claude adds it despite instructions
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    return json.loads(text), raw


def main():
    subreddit = config.SUBREDDIT
    print(f"Moon or Doom scraper — r/{subreddit}")
    print("=" * 40)

    config.validate_scraper()
    db.init_db()

    # Fetch posts
    print("Fetching posts from Reddit...")
    posts = fetch_posts(subreddit)
    print(f"  Found {len(posts)} posts")

    # Filter out already-seen posts
    existing_ids = db.get_existing_post_ids(subreddit)
    new_posts = [p for p in posts if p["id"] not in existing_ids]
    print(f"  {len(new_posts)} new posts (skipping {len(posts) - len(new_posts)} already seen)")

    if not new_posts:
        print("No new posts to analyze. Exiting.")
        return

    # Store posts
    db.insert_posts(new_posts)

    # Build bundle and analyze
    print("Building text bundle...")
    bundle = build_text_bundle(new_posts)
    print(f"  Bundle size: {len(bundle)} chars")

    print("Calling Claude for sentiment analysis...")
    analysis, raw_response = analyze_with_claude(subreddit, bundle)

    # Store analysis
    post_ids = [p["id"] for p in new_posts]
    analysis_id = db.insert_analysis(subreddit, analysis, post_ids, raw_response)
    print(f"  Analysis saved (id={analysis_id})")

    # Store important dates
    dates = analysis.get("important_dates", [])
    if dates:
        db.upsert_dates(subreddit, dates, analysis_id)
        print(f"  {len(dates)} important date(s) saved")

    # Summary
    print()
    print(f"Recommendation: {analysis.get('covered_call_recommendation', 'N/A').upper()}")
    print(f"  {analysis.get('covered_call_reasoning', '')}")
    print()
    print("Run `python dashboard.py` to see the full dashboard.")


if __name__ == "__main__":
    main()
