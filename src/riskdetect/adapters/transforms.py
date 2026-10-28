"""Small, pure helpers used while translating raw records into Events.

Raw text enters these functions and leaves only as fingerprints and counts.
Nothing here stores or returns the text itself.
"""

import hashlib
import hmac
import re
from datetime import UTC, datetime, tzinfo
from itertools import pairwise

from riskdetect.schema import normalize_domain

# Epoch values at or above this are treated as milliseconds (seconds would be year 5000+).
_EPOCH_MS_THRESHOLD = 100_000_000_000
_DIGITS_RE = re.compile(r"^-?\d+(\.\d+)?$")
_WORD_RE = re.compile(r"\w+")
_MENTION_RE = re.compile(r"(?<![\w@])@\w+")

# Explicit URLs (scheme or www.), or bare domains that end in a common TLD.
# The bare form needs a known TLD so that "file.txt" or "e.g." are not taken as links,
# and the lookbehind skips e-mail addresses ("me@gmail.com" is not a link).
_BARE_TLDS = (
    "com|net|org|io|ly|co|me|xyz|info|biz|in|uk|de|ru|cn|tk|top|app|dev|gg|to|"
    "link|shop|store|site|online|club|live"
)
_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+"
    r"|(?<![@\w.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:"
    + _BARE_TLDS
    + r")\b(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)


def parse_time(value: object, default_tz: tzinfo = UTC) -> datetime:
    """Parse a timestamp from common raw forms into an aware UTC datetime.

    Accepts datetimes, ISO 8601 strings, and Unix epoch numbers (seconds or
    milliseconds, as numbers or digit strings). Values without a timezone are
    interpreted in ``default_tz``, the platform's configured source timezone.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, bool):
        raise ValueError("boolean is not a timestamp")
    elif isinstance(value, int | float):
        parsed = _from_epoch(float(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("empty timestamp")
        parsed = (
            _from_epoch(float(text)) if _DIGITS_RE.match(text) else datetime.fromisoformat(text)
        )
    elif value is None:
        raise ValueError("missing timestamp")
    else:
        raise ValueError(f"unsupported timestamp type: {type(value).__name__}")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed.astimezone(UTC)


def _from_epoch(number: float) -> datetime:
    seconds = number / 1000 if abs(number) >= _EPOCH_MS_THRESHOLD else number
    return datetime.fromtimestamp(seconds, tz=UTC)


def normalize_text(text: str) -> str:
    """Case-fold and collapse whitespace, so trivial variations hash the same."""
    return " ".join(text.casefold().split())


def hash_text(text: str) -> str | None:
    """Exact-match fingerprint (SHA-256 hex) of normalized text; None for empty text."""
    normalized = normalize_text(text)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def simhash_text(text: str) -> int | None:
    """64-bit near-duplicate fingerprint; similar texts give values a few bits apart.

    Uses words and word pairs as features. Compare two values with ``hamming_distance``.
    """
    tokens = _WORD_RE.findall(text.casefold())
    if not tokens:
        return None
    features = tokens + [f"{a} {b}" for a, b in pairwise(tokens)]
    bit_strings = [
        format(int.from_bytes(hashlib.blake2b(f.encode("utf-8"), digest_size=8).digest()), "064b")
        for f in features
    ]
    # Column-wise vote: a bit is set when most features have it set.
    half = len(bit_strings) / 2
    result = 0
    for column in zip(*bit_strings, strict=True):
        result = (result << 1) | (column.count("1") > half)
    return result


def hamming_distance(a: int, b: int) -> int:
    """Number of differing bits between two simhash values."""
    return (a ^ b).bit_count()


def extract_domains(value: object) -> tuple[str, ...]:
    """Find link domains in free text, or normalize an explicit list of URLs.

    Returns unique domains in first-seen order. Invalid candidates are skipped.
    Links are never visited.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        candidates: list[str] = _URL_RE.findall(value)
    elif isinstance(value, list | tuple):
        candidates = [str(item) for item in value if item is not None]
    else:
        candidates = [str(value)]

    domains: dict[str, None] = {}
    for candidate in candidates:
        try:
            domains[normalize_domain(candidate)] = None
        except ValueError:
            continue
    return tuple(domains)


def drop_own_domains(domains: tuple[str, ...], own: tuple[str, ...]) -> tuple[str, ...]:
    """Remove links to the platform's own sites (and their subdomains): that is navigation."""
    if not own:
        return domains
    return tuple(d for d in domains if not any(d == o or d.endswith("." + o) for o in own))


def count_mentions(text: str) -> int:
    """Count @mentions, ignoring e-mail addresses."""
    return len(_MENTION_RE.findall(text))


def pseudonymize_id(value: str, salt: str) -> str:
    """Stable anonymous ID: the same input and salt always give the same output."""
    digest = hmac.new(salt.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"p_{digest[:24]}"
