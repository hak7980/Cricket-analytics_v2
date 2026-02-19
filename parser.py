"""
Commentary parser: extracts structured delivery identifiers from raw
ESPNcricinfo ball-by-ball commentary text.

Every pattern here is pure regex / keyword matching - no external NLP
dependency required.
"""
import re
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Pattern dictionaries
# Order matters: more specific patterns before general ones.
# ---------------------------------------------------------------------------

LENGTH_PATTERNS: Dict[str, str] = {
    "full_toss":     r"\bfull[\s-]toss\b",
    "yorker":        r"\byorker\b|\byorkered\b",
    "bouncer":       r"\bbouncer\b|\bbumper\b|\bshort[\s-]and[\s-]sharp\b",
    "short":         r"\bshort[\s-]pitched\b|\bshort delivery\b|\bvery short\b"
                     r"|\bpulled short\b|\bway short\b",
    "short_of_good": r"\bshort of (?:a )?good length\b|\bback of a length\b"
                     r"|\bback-of-a-length\b|\bjust short of\b",
    "good_length":   r"\bgood[\s-]length\b|\bgood delivery\b",
    "full":          r"\bfull(?:er)?\b(?! toss)|\bover[\s-]pitched\b|\blength ball\b",
}

LINE_PATTERNS: Dict[str, str] = {
    "outside_off":  r"\boutside (?:the )?off\b|\bwide of (?:the )?off\b"
                    r"|\baway from (?:the )?off\b|\bfifth stump\b|\bsixth stump\b"
                    r"|\boff side wide\b",
    "off_stump":    r"\b(?:on (?:the )?)?off[\s-]stump(?: line)?\b",
    "middle_stump": r"\b(?:on (?:the )?)?middle(?: and off| and leg|[\s-]stump)?\b"
                    r"|\bmiddle[\s-]and[\s-]off\b|\boff[\s-]and[\s-]middle\b",
    "leg_stump":    r"\b(?:on (?:the )?)?leg[\s-]stump(?: line)?\b"
                    r"|\bmiddle[\s-]and[\s-]leg\b|\bleg[\s-]and[\s-]middle\b",
    "outside_leg":  r"\boutside (?:the )?leg\b|\bdown (?:the )?leg\b"
                    r"|\bon the pads\b|\bon (?:his|the) legs\b|\bdown leg side\b",
}

MOVEMENT_PATTERNS: Dict[str, str] = {
    "inswing":      r"\binswing(?:er)?\b|\bswings? (?:back )?in\b|\bdrifts? in\b"
                    r"|\bmoving in\b|\bgoing in\b",
    "outswing":     r"\boutswing(?:er)?\b|\bswings? (?:back )?away\b|\bdrifts? away\b"
                    r"|\bmoving away\b|\bgoing away\b",
    "off_cutter":   r"\boff[\s-]cutter\b",
    "leg_cutter":   r"\bleg[\s-]cutter\b",
    "seam":         r"\bseam(?:ing)?\b|\bseam[\s-]movement\b|\boff the seam\b",
    "googly":       r"\bgoogly\b|\bwrong[\s-](?:')?un\b",
    "doosra":       r"\bdoosra\b",
    "flipper":      r"\bflipper\b",
    "slider":       r"\bslider\b",
    "arm_ball":     r"\barm[\s-]ball\b",
    "carrom":       r"\bcarrom\b",
    "top_spinner":  r"\btop[\s-]spinner\b|\btop[\s-]spin\b",
    "off_break":    r"\boff[\s-]break\b|\boff[\s-]spin(?:ner)?\b",
    "leg_break":    r"\bleg[\s-]break\b|\bleg[\s-]spin(?:ner)?\b",
}

