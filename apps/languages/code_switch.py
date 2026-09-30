"""
Code-switching detection (§27).

Nigeria is multilingual and most real conversations mix languages. A customer
may write:

    "I understand the balance, but wallahi I need small time."

Treating that as "unknown" and asking which language they prefer is a poor
experience — the customer has already told us, implicitly, by writing the way
they actually speak.

This module is deliberately Django-free so it can be unit-tested without a
database. It performs *segment-level* scoring: the message is split into
clauses and each clause is attributed to a language, because code-switching
is a property of clauses, not of whole documents.

Two design rules keep this honest:

1. Loanwords are not evidence of a switch. "wallahi", "wahala", "abeg" and
   "oya" are shared Nigerian vocabulary that appear inside English text. A
   clause containing only loanwords must not outvote the surrounding English.
2. A switch requires *real* presence of the second language, not a single
   ambiguous token. Otherwise every English message with "japa" would be
   classified as Pidgin.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Sequence

# Clausal separators. Splitting on these lets us attribute language per clause.
# `?` and `!` are included because greeting + body is the common pattern
# ("Sannu, ina san cikin sa'adatu? / Zan biya gobe.").
_SPLIT_RE = r"[,;:.!?\n]|\bbut\b|\bhowever\b|\bthough\b|\balthough\b|\band then\b|\bplus\b"

# Neutral shared vocabulary: appears in both Nigerian English and Pidgin and
# therefore discriminates nothing. These must never make a clause look like a
# second language.
LOANWORDS = frozenset({
    "small", "small-small", "kama", "plenty", "later", "soon", "now",
    "money", "customer", "balance", "invoice", "payment", "pay", "paid",
    "thanks", "sorry", "please", "hello", "ok", "okay", "time", "need",
    "understand", "link", "send", "friday", "tomorrow", "today",
})

# Unambiguous register markers. Unlike loanwords these *are* the signal: a
# clause containing one of these is genuinely in Nigerian Pidgin register even
# if the clause is a single word ("Abeg."). They are deliberately NOT treated
# as noise — "wallahi" and "abeg" are what make a message Nigerian rather than
# British English, and §27 requires us to notice exactly that.
STRONG_MARKERS = frozenset({
    "wallahi", "wahala", "wahalah", "abeg", "abegabeg", "oya", "japa", "jide",
    "gidi", "correct", "sharp", "sharp-sharp", "naija", "naijer",
    "na wetin", "dey", "don", "fit", "get", "wetin", "abeg boss",
})

# A secondary language must reach this score within a single clause to be
# considered genuinely present (as opposed to a borrowed word).
_SEGMENT_PRESENCE_THRESHOLD = 2

# And it must reach this fraction of the primary language's total to count as
# a code-switch rather than incidental vocabulary.
_SWITCH_RATIO = 0.34

HIGH = Decimal("0.95")
MEDIUM = Decimal("0.80")
LOW = Decimal("0.62")
UNCERTAIN = Decimal("0.40")


@dataclass(frozen=True)
class Segment:
    """One attributed clause of the original message."""
    text: str
    language: str
    score: int


@dataclass
class CodeSwitchResult:
    primary: str
    secondary: Optional[str] = None
    confidence: Decimal = UNCERTAIN
    is_code_switched: bool = False
    segments: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "confidence": float(self.confidence),
            "is_code_switched": self.is_code_switched,
            "segments": [
                {"text": s.text, "language": s.language, "score": s.score}
                for s in self.segments
            ],
        }


def split_segments(text: str) -> list[str]:
    """Split a message into clause-sized segments."""
    import re
    if not text or not text.strip():
        return []
    parts = re.split(_SPLIT_RE, text, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p and p.strip()]


def _tokens(text: str) -> list[str]:
    import re
    return re.findall(r"[\w']+", (text or "").lower(), flags=re.UNICODE)


def _score_segment(segment: str, keyword_map: dict) -> dict:
    """
    Score one segment against every language in `keyword_map`.

    Returns {code: score}. Matching is word-boundary aware so that "biya"
    does not match inside an unrelated longer token, and multi-word keywords
    ("i go pay") are matched as phrases within the segment.
    """
    import re
    low = (segment or "").lower()
    padded = f" {low} "
    scores: dict = {}
    for code, keywords in keyword_map.items():
        total = 0
        for kw in keywords:
            k = kw.lower().strip()
            if not k:
                continue
            if " " in k:
                # phrase match, e.g. "i go pay"
                if k in low:
                    total += 2
            else:
                # word-boundary match, tolerant of leading/trailing spaces
                # that appear in the source keyword lists
                pattern = r"(?<!\w)" + re.escape(k) + r"(?!\w)"
                if re.search(pattern, low):
                    total += 1
        scores[code] = total
    return scores


def _strip_loanword_evidence(segment: str, scores: dict) -> None:
    """
    Discount a language whose only evidence in this segment is neutral
    vocabulary.

    Prevents "I will pay on Friday" from registering any Pidgin presence just
    because "pay" and "friday" are shared words.
    """
    toks = set(_tokens(segment))
    if not toks:
        return
    # A clause whose entire vocabulary is neutral carries no discriminating
    # evidence for any language.
    if toks.issubset(LOANWORDS):
        for code in list(scores):
            if code != "en":
                scores[code] = 0


def _has_strong_marker(segment: str) -> bool:
    """True when the clause contains an unambiguous Nigerian register marker."""
    low = (segment or "").lower()
    toks = set(_tokens(segment))
    if toks & STRONG_MARKERS:
        return True
    for marker in STRONG_MARKERS:
        if " " in marker and marker in low:
            return True
    return False


def detect_code_switch(
    text: str,
    keyword_map: dict,
    default_language: str = "en",
) -> CodeSwitchResult:
    """
    Attribute each clause of `text` to a language and report the dominant one.

    `keyword_map` maps language code -> list of keywords. Passing it in (rather
    than importing it) keeps this module free of circular imports and lets the
    router supply a richer, registry-driven map.

    Returns a CodeSwitchResult. `confidence` reflects how decisively the
    primary language won, so the caller can apply its own escalation policy.
    """
    segments = split_segments(text)
    if not segments:
        return CodeSwitchResult(primary=default_language, confidence=UNCERTAIN)

    totals: dict = {}
    attributed: list = []

    for seg in segments:
        scores = _score_segment(seg, keyword_map)
        _strip_loanword_evidence(seg, scores)
        if not any(scores.values()):
            # Neutral clause (e.g. "ok", "yes") — inherits the default and
            # contributes no evidence either way.
            attributed.append(Segment(text=seg, language=default_language, score=0))
            continue
        best = max(scores, key=lambda k: scores[k])
        attributed.append(Segment(text=seg, language=best, score=scores[best]))
        totals[best] = totals.get(best, 0) + scores[best]

    if not totals:
        return CodeSwitchResult(
            primary=default_language, confidence=UNCERTAIN, segments=attributed
        )

    primary = max(totals, key=lambda k: totals[k])
    primary_total = totals[primary]
    ranked = sorted(totals.values(), reverse=True)
    secondary_total = ranked[1] if len(ranked) > 1 else 0
    secondary = next((c for c, v in totals.items() if v == secondary_total and c != primary), None)

    # A clause must contain real evidence of the second language before we
    # call this a code switch. A strong register marker ("abeg", "wallahi")
    # counts on its own; otherwise the clause needs corroborating tokens.
    has_real_presence = False
    if secondary:
        for s in attributed:
            if s.language != secondary:
                continue
            if s.score >= _SEGMENT_PRESENCE_THRESHOLD or _has_strong_marker(s.text):
                has_real_presence = True
                break

    ratio = (secondary_total / primary_total) if primary_total else 0.0

    # Two independent routes to "this is a code switch":
    #
    #  1. A deliberate register marker ("Abeg.", "wallahi") in a clause written
    #     in another language. Someone who consciously reaches for a dialect
    #     particle has told us how they speak; proportion does not matter.
    #  2. Sustained presence of a second language across the message, measured
    #     by ratio. This catches unmarked switching such as
    #     "I will pay. Mo san pe mo ni gbese."
    #
    # Route 2 alone would miss a single-word switch; route 1 alone would fire
    # on any incidental marker in a long message.
    marker_switch = bool(secondary) and has_real_presence and any(
        s.language == secondary and _has_strong_marker(s.text) for s in attributed
    )
    ratio_switch = (
        bool(secondary)
        and has_real_presence
        and ratio >= _SWITCH_RATIO
    )
    is_switched = marker_switch or ratio_switch

    # Confidence: dominant and uncontested is high; a genuine second language
    # legitimately lowers it a little, because the reply may reasonably be in
    # either language.
    if primary_total >= 4 and not is_switched:
        confidence = HIGH
    elif primary_total >= 3:
        confidence = MEDIUM if not is_switched else LOW
    elif primary_total >= 2:
        confidence = MEDIUM if not is_switched else LOW
    else:
        confidence = UNCERTAIN

    return CodeSwitchResult(
        primary=primary,
        secondary=secondary if is_switched else None,
        confidence=confidence,
        is_code_switched=is_switched,
        segments=attributed,
    )
