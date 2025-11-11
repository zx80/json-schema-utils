from typing import Any
import re
import copy
import logging
from .utils import only
from urllib.parse import quote, unquote

type JsonPath = list[str|int]

log = logging.getLogger("convert")
# log.setLevel(logging.DEBUG)

def tname(v) -> str:
    return (
        "null" if v is None else
        "bool" if isinstance(v, bool) else
        "int"  if isinstance(v, int) else
        "number" if isinstance(v, float) else
        "string" if isinstance(v, str) else
        "array" if isinstance(v, list) else
        "object" if isinstance(v, dict) else
        "UNKNOWN"
    )

#
# BEST EFFORT SCHEMA TO MODEL CONVERSION
#

def toconst(val):
    match val:
        case None:
            return None  # or "=null"
        case bool():
            return "=true" if val else "=false"
        case int()|float():
            return "=" + str(val)
        case str():
            return "_" + val
        case list():
            # constant list…
            return {
                "@": [ toconst(v) for v in val ],
                "=": len(val)
            }
        case dict():
            return { f"_{p}": toconst(v) for p, v in val.items() }
        case _:
            raise Exception(f"unexpected value for a constant: {val}")


def esc(s):
    """Escape a string if necessary."""
    if isinstance(s, str) and (len(s) == 0 or s[0] in ("$", "?", "_", "!", "=", "^")):
        return "_" + s
    else:
        return s


def sesc(s):
    if not isinstance(s, str):
        return str(s)
    elif re.search(r"^\w+$", s):
        return s
    else:
        return '"' + s.replace('"', r'\"').replace("\n", r'\n') + '"'


def jpath(path: JsonPath):
    return "." + ".".join(sesc(s) for s in path)


def numberConstraints(schema):
    assert "type" in schema and schema["type"] in ("integer", "number")
    constraints = {}
    if "multipleOf" in schema:
        mo = schema["multipleOf"]
        assert type(mo) in (int, float)
        constraints[".mo"] = mo  # extension
        # assert False, "keyword multipleOf is not supported"
    if "minimum" in schema:
        mini = schema["minimum"]
        assert type(mini) in (int, float)
        constraints[">="] = mini
    if "maximum" in schema:
        maxi = schema["maximum"]
        assert type(maxi) in (int, float)
        constraints["<="] = maxi
    if "exclusiveMinimum" in schema:
        mini = schema["exclusiveMinimum"]
        assert type(mini) in (int, float)
        constraints[">"] = mini
    if "exclusiveMaximum" in schema:
        maxi = schema["exclusiveMaximum"]
        assert type(maxi) in (int, float)
        constraints["<"] = maxi
    return constraints


def buildModel(model, constraints: dict, defs: dict, sharp: dict, is_root: bool = False):
    """Build a model."""

    if constraints or sharp or defs:
        # we want to force a JSON object

        if constraints:
            m = {"@": model, **constraints}
        elif isinstance(model, dict):
            m = model
        else:
            m = {"@": model}

        if sharp and "description" in sharp:
            m["#"] = sharp["description"]
        if defs:
            m["$"] = defs
        if is_root and "#" not in m:
            m["#"] = "JSON Model generated from a JSON Schema with json-schema-utils"
        return m

    else:
        if is_root and isinstance(model, dict) and "#" not in model:
            model["#"] = "JSON Model generated from a JSON Schema with json-schema-utils"

        # we can simplify
        while isinstance(model, dict) and len(model) == 1 and "@" in model:
            model = model["@"]

        return model


META_KEYS = [
    "title", "description", "default", "examples", "deprecated", "readOnly", "writeOnly", "id",
    "$schema", "$id", "$comment", "$dynamicAnchor",
    # OLD?
    "context", "notes",
    # extensions and strange stuff?
    "markdownDescription", "deprecationMessage", "scope", "body", "example", "private",
]

IGNORE = META_KEYS + ["$defs", "definitions"]

# keywords specific to a type
SPLITS = {
    "number": ["minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"],
    "string": ["minLength", "maxLength", "pattern"],
    "array": ["minItems", "maxItems", "uniqueItems", "items", "prefixItems", "contains",
              "minContains", "maxContains"],
    "object": ["properties", "required", "additionalProperties", "minProperties", "maxProperties",
               "patternProperties", "propertyNames"],
}

SPLIT = {}
for k in SPLITS.keys():
    for n in SPLITS[k]:
        SPLIT[n] = k
# log.warning(f"SPLIT = {SPLIT}")


