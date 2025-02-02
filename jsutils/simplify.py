from typing import Any
from .utils import JsonSchema, log
from .recurse import recurseSchema

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


def getEnum(ls: list[JsonSchema]) -> list[Any]|None:
    assert isinstance(ls, list)
    lv = []
    for s in ls:
        if isinstance(s, dict):
            if "const" in s:
                lv.append(s["const"])
            elif "enum" in s:
                lv.extend(s["enum"])
            else:
                return None
        else:
            return None
    return lv


def simplifySchema(schema: JsonSchema, url: str):

    def rwtSimpler(schema: JsonSchema, path: list[str]) -> JsonSchema:

        lpath = "/".join(path) if path else "."

        if isinstance(schema, bool):
            return schema
        assert isinstance(schema, dict)

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

        # switch oneOf/anyOf const/enum to enum
        for prop in ("oneOf", "anyOf"):
            if prop in schema:
                lv = getEnum(schema[prop])
                # TODO remove duplicates on oneOf
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

        # TODO anyOf/oneOf/allOf of length 1

        if "const" in schema and "enum" in schema:
            log.info(f"const/enum at {lpath}")
            if schema["const"] in schema["enum"]:
                del schema["enum"]
            else:
                return False
        elif "enum" in schema and len(schema["enum"]) == 1:
            log.info(f"enum of one at {lpath}")
            schema["const"] = schema["enum"][0]
            del schema["enum"]

        return schema

    return recurseSchema(schema, url, rwt=rwtSimpler)
