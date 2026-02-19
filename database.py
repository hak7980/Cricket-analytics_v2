"""
SQLite database layer for Cricket Analytics.
Thread-safe using WAL mode and per-call connections.
"""
import sqlite3
import os
from contextlib import contextmanager
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "cricket.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS matches (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id         TEXT    UNIQUE NOT NULL,
                series_id        TEXT,
                title            TEXT,
                description      TEXT,
                venue            TEXT,
                match_date       TEXT,
                match_type       TEXT,
                team1            TEXT,
                team2            TEXT,
                result           TEXT,
                status           TEXT    DEFAULT 'pending',
                scraped_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS innings (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id         TEXT    NOT NULL,
                innings_id       INTEGER NOT NULL,
                innings_number   INTEGER NOT NULL,
                batting_team     TEXT,
                bowling_team     TEXT,
                total_runs       INTEGER,
                total_wickets    INTEGER,
                total_overs      REAL,
                FOREIGN KEY (match_id) REFERENCES matches(match_id),
                UNIQUE (match_id, innings_id)
            );

            CREATE TABLE IF NOT EXISTS deliveries (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id         TEXT    NOT NULL,
                innings_number   INTEGER NOT NULL,
                over_number      INTEGER NOT NULL,
                ball_number      INTEGER NOT NULL,
                over_ball        TEXT,
                bowler           TEXT,
                batsman          TEXT,
                non_striker      TEXT,
                runs_off_bat     INTEGER DEFAULT 0,
                extras           INTEGER DEFAULT 0,
                extra_type       TEXT,
                wicket_type      TEXT,
                wicket_fielder   TEXT,
                commentary       TEXT,
                length_type      TEXT,
                line_type        TEXT,
                movement_type    TEXT,
                shot_type        TEXT,
                is_slower_ball   INTEGER DEFAULT 0,
                control_type     TEXT,
                edge_type        TEXT,
                FOREIGN KEY (match_id) REFERENCES matches(match_id)
            );

            CREATE INDEX IF NOT EXISTS idx_del_match    ON deliveries(match_id);
            CREATE INDEX IF NOT EXISTS idx_del_bowler   ON deliveries(bowler);
            CREATE INDEX IF NOT EXISTS idx_del_batsman  ON deliveries(batsman);
            CREATE INDEX IF NOT EXISTS idx_del_length   ON deliveries(length_type);
            CREATE INDEX IF NOT EXISTS idx_del_line     ON deliveries(line_type);

            CREATE TABLE IF NOT EXISTS scrape_jobs (
                job_id      TEXT PRIMARY KEY,
                match_id    TEXT,
                status      TEXT DEFAULT 'pending',
                message     TEXT,
                progress    INTEGER DEFAULT 0,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)


# ---------------------------------------------------------------------------
# Match helpers
# ---------------------------------------------------------------------------

def upsert_match(data: Dict) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO matches (match_id, series_id, title, description, venue,
                                 match_date, match_type, team1, team2, result, status)
            VALUES (:match_id, :series_id, :title, :description, :venue,
                    :match_date, :match_type, :team1, :team2, :result, :status)
            ON CONFLICT(match_id) DO UPDATE SET
                title=excluded.title, description=excluded.description,
                venue=excluded.venue, match_date=excluded.match_date,
                match_type=excluded.match_type, team1=excluded.team1,
                team2=excluded.team2, result=excluded.result, status=excluded.status
        """, data)


def set_match_status(match_id: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE matches SET status=? WHERE match_id=?", (status, match_id))


def get_match(match_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM matches WHERE match_id=?", (match_id,)).fetchone()
        return dict(row) if row else None


def list_matches() -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM matches ORDER BY match_date DESC, id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Innings helpers
# ---------------------------------------------------------------------------

def upsert_innings(data: Dict) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO innings (match_id, innings_id, innings_number, batting_team,
                                 bowling_team, total_runs, total_wickets, total_overs)
            VALUES (:match_id, :innings_id, :innings_number, :batting_team,
                    :bowling_team, :total_runs, :total_wickets, :total_overs)
            ON CONFLICT(match_id, innings_id) DO UPDATE SET
                batting_team=excluded.batting_team, bowling_team=excluded.bowling_team,
                total_runs=excluded.total_runs, total_wickets=excluded.total_wickets,
                total_overs=excluded.total_overs
        """, data)


