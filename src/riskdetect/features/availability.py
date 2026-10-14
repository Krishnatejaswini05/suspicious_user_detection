"""Which features a platform can support, decided by what its data provides.

A platform without text gets no duplicate features; one without reports gets no
"reports received" feature. Unsupported features are reported as missing (None),
never as 0, so the model never mistakes "no data" for "clean behavior".
"""

from collections.abc import Iterable

from riskdetect.adapters import PlatformConfig
from riskdetect.features.definition import Feature
from riskdetect.features.registry import all_features
from riskdetect.schema import EventType

_FAMILY_OF_EVENT: dict[EventType, str] = {
    EventType.CONTENT_CREATED: "content",
    EventType.CONTENT_EDITED: "content",
    EventType.CONTENT_DELETED: "content",
    EventType.INTERACTION: "interactions",
    EventType.REPORT_FILED: "reports",
    EventType.MODERATION_ACTION: "moderation",
}


def fields_from_config(config: PlatformConfig) -> set[str]:
    """What a platform declares it provides: mapped columns plus the event families it maps.

    Uses the same names as the adapter's MappingReport.available_fields, so either source
    can drive feature selection.
    """
    fields = {name for name, column in config.fields.model_dump().items() if column}
    fields.discard("attributes")
    fields |= {
        _FAMILY_OF_EVENT[m.event_type]
        for m in config.event_types.values.values()
        if m.event_type in _FAMILY_OF_EVENT
    }
    return fields


def supported_features(
    available_fields: Iterable[str] | None, features: Iterable[Feature] | None = None
) -> list[Feature]:
    """Features whose requirements are met. ``None`` means "assume everything is available"."""
    candidates = list(features) if features is not None else list(all_features())
    if available_fields is None:
        return candidates
    available = set(available_fields)
    return [f for f in candidates if f.requires <= available]
