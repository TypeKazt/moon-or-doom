#!/usr/bin/env python3
"""Web dashboard: simple Flask app mirroring the CLI dashboard."""

from datetime import datetime
from html import escape

import config
import db


def score_bar_html(score):
    if score is None:
        return '<span class="dim">N/A</span>'
    clamped = max(-100, min(100, score))
    pct = (clamped + 100) / 2  # 0-100 range
    if clamped > 0:
        color = "var(--green)"
    elif clamped < 0:
        color = "var(--red)"
    else:
        color = "var(--yellow)"
    return (
        f'<div class="score-bar">'
        f'<div class="score-fill" style="width:{pct}%;background:{color}"></div>'
        f'<span class="score-label">{score:+d}</span>'
        f'</div>'
    )


def build_page():
    db.init_db()
    subreddit = config.SUBREDDIT
    analysis = db.get_latest_analysis(subreddit)

    if not analysis:
        return f"""<!DOCTYPE html>
<html><head><title>Moon or Doom</title>{CSS}</head>
<body><div class="container">
<div class="panel yellow"><h1>Moon or Doom</h1>
<p>No data yet. Run <code>python scrape.py</code> first.</p>
</div></div></body></html>"""

    analyzed_at = escape(analysis.get("analyzed_at", "unknown"))
    dates = db.get_upcoming_dates(subreddit)
    links = db.get_notable_links(subreddit)

    sentiment_colors = {"bullish": "green", "bearish": "red", "neutral": "yellow"}
    rec_colors = {"sell": "green", "cautious": "yellow", "hold": "red"}

    # --- Sentiment rows ---
    sentiment_rows = ""
    for period, label in [("week", "Week"), ("month", "Month"), ("quarter", "Quarter")]:
        sentiment = analysis.get(f"{period}_sentiment", "N/A")
        score = analysis.get(f"{period}_score")
        summary = escape(analysis.get(f"{period}_summary", ""))
        color = sentiment_colors.get(sentiment, "white")
        sentiment_rows += f"""<tr>
            <td><strong>{label}</strong></td>
            <td><span class="badge {color}">{escape(sentiment.upper())}</span></td>
            <td>{score_bar_html(score)}</td>
            <td>{summary}</td>
        </tr>"""

    # --- Recommendation ---
    rec = analysis.get("covered_call_recommendation", "N/A")
    reasoning = escape(analysis.get("covered_call_reasoning", ""))
    rec_color = rec_colors.get(rec, "white")

    # --- Dates rows ---
    today = datetime.now().date()
    dates_rows = ""
    if dates:
        for d in dates:
            event_date = d.get("event_date")
            if event_date:
                try:
                    dt = datetime.strptime(event_date, "%Y-%m-%d").date()
                    days = (dt - today).days
                    days_str = str(days)
                    date_str = escape(event_date)
                except ValueError:
                    date_str = escape(event_date)
                    days_str = "?"
            else:
                date_str = escape(d.get("estimated_quarter") or "TBD")
                days_str = "?"
            dates_rows += f"""<tr>
                <td>{date_str}</td>
                <td>{escape(d.get('event_type', ''))}</td>
                <td>{escape(d.get('description', ''))}</td>
                <td class="right">{days_str}</td>
            </tr>"""
    else:
        dates_rows = '<tr><td colspan="4" class="dim">No upcoming dates tracked.</td></tr>'

    # --- Notable links rows ---
    links_rows = ""
    if links:
        for link in links:
            link_type = link.get("link_type", "post")
            type_class = "post" if link_type == "post" else "comment"
            url = escape(link.get("link_url", ""))
            links_rows += f"""<tr>
                <td><span class="link-type {type_class}">{escape(link_type)}</span></td>
                <td>{escape(link.get('author', ''))}</td>
                <td class="right">{link.get('score', '')}</td>
                <td>{escape(link.get('title', ''))}</td>
                <td>{escape(link.get('reason', ''))}</td>
                <td class="url-cell"><a href="{url}" target="_blank" rel="noopener">{url}</a></td>
            </tr>"""
    else:
        links_rows = '<tr><td colspan="6" class="dim">No notable links tracked.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Moon or Doom — r/{escape(subreddit)}</title>
{CSS}
</head>
<body>
<div class="container">

    <div class="panel blue">
        <h1>Moon or Doom</h1>
        <p>r/{escape(subreddit)}  |  Last analyzed: {analyzed_at}</p>
    </div>

    <div class="section">
        <h2>Sentiment Analysis</h2>
        <table>
            <thead><tr>
                <th>Timeframe</th><th>Sentiment</th><th>Score</th><th>Summary</th>
            </tr></thead>
            <tbody>{sentiment_rows}</tbody>
        </table>
    </div>

    <div class="panel {rec_color}">
        <h2>Covered Call Recommendation</h2>
        <span class="badge {rec_color} big">{escape(rec.upper())}</span>
        <p>{reasoning}</p>
    </div>

    <div class="section">
        <h2>Upcoming Dates</h2>
        <table>
            <thead><tr>
                <th>Date</th><th>Type</th><th>Description</th><th class="right">Days Until</th>
            </tr></thead>
            <tbody>{dates_rows}</tbody>
        </table>
    </div>

    <div class="section">
        <h2>Notable Links</h2>
        <div class="table-scroll">
        <table>
            <thead><tr>
                <th>Type</th><th>Author</th><th class="right">Score</th>
                <th>Title</th><th>Reason</th><th>URL</th>
            </tr></thead>
            <tbody>{links_rows}</tbody>
        </table>
        </div>
    </div>

