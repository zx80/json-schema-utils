from typing import Any
import json
from .utils import JsonSchema, JSUError

def recurse(schema: JsonSchema, url: str, change: callable) -> JsonSchema:
    """Recurse on a schema."""
    if isinstance(schema, bool):
        return schema
    assert isinstance(schema, dict)
    for prop in ("allOf", "oneOf", "anyOf"):
        if prop in schema:
            subs = schema[prop]
            assert isinstance(subs, list)
            schema[prop] = [ recurse(s, url, change) for s in subs ]
    # values are schemas
    for prop in ("properties", "$defs"):
        if prop in schema:
            props = schema[prop]
            assert isinstance(props, dict)
            for p, s in props.items():
                props[p] = recurse(s, url, change)
    # direct schemas
    for prop in ("additionalProperties", "unevaluatedProperties", "items"):
        if prop in schema:
            schema[prop] = recurse(schema[prop], url, change)
    return change(schema)