SHOT_PATTERNS: Dict[str, str] = {
    "reverse_sweep":  r"\breverse[\s-]sweep\b",
    "sweep":          r"\bsweep(?:s|ing|t)?\b",
    "hook":           r"\bhook(?:s|ed|ing)?\b",
    "pull":           r"\bpull(?:s|ed|ing)?\b",
    "cut":            r"\bcut(?:s|ting)?\b|\blate[\s-]cut\b|\bsquare[\s-]cut\b",
    "scoop":          r"\bscoop(?:s|ed|ing)?\b",
    "ramp":           r"\bramp(?:s|ed|ing)?\b",
    "paddle":         r"\bpaddle(?:s|d|ing)?\b",
    "slog":           r"\bslog(?:s|ged|ging)?\b",
    "loft":           r"\bloft(?:s|ed|ing)?\b|\blofted\b",
    "glance":         r"\bglanc(?:e|es|ed|ing)\b",
    "flick":          r"\bflick(?:s|ed|ing)?\b",
    "nudge":          r"\bnudg(?:e|es|ed|ing)\b",
    "punch":          r"\bpunch(?:es|ed|ing)?\b",
    "dab":            r"\bdab(?:s|bed|bing)?\b",
    "drive":          r"\bdriv(?:e|es|en|ing|es)\b|\bdrove\b",
    "block":          r"\bblock(?:s|ed|ing)?\b|\bdefend(?:s|ed|ing)?\b|\bplay(?:s|ed)? it back\b",
    "leave":          r"\bleav(?:e|es|ing)\b|\bleft alone\b|\bleaves it\b",
}

CONTROL_PATTERNS: Dict[str, str] = {
    "beaten":    r"\bbeat(?:s|ing|en)?\b|\bmiss(?:es|ed)?\b|\bbeaten all ends up\b"
                 r"|\bplayed and missed\b|\bplays and misses\b",
    "mistimed":  r"\bmistrip(?:s|ped|ping)?\b|\bmis[\s-]time(?:d|s)?\b|\bmishit\b"
                 r"|\bskies\b|\bskied\b|\bin the air\b|\bmistimed\b",
}

EDGE_PATTERNS: Dict[str, str] = {
    "inside_edge":  r"\binside[\s-]edg(?:e|es|ed|ing)\b|\boff the inside\b"
                    r"|\binside[\s-]edge\b",
    "outside_edge": r"\boutside[\s-]edg(?:e|es|ed|ing)\b|\bthin edge\b|\bthick edge\b"
                    r"|\bedge(?:s|d)? (?:to|through|behind)\b|\bedged\b",
    "top_edge":     r"\btop[\s-]edg(?:e|es|ed|ing)\b",
    "bottom_edge":  r"\bbottom[\s-]edg(?:e|es|ed|ing)\b",
}

SLOWER_BALL_PATTERNS: str = (
    r"\bslower[\s-](?:one|ball|delivery)\b|\bchange[\s-]of[\s-]pace\b"
    r"|\bchanged[\s-]up\b|\bslowing (?:it|the ball) (?:down|up)\b"
    r"|\boff[\s-]pace\b|\bheld[\s-]up\b|\bcutting (?:the ball )?back\b"
)

# Pre-compile all patterns for performance
_compiled_length    = {k: re.compile(v, re.I) for k, v in LENGTH_PATTERNS.items()}
_compiled_line      = {k: re.compile(v, re.I) for k, v in LINE_PATTERNS.items()}
_compiled_movement  = {k: re.compile(v, re.I) for k, v in MOVEMENT_PATTERNS.items()}
_compiled_shot      = {k: re.compile(v, re.I) for k, v in SHOT_PATTERNS.items()}
_compiled_control   = {k: re.compile(v, re.I) for k, v in CONTROL_PATTERNS.items()}
_compiled_edge      = {k: re.compile(v, re.I) for k, v in EDGE_PATTERNS.items()}
_compiled_slower    = re.compile(SLOWER_BALL_PATTERNS, re.I)


def _first_match(text: str, compiled: Dict[str, re.Pattern]) -> Optional[str]:
    """Return the first key whose pattern matches, or None."""
    for key, pattern in compiled.items():
        if pattern.search(text):
            return key
    return None


def _any_match(text: str, compiled: Dict[str, re.Pattern]) -> Optional[str]:
    """Alias for _first_match (readability)."""
    return _first_match(text, compiled)