</div>
</body>
</html>"""


CSS = """<style>
:root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --dim: #8b949e;
    --green: #3fb950;
    --red: #f85149;
    --yellow: #d29922;
    --blue: #58a6ff;
    --cyan: #39c5cf;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 1rem;
}
.container { max-width: 1200px; margin: 0 auto; }
h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.1rem; margin-bottom: 0.75rem; color: var(--text); }
p { margin: 0.5rem 0; }

.panel {
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1rem 1.25rem;
    margin-bottom: 1.25rem;
    background: var(--surface);
}
.panel.blue { border-color: var(--blue); }
.panel.green { border-color: var(--green); }
.panel.yellow { border-color: var(--yellow); }
.panel.red { border-color: var(--red); }

.section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1rem 1.25rem;
    margin-bottom: 1.25rem;
}

table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th, td { padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }
th { color: var(--dim); font-weight: 600; font-size: 0.8rem; text-transform: uppercase; }
.right { text-align: right; }

.badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-weight: 700;
    font-size: 0.8rem;
}
.badge.green { background: rgba(63,185,80,0.15); color: var(--green); }
.badge.red { background: rgba(248,81,73,0.15); color: var(--red); }
.badge.yellow { background: rgba(210,153,34,0.15); color: var(--yellow); }
.badge.big { font-size: 1.1rem; padding: 0.3rem 0.75rem; }

.score-bar {
    position: relative;
    height: 20px;
    background: var(--border);
    border-radius: 3px;
    min-width: 160px;
}
.score-fill {
    position: absolute;
    left: 0; top: 0; bottom: 0;
    border-radius: 3px;
    opacity: 0.6;
}
.score-label {
    position: absolute;
    right: 6px;
    top: 0;
    line-height: 20px;
    font-size: 0.75rem;
    font-weight: 700;
    color: var(--text);
}

.link-type {
    font-weight: 600;
    font-size: 0.8rem;
}
.link-type.post { color: var(--cyan); }
.link-type.comment { color: var(--blue); }

.url-cell { white-space: nowrap; }
.url-cell a { color: var(--dim); text-decoration: none; }
.url-cell a:hover { color: var(--blue); text-decoration: underline; }

.table-scroll { overflow-x: auto; }

.dim { color: var(--dim); }

@media (max-width: 768px) {
    body { padding: 0.5rem; }
    th, td { padding: 0.35rem 0.5rem; font-size: 0.78rem; }
}
</style>"""


if __name__ == "__main__":
    import os

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    html = build_page()
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote dashboard to {out}")
