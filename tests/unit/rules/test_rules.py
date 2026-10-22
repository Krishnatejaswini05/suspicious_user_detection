from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml

from riskdetect.rules import (
    Comparison,
    Group,
    Rule,
    RulesError,
    RuleSet,
    evaluate,
    load_rules,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def rule_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "R900_test",
        "description": "test rule",
        "category": "spam",
        "score_floor": 0.6,
        "when": {"all": [{"feature": "duplicate_ratio_7d", "op": ">=", "value": 0.8}]},
        "reason": "{duplicate_ratio_7d:.0%} repeated",
    }
    data.update(overrides)
    return data


class TestConditions:
    def test_comparisons(self) -> None:
        assert Comparison(feature="x", op=">=", value=5).evaluate({"x": 5})
        assert not Comparison(feature="x", op=">", value=5).evaluate({"x": 5})
        assert Comparison(feature="x", op="<", value=0.3).evaluate({"x": 0.1})

    def test_unknown_never_triggers(self) -> None:
        # Even "x < 5" is false when x is unknown: missing data is never evidence.
        assert not Comparison(feature="x", op="<", value=5).evaluate({"x": None})
        assert not Comparison(feature="x", op="<", value=5).evaluate({})

    def test_all_and_any_nest(self) -> None:
        group = Group.model_validate(
            {
                "all": [
                    {"feature": "a", "op": ">", "value": 1},
                    {
                        "any": [
                            {"feature": "b", "op": ">", "value": 1},
                            {"feature": "c", "op": ">", "value": 1},
                        ]
                    },
                ]
            }
        )
        assert group.evaluate({"a": 2, "c": 2})
        assert not group.evaluate({"a": 2})
        assert group.features() == {"a", "b", "c"}

    @pytest.mark.parametrize("bad", [{}, {"all": []}, {"all": [], "any": []}])
    def test_group_must_have_one_non_empty_list(self, bad: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            Group.model_validate(bad)


class TestRuleValidation:
    def test_valid_rule(self) -> None:
        assert Rule.model_validate(rule_data()).strength == 0.6

    def test_unknown_feature_is_rejected(self) -> None:
        when = {"all": [{"feature": "duplicate_ratio_7dd", "op": ">=", "value": 0.8}]}
        with pytest.raises(ValueError, match="unknown features"):
            Rule.model_validate(rule_data(when=when))

    def test_percentile_columns_are_known(self) -> None:
        when = {"all": [{"feature": "posts_1h_pct", "op": ">=", "value": 99}]}
        Rule.model_validate(rule_data(when=when))

    def test_account_age_alone_is_rejected(self) -> None:
        when = {
            "all": [
                {"feature": "account_age_days", "op": "<", "value": 2},
                {"feature": "events_seen", "op": "<", "value": 5},
            ]
        }
        with pytest.raises(ValueError, match="must look at behavior"):
            Rule.model_validate(rule_data(when=when))

    @pytest.mark.parametrize(
        "change",
        [
            {"score_floor": None},  # needs a floor or a weight
            {"category": "clean"},
            {"id": "my rule"},
            {"mode": "sometimes"},
            {"score_floor": 1.5},
            {"surprise": 1},
        ],
    )
    def test_invalid_rules(self, change: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            Rule.model_validate(rule_data(**change))

    def test_rule_ids_must_be_unique(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            RuleSet.model_validate({"version": 1, "rules": [rule_data(), rule_data()]})


class TestRulesFile:
    def test_project_rules_file_is_valid(self) -> None:
        rules = load_rules(PROJECT_ROOT / "configs" / "rules.yaml")
        assert len(rules.rules) >= 5

    def test_errors_name_the_problem(self, tmp_path: Path) -> None:
        path = tmp_path / "rules.yaml"
        bad = rule_data(when={"all": [{"feature": "nope", "op": ">", "value": 1}]})
        path.write_text(yaml.safe_dump({"version": 1, "rules": [bad]}), encoding="utf-8")
        with pytest.raises(RulesError, match="unknown features"):
            load_rules(path)
        with pytest.raises(RulesError, match="not found"):
            load_rules(tmp_path / "missing.yaml")


def test_evaluate_reports_evidence_and_shadow_rules() -> None:
    rules = RuleSet.model_validate(
        {"version": 1, "rules": [rule_data(), rule_data(id="R901_shadow", mode="shadow")]}
    )
    hits = evaluate(rules, {"duplicate_ratio_7d": 0.9, "posts_7d": 10.0})
    assert [(h.rule.id, h.active) for h in hits] == [("R900_test", True), ("R901_shadow", False)]
    assert hits[0].evidence == {"duplicate_ratio_7d": 0.9}
    assert evaluate(rules, {"duplicate_ratio_7d": 0.1}) == []


class TestSelfPromotion:
    """R009, from real Reddit data: links to one site, never joining in."""

    PROMOTER: ClassVar[dict[str, float]] = {
        "posts_7d": 30.0,
        "link_ratio_7d": 1.0,
        "top_domain_share_7d": 1.0,
        "reply_share_7d": 0.0,
    }

    def fired(self, row: dict[str, Any]) -> list[str]:
        rules = load_rules(PROJECT_ROOT / "configs" / "rules.yaml")
        return [hit.rule.id for hit in evaluate(rules, row)]

    def test_a_one_site_promoter_is_caught(self) -> None:
        assert "R009_single_site_self_promotion" in self.fired(self.PROMOTER)

    def test_an_expert_who_also_replies_is_not(self) -> None:
        expert = {**self.PROMOTER, "reply_share_7d": 0.6}
        assert "R009_single_site_self_promotion" not in self.fired(expert)

    def test_unknown_reply_share_never_triggers(self) -> None:
        chat = {k: v for k, v in self.PROMOTER.items() if k != "reply_share_7d"}
        assert "R009_single_site_self_promotion" not in self.fired(chat)
