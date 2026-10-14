"""Domain lists (e.g. known scam sites), kept as plain text so they can change without code."""

from pathlib import Path

from riskdetect.schema import normalize_domain

DEFAULT_BLOCKED_DOMAINS_PATH = Path("configs/lists/blocked_domains.txt")


def load_domain_list(path: Path) -> frozenset[str]:
    """Normalized domains from a text file; blank lines and # comments are ignored.

    A missing file means an empty list, so a deployment without a list still works.
    """
    if not path.exists():
        return frozenset()
    domains = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        try:
            domains.add(normalize_domain(entry))
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
    return frozenset(domains)
