"""
Cricket Analytics — Flask web application.

Endpoints
---------
GET  /                          → main SPA page
POST /api/add-match             → scrape a single match URL  → {job_id}
POST /api/add-series            → scrape all matches in a series URL → {job_id}
GET  /api/job/<job_id>          → job status
GET  /api/matches               → list all stored matches
GET  /api/match/<id>            → match info + innings
GET  /api/match/<id>/deliveries → deliveries (with filters)
GET  /api/match/<id>/overs      → runs/wickets per over (innings query param)
GET  /api/players               → distinct batsman names
GET  /api/bowlers               → distinct bowler names
GET  /api/analytics             → run a named analytics query
"""
import logging
import threading
import uuid
from typing import Dict, List

from flask import Flask, jsonify, render_template, request

import database as db
import parser as psr
from scraper import CricinfoScraper, extract_ids, extract_series_id

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
db.init_db()


# ---------------------------------------------------------------------------
# Background scrape worker
# ---------------------------------------------------------------------------

def _run_scrape(job_id: str, series_id: str, match_id: str):
    scraper = CricinfoScraper(delay=1.2)
    try:
        db.update_job(job_id, "running", "Fetching match info …", 5)

        match_info = scraper.get_match_info(series_id, match_id)
        if not match_info:
            reason = scraper.last_error or "No data returned by ESPN API"
            db.update_job(job_id, "failed", f"Could not fetch match info: {reason}", 0)
            return

        db.upsert_match({
            "match_id":    match_id,
            "series_id":   series_id,
            "title":       match_info["title"],
            "description": match_info["description"],
            "venue":       match_info["venue"],
            "match_date":  match_info["match_date"],
            "match_type":  match_info["match_type"],
            "team1":       match_info["team1"],
            "team2":       match_info["team2"],
            "result":      match_info["result"],
            "status":      "scraping",
        })
        db.set_match_status(match_id, "scraping")

        # Store innings metadata
        innings_list = match_info.get("innings", [])
        for i, inn in enumerate(innings_list):
            db.upsert_innings({
                "match_id":       match_id,
                "innings_id":     inn.get("innings_id", i + 1),
                "innings_number": inn.get("innings_number", i + 1),
                "batting_team":   inn.get("batting_team", ""),
                "bowling_team":   inn.get("bowling_team", ""),
                "total_runs":     inn.get("total_runs"),
                "total_wickets":  inn.get("total_wickets"),
                "total_overs":    inn.get("total_overs"),
            })

        # Determine how many innings exist (up to 4 for Tests)
        num_innings = max(len(innings_list), 2)

        # Remove old deliveries so re-scraping works cleanly
        db.delete_match_deliveries(match_id)

        total_deliveries = 0
        for inn_idx in range(1, num_innings + 1):
            progress = 10 + int(75 * (inn_idx - 1) / num_innings)
            db.update_job(job_id, "running", f"Scraping innings {inn_idx} …", progress)

            def _progress(msg, _id=job_id, _p=progress):
                db.update_job(_id, "running", msg, _p)

            raw_comments = scraper.get_all_commentary(
                series_id, match_id, inn_idx, progress_cb=_progress
            )

            if not raw_comments:
                log.info("No commentary for innings %d", inn_idx)
                continue

            rows: List[Dict] = []
            for raw in raw_comments:
                delivery = scraper.parse_comment(raw, match_id, inn_idx)
                if delivery is None:
                    continue
                # Parse commentary text for delivery identifiers
                identifiers = psr.parse_commentary(delivery.get("commentary", ""))
                delivery.update(identifiers)
                rows.append(delivery)

            db.insert_deliveries(rows)
            total_deliveries += len(rows)
            log.info("Innings %d: stored %d deliveries", inn_idx, len(rows))

        db.set_match_status(match_id, "done")
        db.update_job(
            job_id, "done",
            f"Complete — {total_deliveries} deliveries stored.", 100
        )

    except Exception as e:
        log.exception("Scrape job %s failed", job_id)
        db.update_job(job_id, "failed", str(e), 0)
        db.set_match_status(match_id, "failed")


def _run_series_scrape(job_id: str, series_id: str):
    scraper = CricinfoScraper(delay=1.2)
    try:
        db.update_job(job_id, "running", "Fetching series schedule …", 2)
        matches = scraper.get_series_matches(series_id)
        if not matches:
            db.update_job(job_id, "failed", "No matches found for this series.", 0)
            return

        total = len(matches)
        db.update_job(job_id, "running", f"Found {total} matches. Scraping …", 5)

        for idx, m in enumerate(matches):
            progress = 5 + int(90 * idx / total)
            db.update_job(job_id, "running",
                          f"Scraping match {idx + 1}/{total}: {m.get('title', m['match_id'])} …",
                          progress)
            sub_job = str(uuid.uuid4())
            db.create_job(sub_job, m["match_id"])
            _run_scrape(sub_job, series_id, m["match_id"])

        db.update_job(job_id, "done", f"All {total} matches scraped.", 100)

    except Exception as e:
        log.exception("Series scrape job %s failed", job_id)
        db.update_job(job_id, "failed", str(e), 0)


