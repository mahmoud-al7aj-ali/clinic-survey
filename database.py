import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "survey.db"))

RATING_LABELS = {
    "very_important": "مهمة جداً",
    "important": "مهمة",
    "nice_to_have": "مفيدة",
    "not_needed": "غير ضرورية",
}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS surveys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                brand_name TEXT NOT NULL DEFAULT 'نظام إدارة العيادات الذكي',
                tag TEXT DEFAULT 'استطلاع أولويات',
                intro_text TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                survey_id INTEGER NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
                page_order INTEGER NOT NULL DEFAULT 0,
                page_label TEXT,
                page_title TEXT,
                page_num TEXT,
                UNIQUE(survey_id, page_order)
            );

            CREATE TABLE IF NOT EXISTS feature_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
                icon TEXT DEFAULT '📋',
                title TEXT NOT NULL,
                subtitle TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL REFERENCES feature_groups(id) ON DELETE CASCADE,
                feature_num INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                long_description TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                survey_id INTEGER NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
                doctor_name TEXT NOT NULL,
                clinic_name TEXT NOT NULL,
                phone TEXT,
                notes TEXT,
                submitted_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS response_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                response_id INTEGER NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
                feature_id INTEGER NOT NULL REFERENCES features(id),
                rating TEXT NOT NULL,
                UNIQUE(response_id, feature_id)
            );

            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            );
            """
        )
        migrate_db(conn)


def migrate_db(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(features)").fetchall()}
    if "long_description" not in cols:
        conn.execute("ALTER TABLE features ADD COLUMN long_description TEXT")
        conn.execute(
            """
            UPDATE features
            SET long_description = description
            WHERE long_description IS NULL OR long_description = ''
            """
        )

    response_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(responses)").fetchall()
    }
    if "email" not in response_cols:
        conn.execute("ALTER TABLE responses ADD COLUMN email TEXT")


def get_active_survey(conn):
    row = conn.execute(
        "SELECT * FROM surveys WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row


def survey_structure(conn, survey_id):
    sections = conn.execute(
        """
        SELECT * FROM sections
        WHERE survey_id = ?
        ORDER BY page_order
        """,
        (survey_id,),
    ).fetchall()

    structure = []
    for section in sections:
        groups = conn.execute(
            """
            SELECT * FROM feature_groups
            WHERE section_id = ?
            ORDER BY sort_order, id
            """,
            (section["id"],),
        ).fetchall()
        group_list = []
        for group in groups:
            features = conn.execute(
                """
                SELECT * FROM features
                WHERE group_id = ? AND is_active = 1
                ORDER BY sort_order, feature_num
                """,
                (group["id"],),
            ).fetchall()
            if features:
                group_list.append({"group": group, "features": features})
        if group_list:
            structure.append({"section": section, "groups": group_list})
    return structure


def count_active_features(conn, survey_id):
    return conn.execute(
        """
        SELECT COUNT(*) FROM features f
        JOIN feature_groups g ON g.id = f.group_id
        JOIN sections s ON s.id = g.section_id
        WHERE s.survey_id = ? AND f.is_active = 1
        """,
        (survey_id,),
    ).fetchone()[0]


RATING_WEIGHTS = {
    "very_important": 4,
    "important": 3,
    "nice_to_have": 2,
    "not_needed": 1,
}


def feature_rating_rankings(conn, survey_id, sort_by="score"):
    """All active features with vote counts per rating, sorted for dashboard."""
    rows = conn.execute(
        """
        SELECT
            f.id,
            f.feature_num,
            f.title,
            f.description,
            g.title AS group_title,
            s.page_title,
            SUM(CASE WHEN ra.rating = 'very_important' THEN 1 ELSE 0 END) AS cnt_very_important,
            SUM(CASE WHEN ra.rating = 'important' THEN 1 ELSE 0 END) AS cnt_important,
            SUM(CASE WHEN ra.rating = 'nice_to_have' THEN 1 ELSE 0 END) AS cnt_nice_to_have,
            SUM(CASE WHEN ra.rating = 'not_needed' THEN 1 ELSE 0 END) AS cnt_not_needed,
            COUNT(ra.id) AS total_votes,
            AVG(CASE ra.rating
                WHEN 'very_important' THEN 4.0
                WHEN 'important' THEN 3.0
                WHEN 'nice_to_have' THEN 2.0
                WHEN 'not_needed' THEN 1.0
            END) AS priority_score
        FROM features f
        JOIN feature_groups g ON g.id = f.group_id
        JOIN sections s ON s.id = g.section_id
        LEFT JOIN response_answers ra ON ra.feature_id = f.id
        LEFT JOIN responses r ON r.id = ra.response_id AND r.survey_id = ?
        WHERE s.survey_id = ? AND f.is_active = 1
        GROUP BY f.id
        """,
        (survey_id, survey_id),
    ).fetchall()

    items = [dict(row) for row in rows]
    for item in items:
        item["priority_score"] = (
            round(item["priority_score"], 2) if item["priority_score"] is not None else None
        )
        tv = item["total_votes"] or 0
        item["pct_very_important"] = (
            round(100 * item["cnt_very_important"] / tv, 1) if tv else 0
        )

    if sort_by == "very_important":
        items.sort(
            key=lambda x: (
                -x["cnt_very_important"],
                -(x["priority_score"] or 0),
                x["feature_num"],
            )
        )
    elif sort_by == "num":
        items.sort(key=lambda x: x["feature_num"])
    else:
        items.sort(
            key=lambda x: (
                -(x["priority_score"] or 0),
                -x["cnt_very_important"],
                x["feature_num"],
            )
        )

    return items
