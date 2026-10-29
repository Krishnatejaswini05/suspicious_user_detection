from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from riskdetect.adapters.transforms import (
    count_mentions,
    drop_own_domains,
    extract_domains,
    hamming_distance,
    hash_text,
    mentions_offsite_contact,
    mentions_risky_payment,
    parse_price,
    parse_time,
    pseudonymize_id,
    simhash_text,
)

T0 = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
IST = ZoneInfo("Asia/Kolkata")


class TestParseTime:
    @pytest.mark.parametrize(
        "value",
        [
            "2026-10-02T10:00:00Z",
            "2026-10-02T15:30:00+05:30",
            "2026-10-02 10:00:00+00:00",
            T0,
            T0.timestamp(),  # epoch seconds
            int(T0.timestamp() * 1000),  # epoch milliseconds
            str(int(T0.timestamp())),  # epoch as text
        ],
    )
    def test_common_forms(self, value: object) -> None:
        assert parse_time(value) == T0

    def test_naive_value_uses_platform_timezone(self) -> None:
        assert parse_time("2026-10-02 15:30", IST) == T0
        assert parse_time(datetime(2026, 10, 2, 15, 30), IST) == T0

    def test_explicit_offset_wins_over_platform_timezone(self) -> None:
        assert parse_time("2026-10-02T10:00:00Z", IST) == T0

    def test_result_is_utc(self) -> None:
        ist_fixed = timezone(timedelta(hours=5, minutes=30))
        assert parse_time(datetime(2026, 10, 2, 15, 30, tzinfo=ist_fixed)).tzinfo is UTC

    @pytest.mark.parametrize("value", [None, "", "  ", "yesterday", True, [1]])
    def test_invalid(self, value: object) -> None:
        with pytest.raises(ValueError):
            parse_time(value)


class TestTextFingerprints:
    def test_hash_ignores_case_and_spacing(self) -> None:
        assert hash_text("Cheap  phones!") == hash_text("cheap phones!")
        assert hash_text("Cheap phones!") != hash_text("Cheap phones!!!x")

    def test_hash_is_hex_and_empty_is_none(self) -> None:
        digest = hash_text("hello")
        assert digest is not None
        assert len(digest) == 64
        assert hash_text("   ") is None

    def test_simhash_near_duplicates_are_close(self) -> None:
        base = "Cheap phones today only, visit our store for the best deals on new phones"
        near = "Cheap phones today only!! visit our store for the best deals on new phones"
        other = "Had a great time hiking in the mountains with friends this weekend"
        a, b, c = simhash_text(base), simhash_text(near), simhash_text(other)
        assert a is not None and b is not None and c is not None
        assert hamming_distance(a, b) <= 3
        assert hamming_distance(a, c) > 10

    def test_simhash_is_64_bit_and_deterministic(self) -> None:
        value = simhash_text("same text")
        assert value == simhash_text("same text")
        assert value is not None and 0 <= value < 2**64
        assert simhash_text("!!!") is None


class TestExtractDomains:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Cheap phones! visit bit.ly/deal", ("bit.ly",)),
            ("see https://www.Example.com/a and http://news.org", ("example.com", "news.org")),
            ("www.shop.xyz now, again WWW.SHOP.XYZ", ("shop.xyz",)),
            ("mail me at someone@gmail.com", ()),
            ("open file.txt or e.g. this", ()),
            ("no links here", ()),
        ],
    )
    def test_from_text(self, text: str, expected: tuple[str, ...]) -> None:
        assert extract_domains(text) == expected

    def test_from_list(self) -> None:
        assert extract_domains(["https://a.com/x", "A.COM", None, "not a url"]) == ("a.com",)

    def test_none(self) -> None:
        assert extract_domains(None) == ()


def test_count_mentions_ignores_emails() -> None:
    assert count_mentions("hi @ravi and @sita, mail x@y.com") == 2


def test_pseudonymize_is_stable_and_salted() -> None:
    assert pseudonymize_id("S42", "salt") == pseudonymize_id("S42", "salt")
    assert pseudonymize_id("S42", "salt") != pseudonymize_id("S42", "other")
    assert pseudonymize_id("S42", "salt").startswith("p_")


def test_own_domains_are_navigation_not_links() -> None:
    found = ("reddit.com", "old.reddit.com", "notreddit.com", "imgur.com")
    assert drop_own_domains(found, ("reddit.com",)) == ("notreddit.com", "imgur.com")
    assert drop_own_domains(found, ()) == found


class TestMarketplaceSigns:
    @pytest.mark.parametrize(
        "text",
        [
            "WhatsApp me at +1 555 123 4567",
            "call me 555-123-4567",
            "write to joe.smith@example.com",
            "Message me on Telegram",
        ],
    )
    def test_offsite_contact(self, text: str) -> None:
        assert mentions_offsite_contact(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Posted on 2008-11-12 at 10:00",
            "over 1,000,000 users",
            "nice bike, pick up downtown",
            "sent 1790087523 piconero at block 2409139048",  # amounts, not phone numbers
        ],
    )
    def test_not_offsite_contact(self, text: str) -> None:
        assert not mentions_offsite_contact(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Payment by Google Play gift card only",
            "I will send a cashier's check, refund the difference",
            "pay with Bitcoin",
            "Western Union please",
        ],
    )
    def test_risky_payment(self, text: str) -> None:
        assert mentions_risky_payment(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Cash on pickup, or card in person",
            "Bitcoin and other crypto prices moved again today",
            "How does Monero compare with Bitcoin privacy?",
            "The miner mines only XMC but not Monero, said the crypto wiki",
        ],
    )
    def test_talking_about_money_is_not_asking_for_it(self, text: str) -> None:
        assert not mentions_risky_payment(text)

    def test_prices(self) -> None:
        assert parse_price("$1,200") == 1200.0
        assert parse_price(99) == 99.0
        assert parse_price("free") is None
        assert parse_price(-3) is None
        assert parse_price(True) is None
