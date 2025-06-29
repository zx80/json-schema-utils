from .utils import JsonSchema, log, FilterFun, RewriteFun


def _recurseSchema(
        schema: JsonSchema,
        url: str,
        path: list[str],
        flt: FilterFun,
        rwt: RewriteFun) -> JsonSchema:

    log.debug(f"recuring at {path}")

    # skip recursion
    if not flt(schema, path):
        return schema

    if isinstance(schema, bool):
        return rwt(schema, path)
    assert isinstance(schema, dict), f"schema must be a dict: {type(schema).__name__}"

    # list of schemas
    for prop in ("allOf", "oneOf", "anyOf", "prefixItems"):
        if prop in schema:
            subs = schema[prop]
            assert isinstance(subs, list)
            schema[prop] = [ _recurseSchema(s, url, path + [prop, str(i)], flt, rwt)  # type: ignore
                             for i, s in enumerate(subs) ]

    # direct schemas
    for prop in ("additionalProperties", "unevaluatedProperties", "items",
                 "not", "if", "then", "else", "contains", "propertyNames",
                 "unevaluatedItems"):
        if prop in schema:
            # handle old items ~ prefixItems
            if prop == "items" and isinstance(schema["items"], list):
                schema[prop] = [ _recurseSchema(s, url, path + [prop, str(i)], flt, rwt)
                    for i, s in enumerate(schema[prop]) ]  # type: ignore
            else:  # standard case
                schema[prop] = _recurseSchema(schema[prop],  # type: ignore
                                              url, path + [prop], flt, rwt)

    # handle values as schemas
    def recValue(schema, *propnames):
        for prop in propnames:
            if prop in schema:
                props = schema[prop]
                assert isinstance(props, dict)
                for p, s in list(props.items()):
                    props[p] = _recurseSchema(s, url, path + [prop, p], flt, rwt)

    recValue(schema, "properties", "dependentSchemas", "patternProperties")

    # apply rwt
    schema = rwt(schema, path)
    assert isinstance(schema, (bool, dict))

    # keep last?!
    if isinstance(schema, dict):
        recValue(schema, "$defs", "definitions")

    return schema


def recurseSchema(schema: JsonSchema, url: str,
                  flt: FilterFun = lambda s, p: True,
                  rwt: RewriteFun = lambda s, p: s) -> JsonSchema:
    """Generic recursion on a JSON Schema.

    :param schema: schema to consider.
    :param url: url of schema.
    :param flt: filter (top-down) function, whether to keep recursing.
    :param rwt: rewrite (bottom-up) function.
    """
    return _recurseSchema(schema, url, [], flt, rwt)


def hasDirectRef(schema, url):
    """Tell whether schema has a $ref."""

    some_ref: bool = False

    def fltHasRef(schema: JsonSchema, path: list[str]) -> bool:
        nonlocal some_ref
        if "$defs" not in path and isinstance(schema, dict) and "$ref" in schema:
            some_ref = True
        return not some_ref

    recurseSchema(schema, url, flt=fltHasRef)

    return some_ref
