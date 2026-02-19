"""
ESPNcricinfo scraper.

Uses the hs-consumer-api (unofficial JSON API) that powers the
espncricinfo.com website itself.  No HTML parsing required.

Rate-limiting: 1 s between requests by default.
"""
import re
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE = "https://hs-consumer-api.espncricinfo.com/v1/pages"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin":          "https://www.espncricinfo.com",
    "Referer":         "https://www.espncricinfo.com/",
}


# ---------------------------------------------------------------------------
# URL / ID helpers
# ---------------------------------------------------------------------------

def extract_ids(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Return (series_id, match_id) from an ESPNcricinfo match URL.

    Handles patterns like:
      /series/some-name-1367856/some-match-name-1384438/...
      /matches/engine/match/1384438.json
    """
    # Standard series/match URL
    m = re.search(r"/series/[^/]+-(\d+)/[^/]+-(\d+)/", url)
    if m:
        return m.group(1), m.group(2)

    # Alternate: series slug then match slug (no trailing slash)
    m = re.search(r"/series/[^/]+-(\d+)/[^/]+-(\d+)", url)
    if m:
        return m.group(1), m.group(2)

    # Old engine URL
    m = re.search(r"/match/(\d+)", url)
    if m:
        return None, m.group(1)

    return None, None


def extract_series_id(url: str) -> Optional[str]:
    m = re.search(r"/series/[^/]+-(\d+)", url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class CricinfoScraper:
    def __init__(self, delay: float = 1.2):
        self.delay = delay
        self.last_error: str = ""
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.verify = False

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    def _get(self, url: str, params: Dict = None, retries: int = 3) -> Optional[Dict]:
        for attempt in range(retries):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                log.info("GET %s → HTTP %s", resp.url, resp.status_code)
                resp.raise_for_status()
                time.sleep(self.delay)
                return resp.json()
            except requests.exceptions.HTTPError as e:
                self.last_error = f"HTTP {e.response.status_code} from ESPN API"
                log.warning("HTTP %s for %s (attempt %d) — body: %s",
                            e.response.status_code, url, attempt + 1,
                            e.response.text[:300])
                if e.response.status_code in (429, 503):
                    time.sleep(2 ** attempt * 5)
                else:
                    break
            except requests.exceptions.SSLError as e:
                self.last_error = f"SSL error: {e}"
                log.warning("SSL error (attempt %d): %s", attempt + 1, e)
                time.sleep(2 ** attempt)
            except requests.exceptions.ConnectionError as e:
                self.last_error = f"Connection error: {e}"
                log.warning("Connection error (attempt %d): %s", attempt + 1, e)
                time.sleep(2 ** attempt)
            except Exception as e:
                self.last_error = str(e)
                log.warning("Request error (attempt %d): %s", attempt + 1, e)
                time.sleep(2 ** attempt)
        return None

    # ------------------------------------------------------------------
    # Match info
    # ------------------------------------------------------------------

    def get_match_info(self, series_id: str, match_id: str) -> Optional[Dict]:
        # Primary attempt with both IDs
        data = self._get(f"{BASE}/match/home", {
            "lang": "en",
            "seriesId": series_id,
            "matchId": match_id,
        })
        # Fallback: try without seriesId (some matches work with matchId alone)
        if not data and series_id and series_id != "0":
            log.info("Retrying get_match_info without seriesId")
            data = self._get(f"{BASE}/match/home", {
                "lang": "en",
                "matchId": match_id,
            })
        if not data:
            return None
        try:
            return self._parse_match_info(data, series_id, match_id)
        except Exception as e:
            log.exception("_parse_match_info failed: %s", e)
            self.last_error = f"Parsing failed: {e}"
            return None

    @staticmethod
    def _parse_match_info(data: Dict, series_id: str, match_id: str) -> Dict:
        match = data.get("match", data.get("matchInfo", {}))
        series = data.get("series", {})

        def _team(t):
            if isinstance(t, dict):
                return t.get("longName") or t.get("name") or t.get("shortName", "")
            return str(t)

        teams = match.get("teams", [])
        team1 = _team(teams[0].get("team", teams[0])) if len(teams) > 0 else ""
        team2 = _team(teams[1].get("team", teams[1])) if len(teams) > 1 else ""

        ground = match.get("ground", {})
        venue = ground.get("ground", {}).get("longName") or ground.get("longName") or \
                ground.get("name", "") if isinstance(ground, dict) else str(ground)

        # Try multiple date fields
        date = (match.get("startDate") or match.get("startTime") or
                match.get("date") or "")
        if date and len(str(date)) > 10:
            date = str(date)[:10]

        match_type_raw = match.get("matchType") or match.get("gameType") or ""
        match_type_map = {"TEST": "Test", "ODI": "ODI", "T20": "T20I",
                          "MDM": "First-class", "LIST_A": "List A"}
        match_type = match_type_map.get(str(match_type_raw).upper(), str(match_type_raw))

        title = (match.get("description") or match.get("title") or
                 f"{team1} vs {team2}")
        result = (data.get("status") or match.get("statusText") or
                  match.get("status") or "")

        innings_list = data.get("innings", [])
        innings_data = []
        for i, inn in enumerate(innings_list):
            innings_data.append({
                "innings_id":      inn.get("inningsId", i + 1),
                "innings_number":  i + 1,
                "batting_team":    _team(inn.get("team", {})),
                "bowling_team":    "",
                "total_runs":      inn.get("runs"),
                "total_wickets":   inn.get("wickets"),
                "total_overs":     _parse_overs(inn.get("overs")),
            })

        return {
            "match_id":    match_id,
            "series_id":   series_id,
            "title":       title,
            "description": match.get("description", ""),
            "venue":       venue,
            "match_date":  date,
            "match_type":  match_type,
            "team1":       team1,
            "team2":       team2,
            "result":      result,
            "innings":     innings_data,
        }

    # ------------------------------------------------------------------
    # Commentary
    # ------------------------------------------------------------------

    def get_all_commentary(
        self,
        series_id: str,
        match_id: str,
        innings_id: int,
        progress_cb=None,
    ) -> List[Dict]:
        """
        Fetch all ball-by-ball comments for one innings.
        Returns a list of raw comment dicts.
        """
        all_comments: List[Dict] = []
        from_over = -1
        page = 0

        while True:
            page += 1
            if progress_cb:
                progress_cb(f"Fetching innings {innings_id} page {page} …")

            data = self._get(f"{BASE}/match/comments", {
                "lang":          "en",
                "seriesId":      series_id,
                "matchId":       match_id,
                "innings":       innings_id,
                "commentType":   "ALL",
                "fromInningOver": from_over,
            })

            if not data:
                log.warning("No data returned for innings %s page %s", innings_id, page)
                break

            comments = data.get("comments", [])
            # Keep only actual ball deliveries
            ball_comments = [c for c in comments if c.get("isBallCommentary", False)]
            all_comments.extend(ball_comments)

            has_more = data.get("hasMore", False)
            if not has_more:
                break

            # Figure out next page marker
            last_over = data.get("nextFromOver") or data.get("lastInningOver")
            if last_over is None and ball_comments:
                last_over = ball_comments[-1].get("overNumber")
            if last_over is None:
                break
            if last_over == from_over:
                break  # Stuck – give up
            from_over = last_over

        return all_comments

    # ------------------------------------------------------------------
    # Parse raw comment → structured delivery row
    # ------------------------------------------------------------------

    @staticmethod
    def parse_comment(raw: Dict, match_id: str, innings_number: int) -> Optional[Dict]:
        """Convert a raw API comment to a delivery dict (without parser identifiers)."""
        if not raw.get("isBallCommentary", False):
            return None

        over_num  = raw.get("overNumber", 0)
        ball_num  = raw.get("ballNumber", 0)
        over_ball = f"{over_num}.{ball_num}"

        # Bowler
        bowler_raw = raw.get("bowler") or {}
        bowler = (bowler_raw.get("name") or bowler_raw.get("longName") or
                  raw.get("bowlerName") or "")

        # Batsmen (the one on strike)
        batsmen = raw.get("batsmen", [])
        if batsmen and isinstance(batsmen, list):
            b0 = batsmen[0] if batsmen else {}
            batsman = b0.get("name") or b0.get("longName") or raw.get("batsmanName", "")
        else:
            batsman = raw.get("batsmanName", "")

        non_striker_raw = raw.get("nonStriker") or {}
        non_striker = (non_striker_raw.get("name") or non_striker_raw.get("longName") or
                       raw.get("nonStrikerName", ""))

        runs_off_bat = int(raw.get("batsmanRuns", 0) or 0)
        extras       = int(raw.get("extraRuns", raw.get("totalExtras", 0)) or 0)
        extra_type   = str(raw.get("extraType", "") or "").lower() or None

        # Wicket
        wkt_info     = raw.get("wicket") or raw.get("wicketInfo") or {}
        wicket_type  = None
        wicket_field = None
        if wkt_info:
            wicket_type  = wkt_info.get("type") or wkt_info.get("dismissalType") or ""
            wicket_type  = str(wicket_type).lower() or None
            fielders     = wkt_info.get("fielders", [])
            if fielders and isinstance(fielders, list):
                wicket_field = fielders[0].get("name") if fielders else None

        # Commentary text
        commentary = (raw.get("displayText") or raw.get("commentTextItems") or
                      raw.get("text") or "")
        if isinstance(commentary, list):
            commentary = " ".join(str(x) for x in commentary)

        return {
            "match_id":      match_id,
            "innings_number": innings_number,
            "over_number":   over_num,
            "ball_number":   ball_num,
            "over_ball":     over_ball,
            "bowler":        bowler,
            "batsman":       batsman,
            "non_striker":   non_striker,
            "runs_off_bat":  runs_off_bat,
            "extras":        extras,
            "extra_type":    extra_type,
            "wicket_type":   wicket_type,
            "wicket_fielder": wicket_field,
            "commentary":    commentary,
        }

    # ------------------------------------------------------------------
    # Series schedule
    # ------------------------------------------------------------------

    def get_series_matches(self, series_id: str) -> List[Dict]:
        """Return a list of {match_id, series_id, title} for all matches in a series."""
        data = self._get(f"{BASE}/series/schedule", {
            "lang": "en",
            "seriesId": series_id,
        })
        if not data:
            return []

        matches = []
        for content_item in data.get("content", [data]):
            for match in content_item.get("matches", content_item.get("matchScheduleList", [])):
                mid  = (match.get("matchId") or match.get("id") or
                        match.get("match", {}).get("id"))
                desc = (match.get("description") or match.get("title") or
                        match.get("match", {}).get("description", ""))
                if mid:
                    matches.append({
                        "match_id":  str(mid),
                        "series_id": series_id,
                        "title":     desc,
                    })
        return matches


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _parse_overs(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        m = re.match(r"(\d+)\.(\d+)", str(val))
        if m:
            return int(m.group(1)) + int(m.group(2)) / 6
    return None
