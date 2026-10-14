"""The list of all features. Other code asks the registry instead of naming features itself."""

from riskdetect.features.definition import Feature
from riskdetect.features.families import FEATURES

_BY_NAME: dict[str, Feature] = {feature.name: feature for feature in FEATURES}
if len(_BY_NAME) != len(FEATURES):
    raise RuntimeError("feature names must be unique")


def all_features() -> tuple[Feature, ...]:
    return FEATURES


def get_feature(name: str) -> Feature:
    try:
        return _BY_NAME[name]
    except KeyError as exc:
        raise KeyError(f"unknown feature {name!r}") from exc


def feature_names() -> list[str]:
    return [feature.name for feature in FEATURES]