def get_innings(match_id: str) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM innings WHERE match_id=? ORDER BY innings_number",
            (match_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Delivery helpers
# ---------------------------------------------------------------------------

def insert_deliveries(rows: List[Dict]) -> None:
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO deliveries (
                match_id, innings_number, over_number, ball_number, over_ball,
                bowler, batsman, non_striker, runs_off_bat, extras, extra_type,
                wicket_type, wicket_fielder, commentary,
                length_type, line_type, movement_type, shot_type,
                is_slower_ball, control_type, edge_type
            ) VALUES (
                :match_id, :innings_number, :over_number, :ball_number, :over_ball,
                :bowler, :batsman, :non_striker, :runs_off_bat, :extras, :extra_type,
                :wicket_type, :wicket_fielder, :commentary,
                :length_type, :line_type, :movement_type, :shot_type,
                :is_slower_ball, :control_type, :edge_type
            )
        """, rows)


def delete_match_deliveries(match_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM deliveries WHERE match_id=?", (match_id,))
        conn.execute("DELETE FROM innings    WHERE match_id=?", (match_id,))


def get_deliveries(match_id: str, innings_number: Optional[int] = None,
                   bowler: Optional[str] = None, batsman: Optional[str] = None,
                   length_type: Optional[str] = None, line_type: Optional[str] = None,
                   phase: Optional[str] = None) -> List[Dict]:
    conditions = ["match_id = ?"]
    params: List[Any] = [match_id]

    if innings_number is not None:
        conditions.append("innings_number = ?")
        params.append(innings_number)
    if bowler:
        conditions.append("bowler LIKE ?")
        params.append(f"%{bowler}%")
    if batsman:
        conditions.append("batsman LIKE ?")
        params.append(f"%{batsman}%")
    if length_type:
        conditions.append("length_type = ?")
        params.append(length_type)
    if line_type:
        conditions.append("line_type = ?")
        params.append(line_type)
    if phase == "powerplay":
        conditions.append("over_number < 6")
    elif phase == "middle":
        conditions.append("over_number BETWEEN 6 AND 14")
    elif phase == "death":
        conditions.append("over_number >= 15")

    where = " AND ".join(conditions)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM deliveries WHERE {where} ORDER BY innings_number, over_number, ball_number",
            params
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Analytics queries
# ---------------------------------------------------------------------------

def query_batsman_vulnerability(batsman: str) -> List[Dict]:
    """For a given batsman, return stats grouped by length + line."""
    sql = """
        SELECT
            COALESCE(length_type, 'unknown')  AS length_type,
            COALESCE(line_type,   'unknown')  AS line_type,
            COUNT(*)                                                       AS balls,
            SUM(runs_off_bat)                                              AS runs,
            SUM(CASE WHEN wicket_type IS NOT NULL AND wicket_type != ''
                     THEN 1 ELSE 0 END)                                    AS wickets,
            ROUND(AVG(runs_off_bat), 2)                                    AS run_rate,
            ROUND(100.0 * SUM(CASE WHEN runs_off_bat = 0 AND (extra_type IS NULL OR extra_type = '')
                                   THEN 1 ELSE 0 END) / COUNT(*), 1)      AS dot_pct,
            ROUND(100.0 * SUM(CASE WHEN runs_off_bat >= 4 THEN 1 ELSE 0 END)
                        / COUNT(*), 1)                                     AS boundary_pct
        FROM deliveries
        WHERE batsman LIKE ?
          AND (extra_type IS NULL OR extra_type NOT IN ('wide', 'no-ball'))
        GROUP BY length_type, line_type
        HAVING balls >= 5
        ORDER BY wickets DESC, dot_pct DESC
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (f"%{batsman}%",)).fetchall()
        return [dict(r) for r in rows]


