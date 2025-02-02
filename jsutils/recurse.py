from typing import Callable
from .utils import JsonSchema

FilterFun = Callable[[JsonSchema], bool]
RewriteFun = Callable[[JsonSchema], JsonSchema]


def recurseSchema(
        schema: JsonSchema,
        url: str,
        flt: FilterFun = lambda _: True,
        rwt: RewriteFun = lambda s: s) -> JsonSchema:
    """Generic recursion on a JSON Schema.

    :param schema: schema to consider.
    :param url: url of schema.
    :param flt: filter (top-down) function, whether to keep recursing.
    :param rwt: rewrite (bottom-up) function.
    """

    if not flt(schema):
        return schema

    if isinstance(schema, bool):
        return rwt(schema)
    assert isinstance(schema, dict)

    # list of schemas
    for prop in ("allOf", "oneOf", "anyOf", "prefixItems"):
        if prop in schema:
            subs = schema[prop]
            assert isinstance(subs, list)
            schema[prop] = [ recurseSchema(s, url, flt, rwt) for s in subs ]

    # object properties' values are schemas
    for prop in ("properties", "$defs", "definitions", "dependentSchemas",
                 "patternProperties"):
        if prop in schema:
            props = schema[prop]
            assert isinstance(props, dict)
            for p, s in props.items():
                props[p] = recurseSchema(s, url, flt, rwt)

    # direct schemas
    for prop in ("additionalProperties", "unevaluatedProperties", "items",
                 "not", "if", "then", "else", "contains", "propertyNames",
                 "unevaluatedItems"):
        if prop in schema:
            schema[prop] = recurseSchema(schema[prop], url, flt, rwt)

    # apply rwt
    return rwt(schema)
