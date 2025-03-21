from typing import Any
import copy
from .utils import JsonSchema, log, JSUError
from .recurse import recurseSchema
from .inline import mergeProperty

# type-specific properties
# TODO complete
TYPED_PROPS: dict[str, set[str]] = {
    "string": {"minLength", "maxLength", "pattern"},
    "number": {"minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum", "multipleOf"},
    "object": {"additionalProperties", "unevaluatedProperties", "propertyNames", "required",
               "properties", "minProperties", "maxProperties", "patternProperties"},
    "array": {"items", "minItems", "maxItems", "prefixItems", "contains", "minContains",
              "maxContains", "unevaluatedItems", "additionalItems"},
    "boolean": set(),
    "null": set()
}


def incompatibleProps(st: str):
    props = set()
    [ props := props.union(p) for t, p in TYPED_PROPS.items() if t != st ]
    return props


# string-specific predefined formats
STRING_FORMATS: set[str] = {
    "date", "date-time", "time", "duration",
    "email", "idn-email",
    "hostname", "idn-hostname", "ipv4", "ipv6",
    "uri", "uri-reference", "uri-template",
    "iri", "iri-reference",
    "uuid",
    "json-pointer", "relative-json-pointer",
    "regex",
}


def counts(lv: list[Any]) -> dict[Any, int]:
    """Count values in list. Probably exists elsewhere."""
    cnt = {}
    for v in lv:
        cnt[v] = (cnt[v] + 1) if v in cnt else 1
    return cnt


def getEnum(ls: list[JsonSchema], is_one: bool) -> list[Any]|None:
    """Attempt to extract a list of constants."""
    assert isinstance(ls, list)
    lv = []
    for s in ls:
        if isinstance(s, dict):
            if "const" in s:
                lv.append(s["const"])
            elif "enum" in s:
                lv.extend(dict.fromkeys(s["enum"]))
            else:
                return None
        else:
            return None
    cnt = counts(lv)
    if is_one:
        # fully remove duplicates
        lv = list(filter(lambda i: cnt[i] == 1, lv))
    else:
        # only remove duplicates
        lv = list(dict.fromkeys(lv))
    return lv


def _typeCompat(t: str, v: Any) -> bool:
    """Check JSON type / value compatibility."""
    return ((t == "null" and v is None) or
            (t == "bool" and isinstance(v, bool)) or
            (t == "number" and isinstance(v, (int, float))) or
            (t == "string" and isinstance(v, str)) or
            (t == "array" and isinstance(v, (list, tuple))) or
            (t == "object" and isinstance(v, dict)))


def simplifySchema(schema: JsonSchema, url: str):
    """Simplify a JSON Schema with various rules."""

    def rwtSimpler(schema: JsonSchema, path: list[str]) -> JsonSchema:

        lpath = "/".join(path) if path else "."

        if isinstance(schema, bool):
            return schema
        assert isinstance(schema, dict)

        # anyOf/oneOf/allOf of length 1
        for prop in ("anyOf", "oneOf", "allOf"):
            if isinstance(schema, dict) and prop in schema and len(schema[prop]) == 1:
                try:
                    nschema = copy.deepcopy(schema)
                    sub = schema[prop][0]
                    for p, v in sub.items():
                        nschema = mergeProperty(nschema, p, v)
                    # success!
                    schema = nschema
                    if isinstance(schema, dict):
                        del schema[prop]
                except JSUError:
                    log.warning(f"{prop} of one merge failed")

        if isinstance(schema, bool):
            return schema
        assert isinstance(schema, dict)

        # switch oneOf/anyOf const/enum to enum/const
        for prop in ("oneOf", "anyOf"):
            if prop in schema:
                lv = getEnum(schema[prop], prop == "oneOf")
                if lv is not None:
                    del schema[prop]
                    log.info(f"{prop} to enum/const/false at {lpath}")
                    if len(lv) == 0:
                        # FIXME check
                        return False
                    else:  # at least one
                        if "enum" in schema:
                            lev = schema["enum"]
                            del schema["enum"]
                            # intersect in initial order
                            nlv = []
                            for v in lev:
                                if v in lv:
                                    nlv.append(v)
                            schema["enum"] = nlv
                        else:
                            schema["enum"] = lv

        # type/props…
        if "type" in schema and isinstance(schema["type"], str):
            stype = schema["type"]
            if stype == "integer":
                stype = "number"
            # remove type-specific properties
            if stype in TYPED_PROPS:
                for p in incompatibleProps(stype):
                    if p in schema:
                        log.info(f"unused property {p} for {stype} at {lpath}")
                        del schema[p]
            if stype != "string" and "format" in schema and schema["format"] in STRING_FORMATS:
                log.info(f"unused string format on {stype}: {schema['format']}")
                del schema["format"]
            # type/const
            if "const" in schema:
                cst = schema["const"]
                if _typeCompat(stype, cst):
                    log.info(f"removing redundant type with const at {lpath}")
                    del schema["type"]
                else:
                    log.info(f"incompatible type {stype} for {cst} at {lpath}")
                    return False
            # type/enum
            if "enum" in schema:
                vals = schema["enum"]
                assert isinstance(vals, list)
                nvals = list(filter(lambda v: _typeCompat(stype, v), vals))
                if len(vals) != len(nvals):
                    log.info(f"removing {len(vals) - len(nvals)} incompatible values "
                             f"from enum at {lpath}")
                    schema["enum"] = nvals
                del schema["type"]

        # const/enum
        if "const" in schema and "enum" in schema:
            log.info(f"const/enum at {lpath}")
            if schema["const"] in schema["enum"]:
                del schema["enum"]
            else:
                return False
        elif "enum" in schema:
            nenum = len(schema["enum"])
            if nenum == 0:
                log.info(f"empty enum at {lpath}")
                return False
            elif nenum == 1:
                log.info(f"enum of one at {lpath}")
                schema["const"] = schema["enum"][0]
                del schema["enum"]

        return schema

    return recurseSchema(schema, url, rwt=rwtSimpler)
