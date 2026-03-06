import json
import sqlite3
from datetime import datetime

import config


def get_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            subreddit TEXT NOT NULL,
            title TEXT NOT NULL,
            selftext TEXT,
            author TEXT,
            score INTEGER,
            num_comments INTEGER,
            created_utc REAL,
            url TEXT,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sentiment_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subreddit TEXT NOT NULL,
            analyzed_at TEXT NOT NULL DEFAULT (datetime('now')),
            week_sentiment TEXT,
            week_score INTEGER,
            week_summary TEXT,
            month_sentiment TEXT,
            month_score INTEGER,
            month_summary TEXT,
            quarter_sentiment TEXT,
            quarter_score INTEGER,
            quarter_summary TEXT,
            covered_call_recommendation TEXT,
            covered_call_reasoning TEXT,
            post_ids_json TEXT,
            raw_response TEXT
        );

        CREATE TABLE IF NOT EXISTS notable_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subreddit TEXT NOT NULL,
            analysis_id INTEGER NOT NULL,
            link_url TEXT NOT NULL,
            title TEXT,
            author TEXT,
            score INTEGER,
            link_type TEXT NOT NULL,  -- 'post' or 'comment'
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (analysis_id) REFERENCES sentiment_analyses(id)
        );

        CREATE TABLE IF NOT EXISTS important_dates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subreddit TEXT NOT NULL,
            event_date TEXT,
            estimated_quarter TEXT,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            source_analysis_id INTEGER,
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_confirmed_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(subreddit, event_date, event_type)
        );
    """)
    conn.commit()
    conn.close()


def get_existing_post_ids(subreddit):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id FROM posts WHERE subreddit = ?", (subreddit,)
    ).fetchall()
    conn.close()
    return {row["id"] for row in rows}


def insert_posts(posts):
    if not posts:
        return
    conn = get_connection()
    conn.executemany(
        """INSERT OR IGNORE INTO posts
           (id, subreddit, title, selftext, author, score, num_comments, created_utc, url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                p["id"], p["subreddit"], p["title"], p["selftext"],
                p["author"], p["score"], p["num_comments"],
                p["created_utc"], p["url"],
            )
            for p in posts
        ],
    )
    conn.commit()
    conn.close()


def insert_analysis(subreddit, analysis, post_ids, raw_response):
    conn = get_connection()
    conn.execute(
        """INSERT INTO sentiment_analyses
           (subreddit, week_sentiment, week_score, week_summary,
            month_sentiment, month_score, month_summary,
            quarter_sentiment, quarter_score, quarter_summary,
            covered_call_recommendation, covered_call_reasoning,
            post_ids_json, raw_response)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            subreddit,
            analysis.get("week_sentiment"),
            analysis.get("week_score"),
            analysis.get("week_summary"),
            analysis.get("month_sentiment"),
            analysis.get("month_score"),
            analysis.get("month_summary"),
            analysis.get("quarter_sentiment"),
            analysis.get("quarter_score"),
            analysis.get("quarter_summary"),
            analysis.get("covered_call_recommendation"),
            analysis.get("covered_call_reasoning"),
            json.dumps(post_ids),
            raw_response,
        ),
    )
    analysis_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return analysis_id


def upsert_dates(subreddit, dates, analysis_id):
    if not dates:
        return
    conn = get_connection()
    for d in dates:
        conn.execute(
            """INSERT INTO important_dates
               (subreddit, event_date, estimated_quarter, event_type, description, source_analysis_id)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(subreddit, event_date, event_type)
               DO UPDATE SET
                   description = excluded.description,
                   estimated_quarter = excluded.estimated_quarter,
                   source_analysis_id = excluded.source_analysis_id,
                   last_confirmed_at = datetime('now')""",
            (
                subreddit,
                d.get("event_date"),
                d.get("estimated_quarter"),
                d["event_type"],
                d["description"],
                analysis_id,
            ),
        )
    conn.commit()
    conn.close()


def insert_notable_links(subreddit, links, analysis_id):
    if not links:
        return
    conn = get_connection()
    for link in links:
        conn.execute(
            """INSERT INTO notable_links
               (subreddit, analysis_id, link_url, title, author, score, link_type, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                subreddit,
                analysis_id,
                link["url"],
                link.get("title"),
                link.get("author"),
                link.get("score"),
                link.get("type", "post"),
                link.get("reason"),
            ),
        )
    conn.commit()
    conn.close()


def get_notable_links(subreddit, limit=10):
    conn = get_connection()
    rows = conn.execute(
        """SELECT nl.*, sa.analyzed_at FROM notable_links nl
           JOIN sentiment_analyses sa ON nl.analysis_id = sa.id
           WHERE nl.subreddit = ?
           ORDER BY nl.created_at DESC LIMIT ?""",
        (subreddit, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_analysis(subreddit):
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM sentiment_analyses
           WHERE subreddit = ?
           ORDER BY analyzed_at DESC LIMIT 1""",
        (subreddit,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_upcoming_dates(subreddit):
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT * FROM important_dates
           WHERE subreddit = ?
             AND (event_date >= ? OR event_date IS NULL)
           ORDER BY
             CASE WHEN event_date IS NULL THEN 1 ELSE 0 END,
             event_date ASC""",
        (subreddit, today),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