def split_schema(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assert isinstance(schema, dict) and "type" in schema
    types = schema["type"]
    assert isinstance(types, (list, tuple))
    # log.info(f"splitting on {types}")
    # per type
    schemas = {t: {"type": t} for t in types}
    schemas[""] = {}
    for prop, val in schema.items():
        if prop in IGNORE:
            schemas[""][prop] = val
        elif prop in META_KEYS or prop == "type":
            pass
        elif prop == "format":
            assert isinstance(val, str), "format is a string"
            if "string" in schemas:
                schemas["string"]["format"] = val
            elif "number" in schemas:
                schemas["number"]["format"] = val
            elif "integer" in schemas:
                schemas["integer"]["format"] = val
            else:
                assert False, f"cannot map format to {types}"
        elif prop == "enum":
            # DEAD CODE… enum does not need any check and is already before?
            assert isinstance(val, list), "enum is a list"
            for _, sh in schemas:
                sh["enum"] = []
            for v in val:
                if v is None and "null" in schemas:
                    # just drop the enum
                    del schemas["null"]["enum"]
                elif isinstance(v, bool) and "boolean" in schemas:
                    schemas["boolean"]["enum"].append(v)
                elif isinstance(v, int):
                    if "integer" in schemas:
                        schemas["integer"]["enum"].append(v)
                    if "number" in schemas:
                        schemas["number"]["enum"].append(float(v))
                elif isinstance(v, float):
                    if "number" in schemas:
                        schemas["number"]["enum"].append(v)
                    if "integer" in schemas and v - int(v) == 0.0:
                        schemas["integer"]["enum"].append(int(v))
                elif isinstance(v, str) and "string" in schemas:
                    schemas["string"]["enum"].append(v)
                elif isinstance(v, list) and "array" in schemas:
                    schemas["array"]["enum"].append(v)
                elif isinstance(v, dict) and "object" in schemas:
                    schemas["object"]["enum"].append(v)
                # else just ignore incompatible value…
        elif prop in SPLIT:
            assert SPLIT[prop] in types
            schemas[SPLIT[prop]][prop] = val
        else:
            assert False, f"cannot map {prop} to a type"
    # log.debug(f"splitted: {schemas}")
    return schemas


# identifiers
CURRENT_SCHEMA: str|None = None
SCHEMA = None
IDS: dict[str, dict[str, Any]] = {}
EXPLICIT_TYPE: bool = False


def reset():
    global CURRENT_SCHEMA, IDS, SCHEMA
    CURRENT_SCHEMA = None
    SCHEMA = None
    IDS = {}


_FMT2MODEL = {
    "password": "$STRING",  # OpenAPI
    "date": "$DATE",
    "date-time": "$DATETIME",
    "time": "$TIME",
    "duration": "$DURATION",
    "email": "$EMAIL",
    "idn-email": "$EMAIL",
    "hostname": "$HOSTNAME",
    "idn-hostname": "$HOSTNAME",
    "ipv4": "$IP4",
    "ipv6": "$IP6",
    "uri": "$URI",
    "iri": "$URI",
    "iri-reference": "$URI",
    "uri-reference": "$URI",
    "uri-template": "$URI",
    "uuid": "$UUID",
    "json-pointer": "$JSONPT",
    "relative-json-pointer": "$JSONPT",
    "regex": "$REGEX",
    # hmmm…
    "color": "$STRING",
    "phone": "$STRING",
}


def format2model(fmt: str):
    if fmt in _FMT2MODEL:
        return _FMT2MODEL[fmt]
    else:
        log.warning(f"unknow format: {fmt}")
        # return f"$UNKNOWN:{fmt}"
        return ""

def doubt(ok: bool, msg: str, strict: bool):
    if not ok:
        if strict:
            assert False, msg
        else:
            log.warning(msg)

def allOfLayer(schema: dict, operator: str):
    # log.warning(f"ao {operator} in: {schema}")
    schemas = copy.deepcopy(schema[operator])
    del schema[operator]
    # extract ignoreables
    nschema = {}
    for k, v in list(schema.items()):
        if k in IGNORE:
            nschema[k] = v
            del schema[k]
    # forward type just in case for *Of
    if "type" in schema and isinstance(schema["type"], str) and isinstance(schemas, list):
        t = schema["type"]
        for s in schemas:
            if isinstance(s, dict) and "type" not in s:
                s["type"] = t
    nschema["allOf"] = [{operator: schemas}, schema]
    return nschema

# (STRANGE) PATTERNS
# manually simplify some patterns for re2 compatibility
# TODO implement some automatic simplifications?
PATTERN: dict[str, str] = {
    # cspell
    "^(?=[^!*,;{}[\\]~\\n]+$)(?=(.*\\w)).+$": "^[^!*,;{}[\\]~\\n]*\\w[^!*,;{}[\\]~\\n]*$",
    "^(?=!+[^!*,;{}[\\]~\\n]+$)(?=(.*\\w)).+$": "^!+[^!*,;{}[\\]~\\n]*\\w[^!*,;{}[\\]~\\n]*$"
}


# TODO handle a global defs so as to be able to create new ones
def schema2model(schema, path: JsonPath = [],
                 strict: bool = True, fix: bool = True, is_root: bool = True):
    """Convert a JSON schema to a JSON model assuming a 2020-12 semantics."""

    global CURRENT_SCHEMA, SCHEMA

    # 4.3.2 Boolean JSON Schemas
    if isinstance(schema, bool):
        return "$ANY" if schema else "$NONE"

    spath: str = jpath(path)

    assert isinstance(schema, dict), f"is an object at [{spath}]"

    if "$schema" in schema:
        sname = schema["$schema"]
        if CURRENT_SCHEMA is not None and CURRENT_SCHEMA != sname:
            log.warning(f"distinct nested $schema: {sname} at [{spath}]")
        CURRENT_SCHEMA = sname

    if SCHEMA is None:
        # COPY because schema may be changed… (hmmm…)
        SCHEMA = copy.deepcopy(schema)

    # handle metadata
    sharp = {}
    for prop in META_KEYS:
        if prop in schema:
            sharp[prop] = schema[prop]

    # handle defs
    # FIXME should delay conversion...
    defs = {}
    if "$defs" in schema or "definitions" in schema:
        dname = "$defs" if "$defs" in schema else "definitions"
        IDS[dname] = {}
        _defs = schema[dname]
        assert isinstance(_defs, dict)
        for name, val in _defs.items():
            log.info(f"registering {dname}/{name} at [{spath}]")
            # if name is ugly, $ref are encoded, we encode here as well
            if "/" in name or "%" in name:
                encoded = quote(name).replace("~", "~0").replace("/", "~1")
            else:
                encoded = name
            # keep json schema for handling $ref #
            IDS[dname][encoded] = val
            # provide a local converted version as well? not enough??
            defs[encoded] = schema2model(val, path + [dname, name], strict, fix, False)
        # special root handling
        IDS[dname][""] = "$#"

    # FIXME cleanup OpenAPI extentions "x-*", nullable
    for prop in list(schema.keys()):
        if prop.startswith("x-"):
            log.warning(f"deleting {prop} at [{spath}]")
            del schema[prop]
        if "nullable" in schema:
            nullable = schema["nullable"]
            assert isinstance(nullable, bool)
            if nullable:
                if "type" in schema and isinstance(schema["type"], str):
                    schema["type"] = [schema["type"], "null"]
                log.warning(f"ignoring nullable directive at [{spath}]")
            del schema["nullable"]

    # FIX missing type in some cases
    if "type" not in schema:
        if "properties" in schema or "required" in schema or "additionalProperties" in schema:
            schema["type"] = "object"
        elif "pattern" in schema or "maxLength" in schema or "minLength" in schema:
            schema["type"] = "string"
        elif "items" in schema or "minItems" in schema or "maxItems" in schema:
            schema["type"] = "array"

    # translate if/then/else to and/xor/not
    # TODO move/replicate in simplify?
    # NOTE this induces some code expansion
    # NOTE generated structures may be simplified later
    if "then" in schema or "else" in schema:
        if "if" not in schema:
            # no if => then/else are ignored (10.2.2)
            log.warning(f"ignoring then/else without if at [{spath}]")
            if "else" in schema:
                del schema["else"]
            if "then" in schema:
                del schema["then"]
        else:  # if in schema
            sif = schema["if"]
            del schema["if"]
            # possibly add type to help convertion
            if isinstance(sif, dict) and "type" not in sif:
                for t in SPLITS.keys():
                    if only(sif, *SPLITS[t], *IGNORE):
                        sif["type"] = t
                        break
            if isinstance(sif, dict) and "type" in sif and isinstance(sif["type"], str):
                type_sif = sif["type"]
            else:
                type_sif = None
            if "then" in schema:
                sthen = schema["then"]
                del schema["then"]
                if type_sif and isinstance(sthen, dict) and "type" not in sthen:
                    sthen["type"] = type_sif
            else:
                sthen = True
            if "else" in schema:
                selse = schema["else"]
                del schema["else"]
                if type_sif and isinstance(selse, dict) and "type" not in selse:
                    selse["type"] = type_sif
            else:
                selse = True
            # W, if: X, then: Y, else: Z => (W and ((X and Y) x?or (not X and Z))
            # separate meta keywords from significant keywords
            subschema = {}
            for k in list(schema.keys()):
                if k not in IGNORE:
                    subschema[k] = schema[k]
                    del schema[k]
            if "allOf" not in schema:
                schema["allOf"] = []
            schema["allOf"].append(subschema)
            schema["allOf"].append(
                {
                    "anyOf": [
                        { "allOf": [ sif, sthen ] },
                        { "allOf": [ { "not": copy.deepcopy(sif) }, selse ] }
                    ]
                }
            )
    elif "if" in schema:
        log.warning(f"ignoring lone if at [{spath}]")
        del schema["if"]

    # FIXME adhoc handling for table-schema.json and ADEME and others
    # FIXME maybe this is not needed anymore?
    if "type" in schema and schema["type"] == "object" and ("anyOf" in schema or "oneOf" in schema):
        log.warning(f"distributing object on anyOf/oneOf at [{spath}]")
        # special case for Ademe
        if "anyOf" in schema:
            assert "oneOf" not in schema
            lof = schema["anyOf"]
        elif "oneOf" in schema:
            assert "anyOf" not in schema
            lof = schema["oneOf"]
        else:
            assert False  # dead code
        # transfer type in list
        del schema["type"]
        for s in lof:
            assert isinstance(s, dict)
            s["type"] = "object"
        if "required" in schema:
            required = schema["required"]
            del schema["required"]
            for s in lof:
                if "required" in s:
                    s["required"].append(required)
                else:
                    s["required"] = required
        if "properties" in schema:
            props = schema["properties"]
            del schema["properties"]
            for s in lof:
                if "properties" in s:
                    s["properties"].update(props)
                else:
                    s["properties"] = props
        if "additionalProperties" in schema:
            addprop = schema["additionalProperties"]
            del schema["additionalProperties"]
            for s in lof:
                # cold overwrite, should warn
                s["additionalProperties"] = addprop
        if "patternProperties" in schema:
            pp = schema["patternProperties"]
            del schema["patternProperties"]
            for s in lof:
                # cold overwrite, should warn
                s["patternProperties"] = pp

    if "type" in schema and ("allOf" in schema or "anyOf" in schema or "oneOf" in schema or
                             "enum" in schema or "$ref" in schema):
        log.warning("removing type from constructed schema?")
        del schema["type"]

    # structures
    if "oneOf" in schema:
        choices = schema["oneOf"]
        assert isinstance(choices, list), f"oneOf list at [{spath}]"
        if only(schema, "oneOf", *IGNORE):
            model = {"^": [schema2model(s, path + ["oneOf", i], strict, fix, False)
                         for i, s in enumerate(choices)]}
            return buildModel(model, {}, defs, sharp, is_root)
        else:  # try building an "allOf" layer
            log.warning(f"keyword oneOf intermixed with other keywords at [{spath}]")
            ao = allOfLayer(schema, "oneOf")
            return schema2model(ao, path + ["oneOf"], strict, fix, False)
    elif "anyOf" in schema:
        choices = schema["anyOf"]
        assert isinstance(choices, (list, tuple)), f"anyOf list at [{spath}]"
        if only(schema, "anyOf", *IGNORE):
            model = {"|": [schema2model(s, path + ["anyOf", i], strict, fix, False)
                        for i, s in enumerate(choices)]}
            return buildModel(model, {}, defs, sharp, is_root)
        else:
            log.warning(f"keyword anyOf intermixed with other keywords at [{spath}]")
            ao = allOfLayer(schema, "anyOf")
            return schema2model(ao, path + ["anyOf"], strict, fix, False)
    elif "allOf" in schema:
        # NOTE types should be compatible to avoid an empty match
        choices = schema["allOf"]
        assert isinstance(choices, (list, tuple)), f"allOf list at [{spath}]"
        if only(schema, "allOf", *IGNORE):
            model = {"&": [schema2model(s, path + ["allOf", i], strict, fix, False)
                        for i, s in enumerate(choices)]}
            return buildModel(model, {}, defs, sharp, is_root)
        else:  # build another allOf layer
            log.warning(f"keyword allOf intermixed with other keywords at [{spath}]")
            ao = allOfLayer(schema, "allOf")
            return schema2model(ao, path + ["allOf"], strict, fix, False)
    elif "not" in schema:
        val = schema["not"]
        assert isinstance(val, dict), "not object at [{spath}]"
        if only(schema, "not", *IGNORE):
            if len(val) == 0:
                model = "$NONE"
            else:
                model = {"^": ["$ANY", schema2model(val, path + ["not"], strict, fix, False)]}
            return buildModel(model, {}, defs, sharp, is_root)
        else:  # add a allOf layer
            log.warning(f"keyword not intermixed with other keywords at [{spath}]")
            ao = allOfLayer(schema, "not")
            return schema2model(ao, path + ["not"], strict, fix, False)

    # handle simpler schemas
    if "$ref" in schema:
        if only(schema, "$ref", *IGNORE):
            ref = schema["$ref"]
            assert isinstance(ref, str) and len(ref) > 0
            if ref in ("#/", "#"):
                return "$#"

            name = None
            if ref.startswith("#/$defs/") and only(schema, "$ref", *IGNORE):
                # keep a reference if simple
                name = ref[8:]
            elif ref.startswith("#/definitions/") and only(schema, "$ref", *IGNORE):
                name = ref[14:]
            if name is not None and "/" not in name:
                return buildModel("$" + name, {}, defs, sharp, is_root)

            # else we have to navigate…
            # FIXME should be useless? should have been simplified?
            if ref.startswith("#/"):
                names = ref[2:].split("/")
                # standard /$def/foo
                if names and names[0] in ("$defs", "definitions"):
                    val = IDS
                    for name in names:
                        assert name in val, \
                            f"following path in {ref}: missing {name} ({IDS}) at [{spath}]"
                        val = val[name]
                else:  # arbitrary path
                    val = SCHEMA
                    for name in names:
                        if "~0" in name or "~1" in name or "%" in name:
                            name = unquote(name).replace("~1", "/").replace("~0", "~")
                        assert name in val, f"following path in {ref}: missing {name} at [{spath}]"
                        val = val[name]
                model = schema2model(val, path + ["$ref"], strict, fix, False)
                return buildModel(model, {}, defs, sharp, is_root)
            else:
                assert False, f"$ref handling not implemented: {ref}"
        else:
            log.warning(f"$ref intermixed with other keywords at [{spath}]")
            return schema2model(allOfLayer(schema, "$ref"), path, strict, fix, False)

    elif "type" in schema:
        ts = schema["type"]
        if isinstance(ts, (list, tuple)):
            schemas = split_schema(schema)
            del schemas[""]  # remove ignored stuff
            return buildModel(
                {
                    "|": [
                        schema2model(v, path + ["typeS"], strict, fix, False)
                            for v in schemas.values()
                    ]
                }, {}, defs, sharp, is_root)
        elif ts == "string" and "const" in schema:
            doubt(only(schema, "type", "const", *IGNORE), f"string const at [{spath}]", strict)
            const = schema["const"]
            return buildModel(f"_{const}", {}, defs, sharp, is_root)
        elif ts == "string":
            doubt(only(schema, "enum", "type", "format", "pattern", "minLength", "maxLength",
                      "contentMediaType", "contentEncoding", *IGNORE),
                  f"string at [{spath}]", strict)
            model = "$STRING" if EXPLICIT_TYPE else ""
            if "format" in schema:
                fmt = schema["format"]
                if fmt is not None:
                    model = format2model(fmt)
                else:
                    log.warning(f"ignoring null format at [{spath}]")
            constraints = {}
            if "enum" in schema:
                ve = schema["enum"]
                assert isinstance(ve, list), path
                # TODO check stat *all* items are strings
                if len(ve) == 1:
                    assert isinstance(ve[0], str), path
                    model = esc(ve[0])
                else:
                    model = {"|": [esc(v) for v in ve]}
            if "pattern" in schema:
                pattern = schema["pattern"]
                pattern = PATTERN.get(pattern, pattern)
                assert isinstance(pattern, str), f"string pattern at [{spath}]"
                assert model in ("", "$STRING"), f"string pattern for string at [{spath}]"
                model = f"/{pattern}/"
            if "minLength" in schema and "maxLength" in schema and \
                    schema["minLength"] == schema["maxLength"]:
                ival = schema["minLength"]
                assert isinstance(ival, int), f"int length at [{spath}]"
                constraints["="] = ival
            else:
                if "minLength" in schema:
                    minlen = schema["minLength"]
                    assert isinstance(minlen, int), f"int min length at [{spath}]"
                    constraints[">="] = minlen
                if "maxLength" in schema:
                    maxlen = schema["maxLength"]
                    assert isinstance(maxlen, int), f"int max length at [{spath}]"
                    constraints["<="] = maxlen
            # if "contentMediaType" in schema:
            #     val = schema["contentMediaType"]
            #     assert isinstance(val, str), path
            #     constraints["mime"] = val
            # if "contentEncoding" in schema:
            #     val = schema["contentEncoding"]
            #     assert isinstance(val, str), path
            #     constraints["encoding"] = val
            return buildModel(model, constraints, defs, sharp, is_root)
        elif ts == "number":
            doubt(only(schema, "type", "format", "multipleOf", "minimum", "maximum",
                       "exclusiveMinimum", "exclusiveMaximum", *IGNORE),
                  f"number properties at [{spath}]", strict)
            model = "$NUMBER" if EXPLICIT_TYPE else -1.0
            if "format" in schema:
                fmt = schema["format"]
                assert fmt in ("double", "float"), f"bad format {fmt} at [{spath}]"
                if fmt == "double":
                    model = "$DOUBLE"
                elif fmt == "float":
                    model = "$FLOAT"
                else:
                    assert False, f"unexpected number format {fmt} at [{spath}]"
            constraints = numberConstraints(schema)
            return buildModel(model, constraints, defs, sharp, is_root)
        elif ts == "integer" and "const" in schema:
            ival = schema["const"]
            if isinstance(ival, (int, float)) and ival == int(ival):
                model = "={int(ival)}"
            else:
                model = "$NONE"
        elif ts == "integer":
            doubt(only(schema, "type", "format", "multipleOf", "minimum", "maximum",
                       "exclusiveMinimum", "exclusiveMaximum", *IGNORE),
                  f"integer properties at [{spath}]", strict)
            model = "$INTEGER" if EXPLICIT_TYPE else -1
            # OpenAPI
            if "format" in schema:
                fmt = schema["format"]
                log.warning(f"ignoring format {fmt} at [{spath}]")
                assert fmt in ("int32", "int64"), f"bad format {fmt} at [{spath}]"
                if fmt == "int32":
                    model = "$I32"
                elif fmt == "int64":
                    model = "$I64"
                else:
                    assert False, f"unexpected integer format: {fmt} at [{spath}]"
            constraints = numberConstraints(schema)
            return buildModel(model, constraints, defs, sharp, is_root)
        elif ts == "boolean":
            if "required" in schema:
                log.warning(f"'required' ignored for boolean at [{spath}]")
            doubt(only(schema, "type", "required", *IGNORE),
                  f"boolean properties at [{spath}]", strict)
            model = "$BOOL" if EXPLICIT_TYPE else True
            return buildModel(model, {}, defs, sharp, is_root)
        elif ts == "null":
            model = "$NULL" if EXPLICIT_TYPE else None
            doubt(only(schema, "type", *IGNORE), f"null with props at [{spath}]", strict)
            return buildModel(model, {}, defs, sharp, is_root)

        elif ts == "array":
            if fix:
                # common misplacements
                if not strict and "items" in schema and isinstance(schema["items"], dict):
                    subschema = schema["items"]
                    for kw in ("uniqueItems", "minItems", "maxItems"):
                        # possible move misplaced keyword
                        if kw not in schema and kw in subschema and "type" in subschema and \
                                isinstance(subschema["type"], str) and subschema["type"] != "array":
                            log.warning(f"moving misplaced {kw} at [{spath}.items]")
                            schema[kw] = subschema[kw]
                            del subschema[kw]
                # common misnamings
                rename = { "minLength": "minItems", "maxLength": "maxItems" }
                for kw in rename:
                    if kw in schema:
                        if rename[kw] not in schema:
                            log.warning(f"renaming {kw} to {rename[kw]} at [{spath}]")
                            schema[rename[kw]] = schema[kw]
                        else:
                            log.warning(f"removing useless {kw} at [{spath}]")
                        del schema[kw]

            # sanity check
            doubt(only(schema, "type", "prefixItems", "items",
                       "contains", "minContains", "maxContains",
                       "minItems", "maxItems", "uniqueItems", *IGNORE),
                  f"array properties at [{spath}]", strict)

            # build model
            constraints = {}
            if "minItems" in schema and "maxItems" in schema and \
                    schema["minItems"] == schema["maxItems"]:
                ival = schema["minItems"]
                assert isinstance(ival, int)
                constraints["="] = ival
            else:
                if "minItems" in schema:
                    mini = schema["minItems"]
                    assert type(mini) is int, f"int min items at [{spath}]"
                    constraints[">="] = mini
                if "maxItems" in schema:
                    maxi = schema["maxItems"]
                    assert type(maxi) is int, f"int max items at [{spath}]"
                    constraints["<="] = maxi
            if "uniqueItems" in schema:
                unique = schema["uniqueItems"]
                assert isinstance(unique, bool), f"boolean unique at [{spath}]"
                if unique:
                    constraints["!"] = True
            if "prefixItems" in schema:
                doubt(only(schema, "type", "prefixItems", "items", "minItems", "maxItems",
                           "uniqueItems", *IGNORE),
                      f"array props with prefixItems at [{spath}]", strict)
                # tuple
                vpi = schema["prefixItems"]
                assert isinstance(vpi, list), f"list prefixItems at [{spath}]"
                model = [
                    schema2model(s, path + ["prefixItems", i], strict, fix, False)
                        for i, s in enumerate(vpi)
                ]
                if "items" in schema:
                    # cas prefixItems + items
                    if isinstance(schema["items"], bool):
                        assert not constraints, f"not implemented yet at [{spath}]"
                        if not schema["items"]:
                            return buildModel(model, {">=": 0, "<=": len(model)},
                                              defs, sharp, is_root)
                        else:
                            assert False, f"not implemented yet at [{spath}]"
                    # items is a type
                    model.append(schema2model(schema["items"], path + ["items"],
                                              strict, fix, False))
                    if not constraints:
                        constraints[">="] = len(model) - 1
                    return buildModel(model, constraints, defs, sharp, is_root)
                else:
                    model.append("$ANY")
                    if not constraints:
                        constraints[">="] = len(model) - 1
                    return buildModel(model, constraints, defs, sharp, is_root)
            elif "items" in schema:
                doubt(only(schema, "type", "items", "minItems", "maxItems", "uniqueItems",
                           *IGNORE), f"array props with items at [{spath}]", strict)
                sitems = schema["items"]
                if isinstance(sitems, list):
                    # OLD JSON Schema prefixItems…
                    array = [
                        schema2model(s, path + ["items", i], strict, fix, False)
                            for i, s in enumerate(sitems)
                    ]
                    if strict:
                        return array
                    else:  # trigger varlen tuple…
                        array.append("$ANY")
                        return { "@": array, ">=": 0 }
                else:
                    assert isinstance(sitems, (dict, bool)), f"valid schema at [{spath}]"
                    model = [schema2model(schema["items"], path + ["items"], strict, fix, False)]
                    return buildModel(model, constraints, defs, sharp, is_root)
            elif "contains" in schema:
                # NO contains/items mixing yet
                assert only(schema, "type", "contains", "minContains", "maxContains",
                            "uniqueItems", *IGNORE), f"array props for containts[{spath}]"
                # NOTE contains is not really supported in jm v2, or rather as an extension
                model = {
                    "@": ["$ANY"],
                    ".in": schema2model(schema["contains"], path + ["contains"], strict, fix, False)
                }
                if "minContains" in schema:
                    mini = schema["minContains"]
                    assert type(mini) is int, f"int min contains at [{spath}]"
                    model[">="] = mini
                if "maxContains" in schema:
                    maxi = schema["maxContains"]
                    assert type(maxi) is int, f"int max contains at [{spath}]"
                    model["<="] = maxi
                return buildModel(model, constraints, defs, sharp, is_root)
            else:
                return buildModel(["$ANY"], constraints, defs, sharp, is_root)

        elif ts == "object":

            # ignore OpenAPI extension
            if "discriminator" in schema:
                log.warning(f"ignoring discriminator at [{spath}]")
                del schema["discriminator"]

            if fix:
                # common misplacements
                if not strict and "properties" in schema and isinstance(schema["properties"], dict):
                    properties = schema["properties"]
                    for kw in ["additionalProperties", "unevaluatedProperties",
                               "minProperties", "maxProperties"]:
                        if kw in properties:
                            if kw not in schema:
                                log.warning(f"moving misplaced {kw} at [{spath}.properties]")
                                schema[kw] = properties[kw]
                                del properties[kw]

            # sanity check
            doubt(only(schema, "type", "properties", "additionalProperties", "required",
                       "minProperties", "maxProperties", "patternProperties", "propertyNames",
                       *IGNORE), f"object properties at [{spath}]", strict)

            # build model
            constraints = {}
            model = {}
            if "minProperties" in schema and "maxProperties" in schema and \
                    schema["minProperties"] == schema["maxProperties"]:
                ival = schema["maxProperties"]
                assert isinstance(ival, int), f"int # props at [{spath}] ({tname(ival)})"
            else:
                if "minProperties" in schema:
                    mini = schema["minProperties"]
                    assert type(mini) is int, f"int min props at [{spath}] ({tname(mini)})"
                    constraints[">="] = mini
                if "maxProperties" in schema:
                    maxi = schema["maxProperties"]
                    assert type(maxi) is int, f"int max props at [{spath}] ({tname(maxi)})"
                    constraints["<="] = maxi

            if "patternProperties" in schema:
                pats = schema["patternProperties"]
                assert isinstance(pats, dict), f"dict pattern props at [{spath}]"
                for pp in sorted(pats.keys()):
                    model[f"/{pp}/"] = \
                        schema2model(pats[pp], path + ["patternProperties", pp], strict, fix, False)

            if "propertyNames" in schema:
                # does not seem very useful?
                pnames = schema["propertyNames"]
                if "additionalProperties" in schema:
                    target = schema2model(schema["additionalProperties"], path, strict, fix, False)
                else:
                    target = "$ANY"

                # TODO for other cases, we could create a new reference
                assert only(pnames, "pattern", "type", "format", *IGNORE), \
                    f"props for prop names at [{spath}]"
                # if given a type, it must be string
                if "type" in pnames:
                    assert pnames["type"] == "string", f"prop name is string at [{spath}]"
                if "pattern" in pnames:
                    pat = pnames["pattern"]
                    assert isinstance(pat, str), f"pattern is string at [{spath}]"
                    model[f"/{pat}/"] = target
                elif "format" in pnames:
                    fmt = pnames["format"]
                    model[format2model(fmt)] = target
                else:
                    model[""] = target

            if "properties" in schema:
                props = schema["properties"]
                required = schema.get("required", [])
                assert isinstance(props, dict), f"dict properties [{spath}]"
                for k, v in props.items():
                    if k in required:
                        model[f"_{k}"] = \
                            schema2model(v, path + ["properties", f"_{k}"], strict, fix, False)
                    else:
                        model[f"?{k}"] = \
                            schema2model(v, path + ["properties", f"?{k}"], strict, fix, False)
                if "additionalProperties" in schema:
                    ap = schema["additionalProperties"]
                    if isinstance(ap, bool):
                        if ap:
                            model[""] = "$ANY"
                        # else nothing else is allowed
                    elif isinstance(ap, dict):
                        model[""] = schema2model(ap, path + ["additionalProperties"],
                                                 strict, fix, False)
                    else:
                        assert False, f"not implemented yet at [{spath}]"
                else:
                    model[""] = "$ANY"

            elif "additionalProperties" in schema:
                # "additionalProperties" without "properties" or "patternProperties"
                doubt(only(schema, "type", "additionalProperties", "maxProperties", "minProperties",
                           "properties", "patternProperties", *IGNORE),
                      f"add prop props at [{spath}]", strict)
                if "properties" not in schema and "additionalProperties" not in schema and strict:
                    assert False, "additionalProperties without properties or patternProperties"
                ap = schema["additionalProperties"]
                if isinstance(ap, bool):
                    if ap:
                        model[""] = "$ANY"
                    # else nothing else is allowed
                elif isinstance(ap, dict):
                    model[""] = schema2model(ap, path + ["additionalProperties"],
                                             strict, fix, False)
                else:
                    assert False, f"not implemented yet at [{spath}]"

            elif "required" in schema:
                # required without properties or additionalProperties
                doubt(only(schema, "type", "required", "maxProperties", "minProperties",
                           *IGNORE), f"object props at [{spath}]", strict)
                required = schema["required"]
                assert isinstance(required, list) and all(isinstance(s, str) for s in required)
                model[""] = "$ANY"
                model.update({ f"_{k}": "$ANY" for k in required })
                # what about other props?

            else:
                doubt(only(schema, "type", "maxProperties", "minProperties", "patternProperties",
                           "propertyNames", *IGNORE), f"object props at [{spath}]", strict)
                if "propertyNames" in schema:
                    pass
                else:
                    model[""] = "$ANY"
            # handle constraints
            return buildModel(model, constraints, defs, sharp, is_root)
        else:
            assert False, f"unexpected type: {ts} at [{spath}]"
    elif "enum" in schema:
        # FIXME check type value compatibility with other keywords, eg type?!
        for prop in ("maxLength", "minLength"):
            if prop in schema:
                log.warning(f"ignoring doubtful {prop} from enum at [{spath}]")
                del schema[prop]
        doubt(only(schema, "enum", *IGNORE),
              f"keyword enum intermixed with other keywords at [{spath}]", strict)
        ve = schema["enum"]
        assert isinstance(ve, list), f"enum list at [{spath}]"
        if len(ve) == 1:
            model = toconst(ve[0])
        else:
            model = {"|": [toconst(v) for v in ve]}
        # vérifier les valeurs?
        return buildModel(model, {}, defs, sharp, is_root)
    elif "const" in schema:
        assert only(schema, "const", *IGNORE), \
            f"keyword const intermixed with other keywords at [{spath}]"
        const = schema["const"]
        # what is the type of the constant? assume a string for NOW, could be anything?
        return buildModel(toconst(const), {}, defs, sharp, is_root)
    else:
        # empty schema
        return buildModel("$ANY", {}, defs, sharp, is_root)
