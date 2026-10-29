"""Rule packs: rules grouped by kind of platform, chosen per platform."""

from datetime import datetime
from pathlib import Path

import pytest

from riskdetect.adapters import platform_rule_packs
from riskdetect.rules import RulesError, evaluate, load_rules
from riskdetect.scoring import Scorer, load_scoring_config

CONFIGS = Path(__file__).resolve().parents[3] / "configs"
PACKS = load_rules(CONFIGS / "rules")
CHEAP = {"cheap_listings_7d": 5.0}  # fires R014, a marketplace rule

RULE = """version: {version}
rules:
  - id: {rule_id}
    description: Test rule.
    category: spam
    weight: 0.3
    when: {{all: [{{feature: posts_7d, op: '>=', value: 1}}]}}
    reason: test
"""


def rule_file(folder: Path, name: str, rule_id: str, version: int = 1) -> None:
    text = RULE.format(version=version, rule_id=rule_id)
    (folder / f"{name}.yaml").write_text(text, encoding="utf-8")


def test_project_packs_are_named_after_their_files() -> None:
    assert set(PACKS.packs) == {"common", "social", "chat", "marketplace"}
    by_id = {rule.id: rule.pack for rule in PACKS.rules}
    assert by_id["R001_duplicate_burst"] == "common"
    assert by_id["R009_single_site_self_promotion"] == "social"
    assert by_id["R013_too_good_to_be_true"] == "marketplace"


def test_only_chosen_packs_apply() -> None:
    assert [h.rule.id for h in evaluate(PACKS, CHEAP)] == ["R014_cheap_listings"]
    assert evaluate(PACKS, CHEAP, packs={"common", "social"}) == []


def test_platform_files_choose_their_packs() -> None:
    packs = platform_rule_packs(CONFIGS / "platforms")
    assert packs["reddit"] == ("common", "social")
    assert "marketplace" in packs["synthetic_market"]


def test_scorer_applies_packs_per_platform() -> None:
    scorer = Scorer(
        PACKS,
        load_scoring_config(CONFIGS / "scoring.yaml"),
        platform_packs={"forum": ["common", "social"]},
    )
    base = {"actor_id": "u1", "as_of": datetime(2026, 1, 1), **CHEAP}
    assert scorer.score({**base, "platform": "forum"}).rules_fired == ()
    # A platform that chose no packs gets every pack.
    assert scorer.score({**base, "platform": "market"}).rules_fired == ("R014_cheap_listings",)
    assert scorer.with_models([]).platform_packs == scorer.platform_packs


def test_unknown_pack_names_are_an_error() -> None:
    config = load_scoring_config(CONFIGS / "scoring.yaml")
    with pytest.raises(ValueError, match="unknown rule packs"):
        Scorer(PACKS, config, platform_packs={"x": ["socail"]})


def test_rule_ids_must_be_unique_across_packs(tmp_path: Path) -> None:
    rule_file(tmp_path, "a", "R901_same")
    rule_file(tmp_path, "b", "R901_same")
    with pytest.raises(RulesError, match="unique"):
        load_rules(tmp_path)


def test_packs_must_share_one_version(tmp_path: Path) -> None:
    rule_file(tmp_path, "a", "R901_one")
    rule_file(tmp_path, "b", "R902_two", version=2)
    with pytest.raises(RulesError, match="different versions"):
        load_rules(tmp_path)


def test_an_empty_folder_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RulesError, match="No rule packs"):
        load_rules(tmp_path)
