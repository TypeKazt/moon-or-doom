#!/usr/bin/env python3
"""Scraper: fetch Reddit posts, analyze with Claude, store in SQLite."""

import json
import sys
import time
from datetime import datetime, timezone

import anthropic
import requests

import config
import db

REDDIT_HEADERS = {"User-Agent": config.REDDIT_USER_AGENT}

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
  ],
  "notable_links": [
    {{
      "url": "<the post or comment link from the data above>",
      "title": "<short description of what the post/comment is about>",
      "author": "<username>",
      "score": <score>,
      "type": "post" or "comment",
      "reason": "<why this is notable — e.g. high engagement, key insight, important news>"
    }}
  ]
}}

For notable_links: include posts/comments that are especially significant — either from \
profiled/weighted users, or from the general public if they have high engagement (high score \
or many replies). Pick up to 10 most notable. Use the exact Link/Comment link URLs provided \
in the data above.\
"""


def _reddit_get(url, params=None):
    """Make a GET request to a Reddit .json endpoint with rate-limit handling."""
    resp = requests.get(url, headers=REDDIT_HEADERS, params=params, timeout=15)
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 5))
        print(f"  Rate limited, waiting {retry_after}s...")
        time.sleep(retry_after)
        resp = requests.get(url, headers=REDDIT_HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _fetch_listing(subreddit_name, sort, limit):
    """Fetch a listing (hot/new) page by page using .json endpoints."""
    base_url = f"https://www.reddit.com/r/{subreddit_name}/{sort}.json"
    collected = []
    after = None

    while len(collected) < limit:
        batch = min(100, limit - len(collected))
        params = {"limit": batch, "raw_json": 1}
        if after:
            params["after"] = after

        data = _reddit_get(base_url, params)
        children = data.get("data", {}).get("children", [])
        if not children:
            break

        collected.extend(children)
        after = data.get("data", {}).get("after")
        if not after:
            break
        time.sleep(1)  # be polite

    return collected


def _fetch_comments(subreddit_name, post_id):
    """Fetch top-level comments for a post via .json endpoint."""
    url = f"https://www.reddit.com/r/{subreddit_name}/comments/{post_id}.json"
    data = _reddit_get(url, params={"limit": config.COMMENT_LIMIT, "sort": "best", "raw_json": 1})
    comments = []
    if len(data) >= 2:
        for child in data[1].get("data", {}).get("children", []):
            if child.get("kind") != "t1":
                continue
            c = child["data"]
            body = (c.get("body") or "")[:config.MAX_COMMENT_CHARS]
            if body.strip():
                comments.append({
                    "author": c.get("author", "[deleted]"),
                    "body": body,
                    "score": c.get("score", 0),
                    "permalink": "https://www.reddit.com" + c.get("permalink", ""),
                })
            if len(comments) >= config.COMMENT_LIMIT:
                break
    return comments


def fetch_posts(subreddit_name):
    """Fetch hot and new posts from a subreddit via Reddit .json endpoints."""
    seen_ids = set()
    posts = []

    for sort in ["hot", "new"]:
        children = _fetch_listing(subreddit_name, sort, config.POST_LIMIT)
        for child in children:
            if child.get("kind") != "t3":
                continue
            s = child["data"]
            fullname = child["kind"] + "_" + s["id"]
            if fullname in seen_ids:
                continue

            title = s.get("title", "")
            # Skip daily discussion threads
            if "daily discussion" in title.lower():
                continue

            seen_ids.add(fullname)

            # Fetch comments for this post
            print(f"  Fetching comments for: {title[:60]}...")
            comments = _fetch_comments(subreddit_name, s["id"])
            time.sleep(1)  # rate-limit politeness

            permalink = "https://www.reddit.com" + s.get("permalink", "")
            posts.append({
                "id": fullname,
                "subreddit": subreddit_name,
                "title": title,
                "selftext": (s.get("selftext") or "")[:config.MAX_POST_CHARS],
                "author": s.get("author", "[deleted]"),
                "score": s.get("score", 0),
                "num_comments": s.get("num_comments", 0),
                "created_utc": s.get("created_utc", 0),
                "url": s.get("url", ""),
                "permalink": permalink,
                "comments": comments,
            })

    return posts


def _format_post_block(p, weight_label=None):
    """Format a single post (with comments) into a text block."""
    tag = f" (weight: {weight_label})" if weight_label else ""
    block = f"### [{p['score']} pts] {p['title']}{tag}\n"
    block += f"Link: {p.get('permalink', '')}\n"
    if p["selftext"]:
        block += p["selftext"] + "\n"
    for c in p.get("comments", []):
        block += f"  > [{c['score']} pts] {c['author']}: {c['body']}\n"
        block += f"    Comment link: {c.get('permalink', '')}\n"
    block += "\n"
    return block


def _collect_blocks(posts, budget, weight_label=None):
    """Collect formatted blocks from posts up to a character budget."""
    blocks = []
    total = 0
    for p in posts:
        block = _format_post_block(p, weight_label)
        if total + len(block) > budget:
            break
        blocks.append(block)
        total += len(block)
    return blocks


def build_text_bundle(posts):
    """Build a weighted text bundle from posts for the Claude prompt.

    Posts/comments from profiled authors get dedicated budget proportional
    to their alpha weight. The general public shares the remainder.
    """
    weights = config.PROFILE_WEIGHTS
    if not weights:
        # No weights configured — flat bundle, all equal
        return "".join(_collect_blocks(posts, config.MAX_BUNDLE_CHARS))

    profiled_names = {name.lower() for name in weights}
    general_weight = 1.0 - sum(weights.values())

    # Partition posts into buckets: one per profiled author + general
    buckets = {name.lower(): [] for name in weights}
    buckets["_general"] = []

    for p in posts:
        author = (p.get("author") or "").lower()
        if author in profiled_names:
            buckets[author].append(p)
        else:
            buckets["_general"].append(p)

    # Build header describing the weighting scheme
    header_lines = ["## Source weighting\n"]
    for name, alpha in sorted(weights.items(), key=lambda x: -x[1]):
        header_lines.append(f"- u/{name}: {alpha:.2f}")
    header_lines.append(f"- General public: {general_weight:.2f}")
    header_lines.append("")
    header_lines.append(
        "Posts are grouped by weight tier. Higher-weight sources should "
        "influence your analysis proportionally more.\n\n"
    )
    header = "\n".join(header_lines)

    remaining = config.MAX_BUNDLE_CHARS - len(header)
    sections = []

    # Profiled author sections — each gets their alpha share of the budget
    for name, alpha in sorted(weights.items(), key=lambda x: -x[1]):
        budget = int(remaining * alpha)
        author_posts = buckets[name.lower()]
        if not author_posts:
            continue
        label = f"u/{name} — {alpha:.2f}"
        blocks = _collect_blocks(author_posts, budget, weight_label=f"{alpha:.2f}")
        if blocks:
            sections.append(f"--- Profiled source: {label} ---\n")
            sections.extend(blocks)

    # General public section
    general_budget = int(remaining * general_weight)
    general_posts = buckets["_general"]
    if general_posts:
        sections.append(f"--- General public (weight: {general_weight:.2f}) ---\n")
        sections.extend(_collect_blocks(general_posts, general_budget))

    return header + "".join(sections)


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

    # Store notable links
    notable = analysis.get("notable_links", [])
    if notable:
        db.insert_notable_links(subreddit, notable, analysis_id)
        print(f"  {len(notable)} notable link(s) saved")

    # Summary
    print()
    print(f"Recommendation: {analysis.get('covered_call_recommendation', 'N/A').upper()}")
    print(f"  {analysis.get('covered_call_reasoning', '')}")
    print()
    print("Run `python dashboard.py` to see the full dashboard.")


if __name__ == "__main__":
    main()
