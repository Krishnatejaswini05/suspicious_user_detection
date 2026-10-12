"""Version of the canonical event format.

Bump SCHEMA_VERSION when the shape of Event/Actor/Space/Label changes in a way
that older readers would misinterpret, and keep older versions in
SUPPORTED_SCHEMA_VERSIONS for as long as stored data still uses them.
"""

SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})
