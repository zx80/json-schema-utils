from typing import Callable
from urllib.parse import quote, unquote
import logging
import sys
import re

log = logging.getLogger("JSU")

# simplistic typing
type Jsonable = None|bool|int|float|str|list[Jsonable]|dict[str, Jsonable]
type JsonSchema = dict[str, Jsonable]|bool
# type JsonPath = tuple[str|int, ...]
type SchemaPathSegment = str|tuple[str, str]|tuple[str, int]
type SchemaPath = tuple[SchemaPathSegment, ...]
type FilterFun = Callable[[JsonSchema, SchemaPath], bool]
type RewriteFun = Callable[[JsonSchema, SchemaPath], JsonSchema]

ALL_TYPES: set[str] = {"null", "boolean", "integer", "number", "string", "array", "object"}

# keywords specific to a type
TYPED_KEYWORDS: dict[str, list[str]] = {
    "number": ["minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"],
    "string": ["minLength", "maxLength", "pattern"],
    "array": ["minItems", "maxItems", "uniqueItems", "items", "prefixItems", "contains",
              "minContains", "maxContains", "additionalItems", "unevaluatedItems"],
    "object": ["properties", "required", "additionalProperties", "minProperties", "maxProperties",
               "patternProperties", "propertyNames", "unevaluatedProperties"],
}

KEYWORD_TYPE: dict[str, str] = {}

META_KEYS = [
    "title", "description", "default", "examples", "deprecated", "readOnly", "writeOnly", "id",
    "$schema", "$id", "$comment", "$dynamicAnchor", "$dynamicRef",
    # OLD?
    "context", "notes",
    # extensions and strange stuff?
    "markdownDescription", "deprecationMessage", "scope", "body", "example", "private",
]

IGNORE = META_KEYS + ["$defs", "definitions"]

for k in TYPED_KEYWORDS.keys():
    for n in TYPED_KEYWORDS[k]:
        KEYWORD_TYPE[n] = k


class JSUError(BaseException):
    pass


def only(schema, *props) -> bool:
    """Tell whether schema only contains these props."""
    assert isinstance(schema, dict)
    ok = set(schema.keys()).issubset(set(props))
    if not ok:
        ttype = schema.get("type", "<>")
        log.debug(f"BAD SCHEMA {ttype}: {list(schema.keys())} {props}")
    return ok

def used_props(schema, *props) -> set[str]:
    """Return occuring properties among props."""
    assert isinstance(schema, dict)
    return set(props) & schema.keys()


def has(schema, *props):
    """Tell whether schema has any of these props."""
    assert isinstance(schema, dict)
    for p in schema.keys():
        if p not in props:
            return False
    return True


def openfiles(args: list[str] = []):
    if not args:  # empty list is same as stdin
        args = ["-"]
    for fn in args:
        if fn == "-":
            yield fn, sys.stdin
        else:
            with open(fn) as fh:
                yield fn, fh

def encode_url(segment: str) -> str:
    """Encode path: why not rely simply on URL encoding?!"""
    return quote(segment.replace("~", "~0").replace("/", "~1"))

def decode_url(segment: str) -> str:
    """Decode strange url-and-more path."""
    if "~0" in segment or "~1" in segment or "%" in segment:
        return unquote(segment).replace("~1", "/").replace("~0", "~")
    else:
        return segment

def schemapath_to_urlpath(path: SchemaPath) -> str:
    """Encode a schema path as a url path."""
    return "/".join(encode_url(s) if isinstance(s, str) else
                    f"{encode_url(str(s[0]))}/{encode_url(str(s[1]))}"
                        for s in path)

_IS_ABS_URL = re.compile(r"((https?|file)://|urn:)").match

def is_abs_url(s: str) -> bool:
    return _IS_ABS_URL(s) is not None

def is_any(schema: JsonSchema) -> bool:
    if isinstance(schema, bool):
        return schema
    elif only(schema, "type", *IGNORE):
        if "type" in schema:
            types = schema["type"]
            return isinstance(types, list) and set(types) == ALL_TYPES
        else:
            return True
            