def query_bowler_profile(bowler: str) -> List[Dict]:
    """Delivery type distribution + economy per type for a bowler."""
    sql = """
        SELECT
            COALESCE(length_type, 'unknown')  AS length_type,
            COALESCE(line_type,   'unknown')  AS line_type,
            COALESCE(movement_type, '')        AS movement_type,
            COUNT(*)                           AS balls,
            SUM(runs_off_bat + extras)         AS runs,
            SUM(CASE WHEN wicket_type IS NOT NULL AND wicket_type != ''
                     THEN 1 ELSE 0 END)        AS wickets,
            ROUND(6.0 * SUM(runs_off_bat + extras) / COUNT(*), 2)  AS economy,
            ROUND(100.0 * SUM(CASE WHEN runs_off_bat = 0 AND extras = 0
                                   THEN 1 ELSE 0 END) / COUNT(*), 1) AS dot_pct
        FROM deliveries
        WHERE bowler LIKE ?
          AND (extra_type IS NULL OR extra_type NOT IN ('wide', 'no-ball'))
        GROUP BY length_type, line_type, movement_type
        HAVING balls >= 3
        ORDER BY balls DESC
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (f"%{bowler}%",)).fetchall()
        return [dict(r) for r in rows]


def query_head_to_head(bowler: str, batsman: str) -> List[Dict]:
    sql = """
        SELECT
            m.title, m.match_date, m.match_type,
            d.innings_number, d.over_number, d.ball_number, d.over_ball,
            d.runs_off_bat, d.extras, d.extra_type,
            d.wicket_type, d.commentary,
            d.length_type, d.line_type, d.movement_type, d.shot_type,
            d.is_slower_ball, d.control_type, d.edge_type
        FROM deliveries d
        JOIN matches m ON d.match_id = m.match_id
        WHERE d.bowler  LIKE ?
          AND d.batsman LIKE ?
        ORDER BY m.match_date, d.innings_number, d.over_number, d.ball_number
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (f"%{bowler}%", f"%{batsman}%")).fetchall()
        return [dict(r) for r in rows]


def query_phase_analysis(match_id: Optional[str] = None,
                          team: Optional[str] = None) -> List[Dict]:
    conditions = []
    params: List[Any] = []
    if match_id:
        conditions.append("d.match_id = ?")
        params.append(match_id)
    if team:
        conditions.append("(m.team1 LIKE ? OR m.team2 LIKE ?)")
        params.extend([f"%{team}%", f"%{team}%"])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT
            CASE
                WHEN over_number < 6  THEN 'Powerplay (1-6)'
                WHEN over_number < 15 THEN 'Middle (7-15)'
                ELSE                       'Death (16+)'
            END AS phase,
            COUNT(*)                                                       AS balls,
            SUM(runs_off_bat + extras)                                     AS runs,
            SUM(CASE WHEN wicket_type IS NOT NULL AND wicket_type != ''
                     THEN 1 ELSE 0 END)                                    AS wickets,
            ROUND(6.0 * SUM(runs_off_bat + extras) / COUNT(*), 2)         AS run_rate,
            ROUND(100.0 * SUM(CASE WHEN runs_off_bat >= 4 THEN 1 ELSE 0 END)
                        / COUNT(*), 1)                                     AS boundary_pct,
            ROUND(100.0 * SUM(CASE WHEN runs_off_bat = 0 AND extras = 0
                                   THEN 1 ELSE 0 END) / COUNT(*), 1)      AS dot_pct
        FROM deliveries d
        JOIN matches m ON d.match_id = m.match_id
        {where}
        GROUP BY phase
        ORDER BY MIN(over_number)
    """
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_players(role: str = "batsman") -> List[str]:
    col = "batsman" if role == "batsman" else "bowler"
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT {col} FROM deliveries WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}"
        ).fetchall()
        return [r[0] for r in rows]


def get_over_summary(match_id: str, innings_number: int) -> List[Dict]:
    sql = """
        SELECT
            over_number,
            SUM(runs_off_bat + extras)   AS runs,
            SUM(CASE WHEN wicket_type IS NOT NULL AND wicket_type != ''
                     THEN 1 ELSE 0 END) AS wickets
        FROM deliveries
        WHERE match_id=? AND innings_number=?
        GROUP BY over_number
        ORDER BY over_number
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (match_id, innings_number)).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Scrape job helpers
# ---------------------------------------------------------------------------

def create_job(job_id: str, match_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO scrape_jobs (job_id, match_id, status, message, progress) VALUES (?,?,?,?,?)",
            (job_id, match_id, "pending", "Queued", 0)
        )


def update_job(job_id: str, status: str, message: str, progress: int = 0) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE scrape_jobs SET status=?, message=?, progress=?, updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
            (status, message, progress, job_id)
        )


def get_job(job_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM scrape_jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None