# ---------------------------------------------------------------------------
# Routes — UI
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------

@app.post("/api/add-match")
def api_add_match():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify(error="url is required"), 400

    series_id, match_id = extract_ids(url)
    if not match_id:
        return jsonify(error="Could not extract match ID from URL. "
                             "Expected an ESPNcricinfo match URL."), 400

    # Use a placeholder series_id if not found
    if not series_id:
        # Try to find it from DB if match already exists
        existing = db.get_match(match_id)
        series_id = (existing or {}).get("series_id") or "0"

    job_id = str(uuid.uuid4())
    db.create_job(job_id, match_id)

    t = threading.Thread(
        target=_run_scrape, args=(job_id, series_id, match_id), daemon=True
    )
    t.start()

    return jsonify(job_id=job_id, match_id=match_id)


@app.post("/api/add-series")
def api_add_series():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify(error="url is required"), 400

    series_id = extract_series_id(url)
    if not series_id:
        return jsonify(error="Could not extract series ID from URL."), 400

    job_id = str(uuid.uuid4())
    db.create_job(job_id, f"series:{series_id}")

    t = threading.Thread(
        target=_run_series_scrape, args=(job_id, series_id), daemon=True
    )
    t.start()

    return jsonify(job_id=job_id, series_id=series_id)


@app.get("/api/job/<job_id>")
def api_job(job_id):
    job = db.get_job(job_id)
    if not job:
        return jsonify(error="job not found"), 404
    return jsonify(job)


@app.get("/api/matches")
def api_matches():
    return jsonify(db.list_matches())


@app.get("/api/match/<match_id>")
def api_match(match_id):
    match = db.get_match(match_id)
    if not match:
        return jsonify(error="match not found"), 404
    match["innings"] = db.get_innings(match_id)
    return jsonify(match)


@app.get("/api/match/<match_id>/deliveries")
def api_deliveries(match_id):
    innings_number = request.args.get("innings", type=int)
    bowler    = request.args.get("bowler")
    batsman   = request.args.get("batsman")
    length    = request.args.get("length")
    line      = request.args.get("line")
    phase     = request.args.get("phase")

    rows = db.get_deliveries(
        match_id,
        innings_number=innings_number,
        bowler=bowler,
        batsman=batsman,
        length_type=length,
        line_type=line,
        phase=phase,
    )
    # Add human-readable labels and pitch coords
    for r in rows:
        r["length_label"]   = psr.label(r.get("length_type"))
        r["line_label"]     = psr.label(r.get("line_type"))
        r["movement_label"] = psr.label(r.get("movement_type"))
        r["shot_label"]     = psr.label(r.get("shot_type"))
        coords = psr.pitch_coords(r.get("length_type"), r.get("line_type"))
        r["pitch_x"], r["pitch_y"] = coords if coords else (None, None)

    return jsonify(rows)


@app.get("/api/match/<match_id>/overs")
def api_overs(match_id):
    innings_number = request.args.get("innings", 1, type=int)
    rows = db.get_over_summary(match_id, innings_number)
    return jsonify(rows)


@app.get("/api/players")
def api_players():
    return jsonify(db.get_players("batsman"))


@app.get("/api/bowlers")
def api_bowlers():
    return jsonify(db.get_players("bowler"))


@app.get("/api/analytics")
def api_analytics():
    analysis_type = request.args.get("type", "batsman_vulnerability")

    if analysis_type == "batsman_vulnerability":
        batsman = request.args.get("batsman", "")
        if not batsman:
            return jsonify(error="batsman param required"), 400
        rows = db.query_batsman_vulnerability(batsman)
        return jsonify({"type": analysis_type, "batsman": batsman, "rows": rows})

    elif analysis_type == "bowler_profile":
        bowler = request.args.get("bowler", "")
        if not bowler:
            return jsonify(error="bowler param required"), 400
        rows = db.query_bowler_profile(bowler)
        return jsonify({"type": analysis_type, "bowler": bowler, "rows": rows})

    elif analysis_type == "head_to_head":
        bowler  = request.args.get("bowler", "")
        batsman = request.args.get("batsman", "")
        if not bowler or not batsman:
            return jsonify(error="bowler and batsman params required"), 400
        rows = db.query_head_to_head(bowler, batsman)
        return jsonify({"type": analysis_type, "bowler": bowler,
                        "batsman": batsman, "rows": rows})

    elif analysis_type == "phase_analysis":
        match_id = request.args.get("match_id")
        team     = request.args.get("team")
        rows = db.query_phase_analysis(match_id=match_id, team=team)
        return jsonify({"type": analysis_type, "rows": rows})

    else:
        return jsonify(error=f"Unknown analysis type: {analysis_type}"), 400


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
