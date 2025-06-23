from typing import Any
import copy
from urllib.parse import urlsplit

from .utils import JsonSchema, JSUError, log
from .schemas import Schemas
from .recurse import recurseSchema

# TODO fix recursion handling

def mergeProperty(schema: JsonSchema, prop: str, value: Any) -> JsonSchema:
    """Merge an additional property into en existing schema.

    Note: this is in a best effort basis, on failure a backup plan is required.
    """
    # handle boolean schema
    if isinstance(schema, bool):
        return { prop: value } if schema else False
    assert isinstance(schema, dict)  # pyright helper

    # log.debug(f"merging {prop} in {schema}")

    # then object
    if prop in ("$defs"):  # ignore
        pass
    elif prop == "enum":
        if prop in schema:
            # intersect in order
            vals = []
            for v in schema[prop]:  # pyright: ignore
                if v in value:
                    vals.append(v)
            if len(vals) == 0:
                log.warning("incompatible enum/enum makes schema unsatisfiable")
                schema = False
            else:
                schema[prop] = vals
        elif "const" in schema:
            if schema["const"] in value:
                pass
            else:
                log.warning("incompatible enum/const makes schema unsatisfiable")
                schema = False
        else:
            schema[prop] = value
    elif prop == "const":
        if prop in schema:
            if schema[prop] == value:
                pass
            else:
                log.warning("incompatible const/const makes schema unsatisfiable")
                schema = False
        elif "enum" in schema:
            schema[prop] = value
            if value in schema["enum"]:
                del schema["enum"]
            else:
                log.warning("incompatible const/enum makes schema unsatisfiable")
                schema = False
        else:
            schema[prop] = value
    elif prop == "required":
        assert isinstance(value, list)
        if prop in schema:
            # append in order and without duplicates
            for p in value:
                if p not in schema["required"]:
                    schema["required"].append(p)  # pyright: ignore
        else:
            schema["required"] = value
    elif prop == "properties":
        if prop in schema:
            props = schema[prop]
            assert isinstance(value, dict) and isinstance(props, dict)
            for p, s in value.items():
                if p in props:
                    if props[p] == s or s is True:
                        pass
                    else:
                        props[p] = { "allOf": [ props[p], s ] }
                else:
                    props[p] = s
        else:
            schema[prop] = value
    elif prop in ("allOf", "anyOf", "oneOf"):
        assert isinstance(value, list)
        if prop in schema:
            schema[prop].extend(value)  # pyright: ignore
        else:
            schema[prop] = value
    elif prop in ("title", "$comment"):
        # best effort
        if prop not in schema:
            schema[prop] = value
    # FIXME: what about "else"?
    # TODO extend list of supported validations?
    elif prop in ("type", "$ref", "pattern",
                  "additionalProperties", "additionalItems", "items",
                  "minLength", "maxLength", "minProperties", "maxProperties",
                  "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                  "minItems", "maxItems", "minContains", "maxContains", "multipleOf",
                  "uniqueItems"):
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

    # log.debug(f"result: {schema}")
    return schema


# properties keept at the root while merging
_KEEP_PROPS = {
    "$schema", "$id", "$comment", "title", "description", "examples",
    # containers
    "$defs", "oneOf", "anyOf", "allOf",
    # special cases
    "unevaluatedProperties", "unevaluatedItems",
    # older version compatibility?
    "definitions",
}


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

        # log.debug(f"merged: {schema}")

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
            schema["allOf"].append(separate)  # pyright: ignore
        if len(refschema) > 0:
            schema["allOf"].append(refschema)  # pyright: ignore

    return schema


def _url(ref):
    """Extract base URL from full reference."""
    u = urlsplit(ref)
    return u.scheme + "://" + u.netloc


def inlineRefs(schema: JsonSchema, url: str, schemas: Schemas) -> JsonSchema:
    """Recursively inline $ref in schema, which is modified."""

    def rwtRef(schema: JsonSchema, path: list[str]) -> JsonSchema:

        # recursion avoidance (FIXME insufficient)
        spath = "/".join(path)
        skips = {url + "#" + spath, url + "#/" + spath, url + "#./" + spath}

        while isinstance(schema, dict) and "$ref" in schema:
            ref = schema["$ref"]
            assert isinstance(ref, str)

            # (direct) recursion detection
            if ref in skips:
                log.info(f"skipping recursive ref: {ref}")
                break

            # actual substitution
            sub = schemas.schema(url, ref)
            del schema["$ref"]
            if isinstance(sub, dict):
                schema = mergeSchemas(schema, sub)
            else:
                assert isinstance(sub, bool)
                if not sub:
                    schema = False
                # else True is coldly ignored

        return schema

    return recurseSchema(schema, url, rwt=rwtRef)
