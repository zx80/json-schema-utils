from typing import Any
import json
from .utils import JsonSchema, JSUError
from .schemas import Schemas
from urllib.parse import urlsplit

def mergeProperty(schema: JsonSchema, prop: str, value: Any) -> JsonSchema:
    """Merge an additional property into en existing schema.

    Note: this is in a best effort basis.
    """
    # handle boolean schema
    if isinstance(schema, bool):
        return { prop: value } if schema else False
    # then object
    if prop in ("$defs"):  # ignore
        pass
    elif prop == "enum":
        if prop in schema:
            # intersect in order
            vals = []
            for v in schema[prop]:
                if v in value:
                    vals.append(v)
            schema[prop] = vals
        else:
            schema[prop] = value
    elif prop == "const":
        if prop in schema:
            if schema[prop] == value:
                pass
            else:
                schema = False
        elif "enum" in schema:
            schema[prop] = value
            if value in schema["enum"]:
                del schema["enum"]
            else:
                schema = False
        else:
            schema[prop] = value
    elif prop == "required":
        if prop in schema:
            # append in order and without duplicates
            for p in value:
                if p not in schema["required"]:
                    schema["required"].append(p)
        else:
            schema["required"] = value
    elif prop == "properties":
        if prop in schema:
            props = schema[prop]
            assert isinstance(value, dict) and isinstance(props, dict)
            for p, s in value.items():
                if p in props:
                    if props[p] == s or s == True:
                        pass
                    else:
                        props[p] = { "allOf": [ props[p], s ] }
                else:
                    props[p] = s
        else:
            schema[prop] = value
    elif prop in ("allOf", "anyOf", "oneOf"):
        if prop in schema:
            schema[prop].extend(value)
        else:
            schema[prop] = value
    elif prop in ("title", "$comment"):
        # best effort
        if prop not in schema:
            schema[prop] = value
    elif prop in ("type", "$ref", "pattern", "additionalProperties", "minLength", "maxLength", "minimum", "maximum"):
        # allow identical values only
        if prop in schema:
            assert schema[prop] == value
        else:
            schema[prop] = value
    else:
        raise JSUError(f"merging of prop {prop} is not supported (yet)")
    return schema

def mergeSchemas(schema: JsonSchema, refschema: JsonSchema) -> JsonSchema:
    if isinstance(refschema, bool):
        return schema if refschema else False
    assert isinstance(refschema, dict)
    for p, v in refschema.items():
        schema = mergeProperty(schema, p, v)
    return schema

def _url(ref):
    u = urlsplit(ref)
    return u.scheme + "://" + u.netloc

def inlineRefs(schema: JsonSchema, url: str, schemas: Schemas) -> JsonSchema:
    """Recursively inline $ref in schema, which is modified."""
    if isinstance(schema, bool):
        return schema
    assert isinstance(schema, dict)
    # RECURSE depending on schema properties
    # list of schemas
    for prop in ("allOf", "oneOf", "anyOf"):
        if prop in schema:
            subs = schema[prop]
            assert isinstance(subs, list)
            schema[prop] = [ inlineRefs(s, url, schemas) for s in subs ]
    # values are schemas
    for prop in ("properties", "$defs"):
        if prop in schema:
            props = schema[prop]
            assert isinstance(props, dict)
            for p, s in props.items():
                props[p] = inlineRefs(s, url, schemas)
    # direct schemas
    for prop in ("additionalProperties", "unevaluatedProperties", "items"):
        if prop in schema:
            schema[prop] = inlineRefs(schema[prop], url, schemas)
    # SUBSTITUTE a ref
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        sub = schemas.schema(url, ref)
        del schema["$ref"]
        if isinstance(sub, dict):
            # FIXME misplaced
            sub = inlineRefs(sub, _url(ref), schemas)
            schema = mergeSchemas(schema, sub)
        else:
            assert isinstance(sub, bool)
            if not sub:
                schema = False
            # else True is coldly ignored
    return schema
