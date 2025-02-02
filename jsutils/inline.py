from typing import Any
import copy
from urllib.parse import urlsplit
import json

from .utils import JsonSchema, JSUError, log
from .schemas import Schemas
from .recurse import recurseSchema

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
            if len(vals) == 0:
                log.warning("incompatible enum makes schema unsatisfiable")
                schema = False
            else:
                schema[prop] = vals
        else:
            schema[prop] = value
    elif prop == "const":
        if prop in schema:
            if schema[prop] == value:
                pass
            else:
                log.warning("incompatible const makes schema unsatisfiable")
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
    # FIXME: else?
    elif prop in ("type", "$ref", "pattern", "additionalProperties",
                  "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"):
        # allow identical values only (for now)
        if prop in schema:
            if schema[prop] == value:
                pass
            else:
                raise JSUError(f"cannot merge prop {prop} distinct values")
        else:
            schema[prop] = value
    else:
        raise JSUError(f"merging of prop {prop} is not supported (yet)")

    return schema

# properties keept at the root while merging
_KEEP_PROPS = {"$schema", "$id", "$comment", "title", "$defs", "definitions", "oneOf", "anyOf", "allOf"}

def mergeSchemas(schema: JsonSchema, refschema: JsonSchema) -> JsonSchema:
    """Merge two schemas."""

    if isinstance(refschema, bool):
        return schema if refschema else False
    elif isinstance(schema, bool):
        return refschema if schema else False
    assert isinstance(schema, dict) and isinstance(refschema, dict)

    saved = schema
    schema = copy.deepcopy(schema)

    try:
        # best effort
        for p, v in refschema.items():
            schema = mergeProperty(schema, p, v)
    except JSUError as e:
        # backup merge with allOf
        log.warning(f"merge error: {e}")
        log.info("merging schemas with allOf")
        schema = saved
        separate = {}
        for p in list(schema.keys()):
            if p not in _KEEP_PROPS:
                separate[p] = schema[p]
                del schema[p]
        if "allOf" not in schema:
            schema["allOf"] = []
        if len(separate) > 0:
            schema["allOf"].append(separate)
        if len(refschema) > 0:
            schema["allOf"].append(refschema)

    return schema

def _url(ref):
    u = urlsplit(ref)
    return u.scheme + "://" + u.netloc

def inlineRefs(schema: JsonSchema, url: str, schemas: Schemas) -> JsonSchema:
    """Recursively inline $ref in schema, which is modified."""

    def replaceRef(schema: JsonSchema) -> JsonSchema:
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

    return recurseSchema(schema, url, replaceRef)
