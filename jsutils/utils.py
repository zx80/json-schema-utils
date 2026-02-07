from typing import Callable
import logging
import sys

log = logging.getLogger("JSU")

# simplistic typing
type Jsonable = None|bool|int|float|str|list[Jsonable]|dict[str, Jsonable]
type JsonSchema = dict[str, Jsonable]|bool
# type JsonPath = tuple[str|int, ...]
type SchemaPathSegment = str|tuple[str, str]|tuple[str, int]
type SchemaPath = tuple[SchemaPathSegment, ...]
type FilterFun = Callable[[JsonSchema, SchemaPath], bool]
type RewriteFun = Callable[[JsonSchema, SchemaPath], JsonSchema]

# keywords specific to a type
TYPED_KEYWORDS: dict[str, list[str]] = {
    "number": ["minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"],
    "string": ["minLength", "maxLength", "pattern"],
    "array": ["minItems", "maxItems", "uniqueItems", "items", "prefixItems", "contains",
              "minContains", "maxContains"],
    "object": ["properties", "required", "additionalProperties", "minProperties", "maxProperties",
               "patternProperties", "propertyNames"],
}

KEYWORD_TYPE: dict[str, str] = {}

for k in TYPED_KEYWORDS.keys():
    for n in TYPED_KEYWORDS[k]:
        KEYWORD_TYPE[n] = k


class JSUError(BaseException):
    pass


def only(schema, *props):
    """Tell whether schema only contains these props."""
    assert isinstance(schema, dict)
    ok = set(schema.keys()).issubset(set(props))
    if not ok:
        ttype = schema.get("type", "<>")
        log.debug(f"BAD SCHEMA {ttype}: {list(schema.keys())} {props}")
    return ok

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
