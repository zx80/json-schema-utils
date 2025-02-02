from typing import Any
import json
from .utils import JsonSchema, JSUError

def recurseSchema(schema: JsonSchema, url: str, change: callable) -> JsonSchema:
    """Recurse on a schema."""

    if isinstance(schema, bool):
        return schema

    assert isinstance(schema, dict)

    # list of schemas
    for prop in ("allOf", "oneOf", "anyOf", "prefixItems"):
        if prop in schema:
            subs = schema[prop]
            assert isinstance(subs, list)
            schema[prop] = [ recurseSchema(s, url, change) for s in subs ]

    # object properties' values are schemas
    for prop in ("properties", "$defs", "definitions", "dependentSchemas",
                 "patternProperties"):
        if prop in schema:
            props = schema[prop]
            assert isinstance(props, dict)
            for p, s in props.items():
                props[p] = recurseSchema(s, url, change)

    # direct schemas
    for prop in ("additionalProperties", "unevaluatedProperties", "items",
                  "not", "if", "then", "else", "contains", "propertyNames",
                  "unevaluatedItems"):
        if prop in schema:
            schema[prop] = recurseSchema(schema[prop], url, change)

    # apply change
    return change(schema)
