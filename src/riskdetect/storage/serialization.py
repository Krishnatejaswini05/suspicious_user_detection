"""Convert Events to flat table rows and back.

Nested blocks (target, content, interaction, moderation) become prefixed columns,
so later feature queries can read plain columns such as ``text_hash`` or
``target_owner_id`` directly with SQL, without unpacking nested structures.
"""

import json
from typing import Any

from riskdetect.schema import Event
from riskdetect.storage.parquet import TIMESTAMPTZ

# Column name -> DuckDB type, in file order.
EVENT_SCHEMA: dict[str, str] = {
    "event_id": "VARCHAR",
    "schema_version": "SMALLINT",
    "platform": "VARCHAR",
    "actor_id": "VARCHAR",
    "event_type": "VARCHAR",
    "occurred_at": TIMESTAMPTZ,
    "ingested_at": TIMESTAMPTZ,
    "space_id": "VARCHAR",
    "target_type": "VARCHAR",
    "target_id": "VARCHAR",
    "target_owner_id": "VARCHAR",
    "content_kind": "VARCHAR",
    "visibility": "VARCHAR",
    "text_hash": "VARCHAR",
    "simhash": "UBIGINT",
    "content_length": "INTEGER",
    "language": "VARCHAR",
    "url_domains": "VARCHAR[]",
    "mention_count": "INTEGER",
    "offsite_contact": "BOOLEAN",
    "risky_payment": "BOOLEAN",
    "price": "DOUBLE",
    "interaction_kind": "VARCHAR",
    "interaction_value": "DOUBLE",
    "moderation_action": "VARCHAR",
    "moderation_source": "VARCHAR",
    "moderation_reason": "VARCHAR",
    "attributes": "VARCHAR",  # JSON text; platform extras are never queried by core logic
}
EVENT_COLUMNS = tuple(EVENT_SCHEMA)


def event_to_row(event: Event) -> dict[str, Any]:
    target, content = event.target, event.content
    interaction, moderation = event.interaction, event.moderation
    return {
        "event_id": event.event_id,
        "schema_version": event.schema_version,
        "platform": event.platform,
        "actor_id": event.actor_id,
        "event_type": str(event.event_type),
        "occurred_at": event.occurred_at,
        "ingested_at": event.ingested_at,
        "space_id": event.space_id,
        "target_type": str(target.type) if target else None,
        "target_id": target.id if target else None,
        "target_owner_id": target.owner_actor_id if target else None,
        "content_kind": str(content.kind) if content else None,
        "visibility": str(content.visibility) if content else None,
        "text_hash": content.text_hash if content else None,
        "simhash": content.simhash if content else None,
        "content_length": content.length if content else None,
        "language": content.language if content else None,
        "url_domains": list(content.url_domains) if content else None,
        "mention_count": content.mention_count if content else None,
        "offsite_contact": content.offsite_contact if content else None,
        "risky_payment": content.risky_payment if content else None,
        "price": content.price if content else None,
        "interaction_kind": str(interaction.kind) if interaction else None,
        "interaction_value": interaction.value if interaction else None,
        "moderation_action": str(moderation.action) if moderation else None,
        "moderation_source": str(moderation.source) if moderation else None,
        "moderation_reason": moderation.reason_category if moderation else None,
        "attributes": json.dumps(event.attributes, sort_keys=True) if event.attributes else None,
    }


def row_to_event(row: dict[str, Any]) -> Event:
    data: dict[str, Any] = {
        "event_id": row["event_id"],
        "schema_version": row["schema_version"],
        "platform": row["platform"],
        "actor_id": row["actor_id"],
        "event_type": row["event_type"],
        "occurred_at": row["occurred_at"],
        "ingested_at": row["ingested_at"],
        "space_id": row["space_id"],
        "attributes": json.loads(row["attributes"]) if row["attributes"] else {},
    }
    if row["target_type"] is not None:
        data["target"] = {
            "type": row["target_type"],
            "id": row["target_id"],
            "owner_actor_id": row["target_owner_id"],
        }
    if row["content_kind"] is not None:
        data["content"] = {
            "kind": row["content_kind"],
            "visibility": row["visibility"],
            "text_hash": row["text_hash"],
            "simhash": row["simhash"],
            "length": row["content_length"],
            "language": row["language"],
            "url_domains": row["url_domains"] or (),
            "mention_count": row["mention_count"] or 0,
            # Files written before these columns existed read them as unknown.
            "offsite_contact": row.get("offsite_contact"),
            "risky_payment": row.get("risky_payment"),
            "price": row.get("price"),
        }
    if row["interaction_kind"] is not None:
        data["interaction"] = {"kind": row["interaction_kind"], "value": row["interaction_value"]}
    if row["moderation_action"] is not None:
        data["moderation"] = {
            "action": row["moderation_action"],
            "source": row["moderation_source"],
            "reason_category": row["moderation_reason"],
        }
    return Event.model_validate(data)
