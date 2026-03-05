#!/usr/bin/env python3
"""Dashboard: display sentiment analysis and important dates via Rich CLI."""

from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import config
import db

console = Console()

SENTIMENT_COLORS = {"bullish": "green", "bearish": "red", "neutral": "yellow"}
REC_COLORS = {"sell": "green", "cautious": "yellow", "hold": "red"}


def score_bar(score):
    """Render a score (-100 to +100) as a colored bar."""
    if score is None:
        return Text("N/A", style="dim")
    clamped = max(-100, min(100, score))
    filled = abs(clamped) // 5  # 0-20 blocks
    if clamped > 0:
        bar = " " * (20 - filled) + "+" * filled + " |"
        color = "green"
    elif clamped < 0:
        bar = "| " + "-" * filled + " " * (20 - filled)
        color = "red"
    else:
        bar = " " * 10 + "||" + " " * 10
        color = "yellow"
    return Text(f"{bar} {score:+d}", style=color)


def render_sentiment_table(analysis):
    table = Table(title="Sentiment Analysis", show_header=True, header_style="bold")
    table.add_column("Timeframe", style="bold", width=10)
    table.add_column("Sentiment", width=10)
    table.add_column("Score", width=30)
    table.add_column("Summary", ratio=1)

    for period, label in [("week", "Week"), ("month", "Month"), ("quarter", "Quarter")]:
        sentiment = analysis.get(f"{period}_sentiment", "N/A")
        score = analysis.get(f"{period}_score")
        summary = analysis.get(f"{period}_summary", "")
        color = SENTIMENT_COLORS.get(sentiment, "white")
        table.add_row(
            label,
            Text(sentiment.upper(), style=f"bold {color}"),
            score_bar(score),
            summary,
        )

    return table


def render_recommendation(analysis):
    rec = analysis.get("covered_call_recommendation", "N/A")
    reasoning = analysis.get("covered_call_reasoning", "")
    color = REC_COLORS.get(rec, "white")
    content = Text()
    content.append(rec.upper(), style=f"bold {color}")
    content.append(f"\n\n{reasoning}")
    return Panel(content, title="Covered Call Recommendation", border_style=color)


def render_dates_table(dates):
    if not dates:
        return Panel("No upcoming dates tracked.", title="Upcoming Dates", border_style="dim")

    table = Table(title="Upcoming Dates", show_header=True, header_style="bold")
    table.add_column("Date", width=12)
    table.add_column("Type", width=14)
    table.add_column("Description", ratio=1)
    table.add_column("Days Until", width=10, justify="right")

    today = datetime.now().date()
    for d in dates:
        event_date = d.get("event_date")
        if event_date:
            try:
                dt = datetime.strptime(event_date, "%Y-%m-%d").date()
                days = (dt - today).days
                days_str = str(days)
                date_str = event_date
            except ValueError:
                date_str = event_date
                days_str = "?"
        else:
            date_str = d.get("estimated_quarter") or "TBD"
            days_str = "?"

        table.add_row(date_str, d.get("event_type", ""), d.get("description", ""), days_str)

    return table


def main():
    subreddit = config.SUBREDDIT
    db.init_db()

    analysis = db.get_latest_analysis(subreddit)
    if not analysis:
        console.print(
            Panel(
                "No data yet. Run [bold]python scrape.py[/bold] first to fetch and analyze posts.",
                title="Moon or Doom",
                border_style="yellow",
            )
        )
        return

    # Header
    analyzed_at = analysis.get("analyzed_at", "unknown")
    console.print()
    console.print(
        Panel(
            f"r/{subreddit}  |  Last analyzed: {analyzed_at}",
            title="Moon or Doom",
            border_style="bold blue",
        )
    )
    console.print()

    # Sentiment
    console.print(render_sentiment_table(analysis))
    console.print()

    # Recommendation
    console.print(render_recommendation(analysis))
    console.print()

    # Dates
    dates = db.get_upcoming_dates(subreddit)
    console.print(render_dates_table(dates))
    console.print()


if __name__ == "__main__":
    main()