def parse_commentary(text: str) -> Dict:
    """
    Parse a single ball's commentary string and return a dict of
    delivery identifiers. All fields may be None if not detectable.
    """
    if not text:
        return _empty_result()

    # Normalise: collapse whitespace, strip
    text = re.sub(r"\s+", " ", text).strip()

    length_type   = _first_match(text, _compiled_length)
    line_type     = _first_match(text, _compiled_line)
    movement_type = _first_match(text, _compiled_movement)
    shot_type     = _first_match(text, _compiled_shot)
    control_type  = _any_match(text, _compiled_control)
    edge_type     = _first_match(text, _compiled_edge)
    is_slower     = int(bool(_compiled_slower.search(text)))

    # Edge detection overrides generic control
    if edge_type:
        control_type = "edged"

    # Bouncer implies short length
    if length_type == "bouncer":
        pass  # keep as-is; bouncer IS a length descriptor

    return {
        "length_type":   length_type,
        "line_type":     line_type,
        "movement_type": movement_type,
        "shot_type":     shot_type,
        "is_slower_ball": is_slower,
        "control_type":  control_type,
        "edge_type":     edge_type,
    }


def _empty_result() -> Dict:
    return {
        "length_type":    None,
        "line_type":      None,
        "movement_type":  None,
        "shot_type":      None,
        "is_slower_ball": 0,
        "control_type":   None,
        "edge_type":      None,
    }


# ---------------------------------------------------------------------------
# Pitch-map coordinate helpers  (for frontend rendering)
# ---------------------------------------------------------------------------

LENGTH_X: Dict[str, float] = {
    "bouncer":       0.10,
    "short":         0.22,
    "short_of_good": 0.38,
    "good_length":   0.55,
    "full":          0.72,
    "yorker":        0.88,
    "full_toss":     0.97,
}

LINE_Y: Dict[str, float] = {
    "outside_leg":  0.10,
    "leg_stump":    0.28,
    "middle_stump": 0.46,
    "off_stump":    0.64,
    "outside_off":  0.82,
}


def pitch_coords(length_type: Optional[str], line_type: Optional[str]):
    """
    Return (x, y) in [0,1] for a pitch-map dot.
    x = length axis (0=near bowler, 1=near batsman)
    y = line axis (0=leg side, 1=off side)
    Returns None if both are unknown.
    """
    x = LENGTH_X.get(length_type) if length_type else None
    y = LINE_Y.get(line_type) if line_type else None
    if x is None and y is None:
        return None
    return (x or 0.5, y or 0.5)


# ---------------------------------------------------------------------------
# Human-readable label helpers
# ---------------------------------------------------------------------------

LABELS = {
    # length
    "full_toss":     "Full toss",
    "yorker":        "Yorker",
    "bouncer":       "Bouncer",
    "short":         "Short",
    "short_of_good": "Short of good length",
    "good_length":   "Good length",
    "full":          "Full",
    # line
    "outside_off":   "Outside off",
    "off_stump":     "Off stump",
    "middle_stump":  "Middle stump",
    "leg_stump":     "Leg stump",
    "outside_leg":   "Outside leg",
    # movement
    "inswing":   "Inswing", "outswing":  "Outswing",
    "off_cutter":"Off cutter","leg_cutter":"Leg cutter",
    "seam":      "Seam","googly":"Googly","doosra":"Doosra",
    "flipper":   "Flipper","slider":"Slider","arm_ball":"Arm ball",
    "carrom":    "Carrom ball","top_spinner":"Top spinner",
    "off_break": "Off break","leg_break":"Leg break",
    # shot
    "drive":"Drive","cut":"Cut","pull":"Pull","hook":"Hook",
    "sweep":"Sweep","reverse_sweep":"Reverse sweep","glance":"Glance",
    "flick":"Flick","nudge":"Nudge","punch":"Punch","dab":"Dab",
    "scoop":"Scoop","ramp":"Ramp","paddle":"Paddle","slog":"Slog",
    "loft":"Loft","block":"Block/Defend","leave":"Leave",
    # control
    "beaten":"Beaten","mistimed":"Mistimed","edged":"Edged",
    # edge
    "inside_edge":"Inside edge","outside_edge":"Outside edge",
    "top_edge":"Top edge","bottom_edge":"Bottom edge",
}


def label(key: Optional[str]) -> str:
    if key is None:
        return ""
    return LABELS.get(key, key.replace("_", " ").title())
