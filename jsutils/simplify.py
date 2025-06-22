# TODO
# oneOf [ { "enum": [] }, { "const": } ]
from typing import Any
import copy
from .utils import JsonSchema, log, JSUError
from .recurse import recurseSchema
from .inline import mergeProperty

# type-specific properties
# TODO complete
TYPED_PROPS: dict[str, set[str]] = {
    # format: not in theory, quite often in practice
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
# NOTE some extensions use other formats, eg for "int32" for numbers
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
                assert isinstance(s["enum"], list)
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


_IGNORABLE = (
    # core
    "$schema", "$id", "$comment", "$vocabulary", "$anchor", "$dynamicAnchor",
    # metadata
    "description", "title", "readOnly", "writeOnly", "default", "examples", "deprecated",
)

def _ignored(schema: JsonSchema) -> JsonSchema:
    """Remove preperties dans do not need to be considered."""
    if isinstance(schema, bool):
        return schema
    schema = copy.deepcopy(schema)
    for keyword in _IGNORABLE:
        if keyword in schema:
            del schema[keyword]
    return schema

def same(s1: JsonSchema, s2: JsonSchema) -> bool:
    return _ignored(s1) == _ignored(s2)

def simplifySchema(schema: JsonSchema, url: str):
    """Simplify a JSON Schema with various rules."""

    def rwtSimpler(schema: JsonSchema, path: list[str]) -> JsonSchema:

        lpath = ".".join(path) if path else "."

        if isinstance(schema, bool):
            return schema
        assert isinstance(schema, dict)

        # TODO anyOf/oneOf/allOf of length 0?

        # anyOf/oneOf/allOf of length 1
        for prop in ("anyOf", "oneOf", "allOf"):
            if (isinstance(schema, dict) and prop in schema and
                    len(schema[prop]) == 1):  # type: ignore
                try:
                    nschema = copy.deepcopy(schema)
                    sub = schema[prop][0]  # pyright: ignore
                    for p, v in sub.items():  # pyright: ignore
                        nschema = mergeProperty(nschema, p, v)
                    # success!
                    schema = nschema
                    if isinstance(schema, dict):
                        del schema[prop]
                except JSUError as e:
                    log.debug(e)
                    log.warning(f"{prop} of one merge failed")

        if isinstance(schema, bool):
            return schema
        assert isinstance(schema, dict)

        # TODO detect inconsistent allOf?

        # switch oneOf/anyOf const/enum to enum/const
        for prop in ("oneOf", "anyOf"):
            if prop in schema:
                val = schema[prop]
                assert isinstance(val, list)
                lv = getEnum(val, prop == "oneOf")  # pyright: ignore
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
                            assert isinstance(lev, list)
                            # intersect in initial order
                            nlv = []
                            for v in lev:
                                if v in lv:
                                    nlv.append(v)
                            schema["enum"] = nlv
                        else:
                            schema["enum"] = lv

        # short type list
        if "type" in schema and isinstance(schema["type"], list):
            types = schema["type"]
            if len(types) == 0:
                return False
            elif len(types) == 1:
                schema["type"] = types[0]
        # type/props…
        if "type" in schema and isinstance(schema["type"], str):
            stype = schema["type"]
            if stype == "number":
                if "multipleOf" in schema and schema["multipleOf"] == 1:
                    schema["type"] = "integer"
                    del schema["multipleOf"]
            if stype == "integer":
                if "multipleOf" in schema and schema["multipleOf"] == 1:
                    del schema["multipleOf"]
                # use this for later type-related checks
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
            # simplify any array
            if stype == "array":
                simpler = _ignored(schema)
                assert isinstance(simpler, dict)  # pyright hint
                if len(simpler) == 2 and "type" in schema:
                    # lone keyword
                    for kw in ("items", "additionalItems", "unevaluatedItems"):
                        if kw in schema:
                            subschema = _ignored(schema[kw])  # pyright: ignore
                            if subschema in (True, {}):
                                log.info(f"removing useless {kw} keyword at {lpath}")
                                del schema[kw]
            # simplify any object
            if stype == "object":
                simpler = _ignored(schema)
                assert isinstance(simpler, dict)  # pyright hint
                if len(simpler) == 2 and "type" in schema:
                    # lone keyword
                    for kw in ("additionalProperties", "unevaluatedProperties"):
                        if kw in schema:
                            subschema = _ignored(schema[kw])  # pyright: ignore
                            if subschema in (True, subschema):
                                log.info(f"removing useless {kw} keyword at {lpath}")
                                del schema[kw]

        # const/enum
        if "const" in schema and "enum" in schema:
            log.info(f"const/enum at {lpath}")
            assert isinstance(schema["enum"], list)
            if schema["const"] in schema["enum"]:
                del schema["enum"]
            else:
                return False
        elif "enum" in schema:
            assert isinstance(schema["enum"], list)
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
