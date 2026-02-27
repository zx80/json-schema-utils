from typing import Any
import re
import copy
import logging
import hashlib
import json

from .utils import JsonSchema, SchemaPath, SchemaPathSegment, Jsonable
from .utils import only, decode_url, schemapath_to_urlpath, is_abs_url
from .utils import TYPED_KEYWORDS, KEYWORD_TYPE, META_KEYS, IGNORE, ALL_TYPES
from .recurse import recurseSchema, log as rec_log

# wrapper may use a simplification step
from .inline import resolveExternalRefs
from .simplify import simplifySchema, scopeDefs
from .types import computeTypes

log = logging.getLogger("convert")
log.setLevel(logging.DEBUG)

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

# collection of properties that hint of a cross-version meta schema
_META_PROPS = {
    "type", "$schema", "allOf", "anyOf", "oneOf",
    "properties", "additionalProperties",
    "items", "uniqueItems",
    # NO: $ref
}

def is_probable_meta_schema(properties: dict[str, Any]) -> bool:
    """Detect property list which looks like a meta-schema."""
    for prop in _META_PROPS:
        if prop not in properties:
            return False
    return True

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

def opt_quote(s: str|int) -> str:
    if isinstance(s, int):
        return str(s)
    elif re.search(r"^\w+$", s):
        return s
    else:
        return '"' + s.replace('"', r'\"').replace("\n", r'\n') + '"'

def sesc(s: SchemaPathSegment) -> str:
    if isinstance(s, str):
        return opt_quote(s)
    elif isinstance(s, tuple):
        assert len(s) == 2
        return opt_quote(s[0]) + "." + opt_quote(s[1])
    else:
        assert False, f"s={s}"

def jpath(path: SchemaPath):
    log.debug(f"path = {path}")
    return "." + ".".join(sesc(s) for s in path)

def numberConstraints(schema):
    assert "type" in schema and schema["type"] in ("integer", "number")
    constraints = {}
    # draft6 and better
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
        assert type(mini) in (int, float), f"exclusiveMinimum is a number but: {mini}"
        constraints[">"] = mini
    if "exclusiveMaximum" in schema:
        maxi = schema["exclusiveMaximum"]
        assert type(maxi) in (int, float), f"exclusiveMaximum is a number but: {maxi}"
        constraints["<"] = maxi
    return constraints


def buildModel(model, constraints: dict[str, Any], defs: dict[str, Jsonable], sharp: dict, is_root: bool = False):
    """Build a model."""

    if constraints or sharp or is_root and defs:
        # we want to force a JSON object

        if constraints:
            m = {"@": model, **constraints}
        elif isinstance(model, dict):
            m = model
        else:
            m = {"@": model}

        if sharp and "description" in sharp:
            m["#"] = sharp["description"]
        if is_root and defs:
            m["$"] = defs
        if is_root and "#" not in m:
            m["#"] = "JSON Model generated from a JSON Schema with json-schema-utils"

        return m

    else:

        if is_root and isinstance(model, dict) and "#" not in model:
            model["#"] = "JSON Model generated from a JSON Schema with json-schema-utils"

        # simplify
        while isinstance(model, dict) and len(model) == 1 and "@" in model:
            model = model["@"]

        return model


def split_schema(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assert isinstance(schema, dict) and "type" in schema
    types = schema["type"]
    assert isinstance(types, (list, tuple))
    # log.info(f"splitting on {types}")
    # per type
    schemas: dict[str, Any] = {t: {"type": t} for t in types}
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
            for t, sh in schemas.items():
                if t != "":
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
            # if possible remove empty list or switch to const
            for t in schemas:
                if t != "" and "enum" in schemas[t]:
                    enums = schemas[t]["enum"]
                    if len(enums) == 0:
                        schemas[t] = False
                    elif len(enums) == 1:
                        schemas[t] = {"const": enums[0]}
        elif prop in KEYWORD_TYPE:
            ptype = KEYWORD_TYPE[prop]
            assert ptype in types
            schemas[KEYWORD_TYPE[prop]][prop] = val
            # Argh, we may have to duplicated stuff between int/float
            if ptype == "number" and "integer" in types:
                schemas["integer"][prop] = copy.deepcopy(val)
            elif ptype == "integer" and "number" in types:
                schemas["number"][prop] = copy.deepcopy(val)
        else:
            log.debug(f"type split: property {prop} moved to commons")
            schemas[""][prop] = val
    # log.debug(f"splitted: {schemas}")
    return schemas


# global identifiers
# TODO use a cleaner context for that!
CURRENT_SCHEMA: str|None = None
SCHEMA = None
IDS: dict[str, dict[str, Any]] = {}
RENAMES: dict[str, str] = {}
N_RENAMES: int = 0
EXPLICIT_TYPE: bool = False

# "#foo" -> "#/path/to/foo/id"
ID_TO_PATH: dict[str, str] = {}

def reset():
    """Reset global stuff."""
    global CURRENT_SCHEMA, SCHEMA, IDS, RENAMES, N_RENAMES, IDS_STACK
    CURRENT_SCHEMA, SCHEMA = None, None
    IDS, ID_TO_PATH, RENAMES, N_RENAMES = {}, {}, {}, 0

def get_new_name() -> str:
    """Get an unused name."""
    global N_RENAMES
    while True:
        name = f"_name_{N_RENAMES}_"
        N_RENAMES += 1
        if name not in IDS:
            return name

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
    # log.debug(f"ao {operator} in: {schema}")
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
    # log.debug(f"ao {operator} out: {nschema}")
    return nschema

# (STRANGE) PATTERNS
# manually simplify some patterns for re2 compatibility
# TODO implement some automatic simplifications?
PATTERN: dict[str, str] = {
    # cspell
    "^(?=[^!*,;{}[\\]~\\n]+$)(?=(.*\\w)).+$": "^[^\\[\\]!*,;{}~\\n]*\\w[^\\[\\]!*,;{}~\\n]*$",
    "^(?=!+[^!*,;{}[\\]~\\n]+$)(?=(.*\\w)).+$": "^!+[^\\[\\]!*,;{}~\\n]*\\w[^\\[\\]!*,;{}~\\n]*$"
}

def schema2model(
            schema,
            url: str = ".",
            path: SchemaPath = (),
            defs: dict[str, Jsonable]|None = None,
            strict: bool = True,
            fix: bool = True,
            is_root: bool = True,
            resilient: bool = False,
        ):
    """Convert a JSON schema to a JSON model assuming a more or less a 2020-12 semantics."""

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

    # handle some $id
    lid = schema["$id"] if "$id" in schema else schema["id"] if "id" in schema else None
    if lid:
        # FIXME uniqueness?
        if re.match("#[^/]*$", lid):
            if lid in ID_TO_PATH:
                log.warning(f"overwriting {lid} at {path}")
            ID_TO_PATH[lid] = "#/" + schemapath_to_urlpath(path)
            ID_TO_PATH[url + lid] = ID_TO_PATH[lid]
        if not is_abs_url(lid):
            lid = None
        # TODO compute current url!
        log.debug(f"$id: {lid} {ID_TO_PATH}")

    #
    # Handle local definitions
    #
    # NOTE JS definitions as str, but references are url encoded with further changes for / and ~
    # we need a clear str-for-str correspondance when translating to a model.
    # beware that some chars may or may not be encoded, eg:
    # { "$defs": { "foo\"bla": true }, "allOf": [ { "$ref": "#foo\"bla", "$ref": "#foo%22bla" } ] }
    #
    dname = "$defs" if "$defs" in schema else "definitions"
    if is_root:
        assert defs is None
        defs = {}
    assert isinstance(defs, dict)

    if is_root and dname in schema:
        # FIXME push?
        IDS[dname] = {}
        _defs = schema[dname]
        assert isinstance(_defs, dict)
        for name, val in _defs.items():
            log.info(f"registering {dname}/{name} at [{spath}] ({is_root})")
            log.debug(f"- schema: {json.dumps(val)}")
            if name == "" or "/" in name or "%" in name or "~" in name or "\"" in name:
                # if name is ugly, $ref are encoded…
                new_name = get_new_name()
            else:  # keep as is
                new_name = name
            # keep track of renamed definitions
            RENAMES[name] = new_name
            # keep json schema for handling $ref with a local path (eg "#/$defs/foo")
            IDS[dname][name] = val
            # provide a local converted version as well? not enough??
            defs[new_name] = schema2model(val, lid or url, path + ((dname, name),), defs, strict, fix, False, resilient)

            log.debug(f"def {new_name}: {json.dumps(defs[new_name])}")
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

    # set type explicitely for typical cases of forgotten types
    # $ref?
    # TODO do not overwrite initial type?
    if fix and ("type" not in schema or
                isinstance(schema["type"], list) and len(schema["type"]) > 5):
        # only(schema, *TYPED_KEYWORDS["object"], *IGNORE):
        if "properties" in schema or "required" in schema or "additionalProperties" in schema:
            schema["type"] = "object"
        # only(schema, *TYPED_KEYWORDS["string"], *IGNORE):
        elif "pattern" in schema or "maxLength" in schema or "minLength" in schema:
            schema["type"] = "string"
        # only(schema, *TYPED_KEYWORDS["array"], *IGNORE):
        elif "items" in schema or "minItems" in schema or "maxItems" in schema:
            schema["type"] = "array"
        # else: schema["type"] = sorted(ALL_TYPES)

    # if resilient and "type" not in schema:
    #     schema["type"] = ["null", "boolean", "number", "string", "array", "object"]
    #     if strict:
    #         schema["type"].append("integer")

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
                for t in TYPED_KEYWORDS.keys():
                    if only(sif, *TYPED_KEYWORDS[t], *IGNORE):
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
                # FIXME cold overwrite, should warn
                s["patternProperties"] = pp

    # if "type" in schema and ("allOf" in schema or "anyOf" in schema or "oneOf" in schema or
    #                          "enum" in schema or "$ref" in schema):
    #     log.warning("removing type from constructed schema?")
    #     del schema["type"]

    # structures
    if "oneOf" in schema:
        choices = schema["oneOf"]
        assert isinstance(choices, list), f"oneOf list at [{spath}]"
        if only(schema, "oneOf", *IGNORE):
            model = {"^": [schema2model(s, lid or url, path + (("oneOf", i), ), defs, strict, fix, False, resilient)
                         for i, s in enumerate(choices)]}
            if len(model["^"]) == 1:
                model = model["^"][0]
            return buildModel(model, {}, defs, sharp, is_root)
        else:  # try building an "allOf" layer
            log.warning(f"keyword oneOf intermixed with other keywords at [{spath}]")
            ao = allOfLayer(schema, "oneOf")
            model = schema2model(ao, lid or url, path + ("oneOf",), defs, strict, fix, False, resilient)
            return buildModel(model, {}, defs, sharp, is_root)
    elif "anyOf" in schema:
        choices = schema["anyOf"]
        assert isinstance(choices, (list, tuple)), f"anyOf list at [{spath}]"
        if only(schema, "anyOf", *IGNORE):
            model = {"|": [schema2model(s, lid or url, path + (("anyOf", i), ), defs, strict, fix, False, resilient)
                        for i, s in enumerate(choices)]}
            model["|"] = list(filter(lambda m: m != "$NONE", model["|"]))
            if len(model["|"]) == 1:
                model = model["|"][0]
            return buildModel(model, {}, defs, sharp, is_root)
        else:
            log.warning(f"keyword anyOf intermixed with other keywords at [{spath}]")
            ao = allOfLayer(schema, "anyOf")
            return schema2model(ao, lid or url, path + ("anyOf",), defs, strict, fix, False, resilient)
    elif "allOf" in schema:
        # NOTE types should be compatible to avoid an empty match
        choices = schema["allOf"]
        assert isinstance(choices, (list, tuple)), f"allOf list at [{spath}]"
        if only(schema, "allOf", *IGNORE):
            model = {"&": [schema2model(s, lid or url, path + (("allOf", i), ), defs, strict, fix, False, resilient)
                        for i, s in enumerate(choices)]}
            if len(model["&"]) == 1:
                model = model["&"][0]
            return buildModel(model, {}, defs, sharp, is_root)
        else:  # build another allOf layer
            log.warning(f"keyword allOf intermixed with other keywords at [{spath}]")
            ao = allOfLayer(schema, "allOf")
            model = schema2model(ao, lid or url, path + ("allOf", ), defs, strict, fix, False, resilient)
            return buildModel(model, {}, defs, sharp, is_root)
    elif "not" in schema:
        val = schema["not"]
        if isinstance(val, bool):
            if val:
                model = "$NONE"
                return model
            else:  # ignore "not: false"
                del schema["not"]
        elif only(schema, "not", *IGNORE):
            if len(val) == 0:
                model = "$NONE"
                return model
            else:
                model = {"^": ["$ANY", schema2model(val, lid or url, path + ("not", ), defs, strict, fix, False, resilient)]}
            return buildModel(model, {}, defs, sharp, is_root)
        else:  # add a allOf layer
            log.warning(f"keyword not intermixed with other keywords at [{spath}]")
            ao = allOfLayer(schema, "not")
            model = schema2model(ao, lid or url, path + ("not", ), defs, strict, fix, False, resilient)
            return buildModel(model, {}, defs, sharp, is_root)

    # handle simpler schemas
    # TODO "ref" for older versions?
    if "$ref" in schema:
        if only(schema, "$ref", *IGNORE):
            ref = schema["$ref"]
            assert isinstance(ref, str) and len(ref) > 0
            log.debug(f"$ref: {ref}")
            if ref in ("#/", "#"):
                return "$#"

            # found a reference to an $id
            if ref in ID_TO_PATH:
                ref = ID_TO_PATH[ref]

            name = None
            if ref.startswith("#/$defs/") and only(schema, "$ref", *IGNORE):
                # keep a reference if simple
                name = ref[8:]
            elif ref.startswith("#/definitions/") and only(schema, "$ref", *IGNORE):
                name = ref[14:]

            # shortcut for simple names which match an existing definition
            if name is not None and "/" not in name:
                uname = decode_url(name)
                if uname not in RENAMES:
                    log.warning(f"reference to {name} seems hidden")
                else:
                    uname = RENAMES[uname]
                return buildModel("$" + uname, {}, defs, sharp, is_root)

            # else we have to navigate…
            # FIXME should be useless? should have been simplified?
            if ref.startswith("#/"):
                names = ref[2:].split("/")
                # standard /$def/foo
                if names and names[0] in ("$defs", "definitions"):
                    val = IDS
                    for name in names:
                        uname = decode_url(name)
                        assert uname in val, \
                            f"following path in {ref}: missing {name} ({IDS}) at [{spath}]"
                        val = val[uname]
                else:  # handle arbitrary path
                    val = SCHEMA
                    for name in names:
                        uname = decode_url(name)
                        if isinstance(val, dict):
                            assert uname in val, \
                                f"following path in {ref}: expecting property {name} at [{spath}]"
                            val = val[uname]
                        elif isinstance(val, list):
                            assert re.match(r"\d+$", uname), \
                                "following path in {ref}: not an array index for {name} at [{spath}]"
                            val = val[int(uname)]
                model = schema2model(val, lid or url, path + ("$ref", ), defs, strict, fix, False, resilient)
                return buildModel(model, {}, defs, sharp, is_root)
            else:
                assert False, f"$ref handling not implemented: {ref}"
        else:
            log.warning(f"$ref intermixed with other keywords at [{spath}]")
            ao = allOfLayer(schema, "$ref")
            model = schema2model(ao, lid or url, path, defs, strict, fix, False, resilient)
            return buildModel(model, {}, defs, sharp, is_root)

    elif "type" in schema:
        ts = schema["type"]
        if isinstance(ts, (list, tuple)):

            # recognize $ANY
            all_types = set(ts) == ALL_TYPES
            if only(schema, "type", *IGNORE) and all_types:
                return buildModel("$ANY", {}, defs, sharp, is_root)

            # else split schema per type
            schemas = split_schema(schema)
            del schemas[""]  # remove ignored stuff
            model = buildModel(
                {
                    "|": [
                        schema2model(v, lid or url, path + (("|", i), ), defs, strict, fix, False, resilient)
                            for i, v in enumerate(schemas.values())
                    ]
                }, {}, defs, sharp, is_root)
            # cleanup
            model["|"] = list(filter(lambda m: m != "$NONE", model["|"]))
            if len(model["|"]) == 1:
                if len(model) == 1:
                    model = model["|"][0]
                else:
                    model["@"] = model["|"][0]
                    del model["|"]
            return model
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
                if isinstance(ival, float):
                    assert ival == int(ival), f"int length spec at [{spath}]"
                    ival = int(ival)
                assert type(ival) is int and ival >= 0, f"pos int length at [{spath}]"
                constraints["="] = ival
            else:
                if "minLength" in schema:
                    minlen = schema["minLength"]
                    if isinstance(minlen, float):
                        assert minlen == int(minlen), f"int min length spec at [{spath}]"
                        minlen = int(minlen)
                    assert type(minlen) is int and minlen >= 0, f"pos int min length at [{spath}]"
                    if minlen > 0:
                        constraints[">="] = minlen
                    # else ignore
                if "maxLength" in schema:
                    maxlen = schema["maxLength"]
                    if isinstance(maxlen, float):
                        assert maxlen == int(maxlen), f"int max length spec at [{spath}]"
                        maxlen = int(maxlen)
                    assert type(maxlen) is int and maxlen >= 0, f"int max length at [{spath}]"
                    if maxlen > 0:
                        constraints["<="] = maxlen
                    else:
                        constraints["="] = maxlen
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
            doubt(only(schema, "type", "prefixItems", "items", "additionalItems",
                       "contains", "minContains", "maxContains", "unexpectedItems",
                       "minItems", "maxItems", "uniqueItems", *IGNORE),
                  f"array properties at [{spath}]", strict)

            # build model
            constraints = {}
            if "minItems" in schema and "maxItems" in schema and \
                    schema["minItems"] == schema["maxItems"]:
                ival = schema["minItems"]
                if type(ival) is float:
                    assert ival == int(ival), "int array length spec at [{spath}]"
                    ival = int(ival)
                assert isinstance(ival, int)
                if ival > 0:
                    constraints["="] = ival
                elif ival == 0:
                    return buildModel([], {}, defs, sharp, is_root)
                else:
                    return buildModel("$NONE", {}, defs, sharp, is_root)
            else:
                if "minItems" in schema:
                    mini = schema["minItems"]
                    if type(mini) is float:
                        assert mini == int(mini), "int array length spec at [{spath}]"
                        mini = int(mini)
                    assert type(mini) is int, f"int min items at [{spath}]"
                    assert mini >= 0, "positive min items as [{spath}]"
                    if mini > 0:
                        constraints[">="] = mini
                    # otherwise nothing to check
                if "maxItems" in schema:
                    maxi = schema["maxItems"]
                    if type(maxi) is float:
                        assert maxi == int(maxi), "int array length spec at [{spath}]"
                        maxi = int(maxi)
                    assert type(maxi) is int, f"int max items at [{spath}]"
                    assert maxi >= 0, "positive max items as [{spath}]"
                    if maxi == 0:
                        constraints["="] = maxi
                        if ">=" in constraints:
                            del constraints[">="]
                    else:
                        constraints["<="] = maxi
            if "uniqueItems" in schema:
                unique = schema["uniqueItems"]
                assert isinstance(unique, bool), f"boolean unique at [{spath}]"
                if unique:
                    constraints["!"] = True

            # up to 7:
            # - items: schema = array of schema
            #   - additionalItems = MUST BE IGNORED
            # - items: list[schema] = tuple of schemas
            #   - additionalItems: schema = remainder
            if "unevaluatedItems" in schema:
                log.warning(f"TODO handle unevaluatedItems")
                # quick approximate fix in one case
                # TODO move to simplify?
                if "additionalItems" not in schema:
                    schema["additionalItems"] = schema["unevaluatedItems"]
                    del schema["unevaluatedItems"]

            # change <= 8 syntax to >= 9 to streamline translation in the next block
            if "additionalItems" in schema:
                assert "prefixItems" not in schema  # <= 8 vs > 8
                if "items" in schema:
                    items = schema["items"]
                    if isinstance(items, list):
                        schema["prefixItems"] = items
                        schema["items"] = schema["additionalItems"]
                    else:
                        # TODO add to simplify
                        log.warning("ignoring additionalItems because items is a schema")
                        assert isinstance(items, (bool, dict))
                else:
                    log.warning("ignoring additionalItems with empty items")
                    # schema["items"] = schema["additionalItems"]
                del schema["additionalItems"]
            elif "items" in schema and isinstance(schema["items"], list):
                assert "prefixItems" not in schema
                schema["prefixItems"] = schema["items"]
                del schema["items"]

            # from 8:
            # - prefixItems: array[schema] = tuple
            # - items: schema = remainder
            # - unevaluatedItems: schema = try again if it fails
            if "prefixItems" in schema:
                doubt(only(schema, "type", "prefixItems", "items", "minItems", "maxItems",
                           "uniqueItems", *IGNORE),
                      f"array props with prefixItems at [{spath}]", strict)
                # var-tuple
                vpi = schema["prefixItems"]
                assert isinstance(vpi, list), f"list prefixItems at [{spath}]"
                model = [
                    schema2model(s, lid or url, path + (("prefixItems", i), ), defs, strict, fix, False, resilient)
                        for i, s in enumerate(vpi)
                ]
                if "items" in schema:
                    # prefixItems + items means extensions
                    if isinstance(schema["items"], bool):
                        if schema["items"]:
                            if ">=" not in constraints:
                                constraints[">="] = 0
                            model.append("$ANY")
                        else:  # no extensions allowed
                            if ">=" not in schema:
                                constraints[">="] = 0
                            if "<=" not in schema or constraints["<="] > len(model):
                                constraints["<="] = len(model)
                            return buildModel(model, constraints, defs, sharp, is_root)
                    # items is a schema
                    if ">=" not in constraints:
                        constraints[">="] = 0
                    model.append(schema2model(schema["items"], lid or url, path + ("items", ),
                                              defs, strict, fix, False, resilient))
                    return buildModel(model, constraints, defs, sharp, is_root)
                else:
                    if ">=" not in constraints:
                        constraints[">="] = 0
                    model.append("$ANY")
                    return buildModel(model, constraints, defs, sharp, is_root)
            elif "items" in schema:
                # items without prefixItems
                # TODO try merging with contains next?
                doubt(only(schema, "type", "items", "minItems", "maxItems", "uniqueItems",
                           "contains", *IGNORE), f"array props with items at [{spath}]", strict)
                model = [
                    schema2model(schema["items"], lid or url, path + ("items", ), defs, strict, fix, False, resilient)
                ]
                if "contains" in schema:
                    model = {
                        "@": model,
                        ".in": schema2model(
                            schema["contains"], lid or url, path + ("contains", ), defs, strict, fix, False, resilient
                        )
                    }
                return buildModel(model, constraints, defs, sharp, is_root)
            elif "contains" in schema:
                assert only(schema, "type", "contains", "minContains", "maxContains",
                            "uniqueItems", *IGNORE), f"array props for containts[{spath}]"
                # NOTE contains is not really supported in jm v2, or rather as an extension
                model = {
                    "@": ["$ANY"],
                    ".in": schema2model(schema["contains"], lid or url, path + ("contains", ), defs, strict, fix, False, resilient)
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
                # common misplacements, but not on a meta-schema!
                if not strict and "properties" in schema and isinstance(schema["properties"], dict):
                    properties = schema["properties"]
                    if not is_probable_meta_schema(properties):
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
                       "unevaluatedProperties", *IGNORE),
                  f"object properties at [{spath}]", strict)

            # build model
            constraints = {}
            model = {}
            ands = []

            if "minProperties" in schema and "maxProperties" in schema and \
                    schema["minProperties"] == schema["maxProperties"]:
                ival = schema["maxProperties"]
                assert isinstance(ival, int), f"int # props at [{spath}] ({tname(ival)})"
            else:
                if "minProperties" in schema:
                    mini = schema["minProperties"]
                    if type(mini) is float:
                        assert mini == int(mini), f"int prop length at [{spath}]"
                        mini = int(mini)
                    assert type(mini) is int, f"int min props at [{spath}] ({tname(mini)})"
                    if mini > 0:
                        constraints[">="] = mini
                    # else ignore
                if "maxProperties" in schema:
                    maxi = schema["maxProperties"]
                    if type(maxi) is float:
                        assert maxi == int(maxi), f"int prop length at [{spath}]"
                        maxi = int(maxi)
                    assert type(maxi) is int, f"int max props at [{spath}] ({tname(maxi)})"
                    if maxi > 0:
                        constraints["<="] = maxi
                    else:  # maxi == 0
                        constraints["="] = maxi
                        if ">=" in constraints:
                            del constraints[">="]

            # just remove empty patternProperties
            if "patternProperties" in schema and not schema["patternProperties"]:
                del schema["patternProperties"]

            # pre-compiled patterns, to be combined later on with properties and additionalProperties
            pattern_props = {}

            if "patternProperties" in schema:

                # schema pattern:
                # S = { props: { x: X }, patprops: { p: P, … }, aprops: A }
                #
                # explicit multipass model:
                # m(S) = { &: [ { x: m(X), /p/: any, "": A }, { /p/: m(P), "": any }, … ] }
                #
                # the point is to check aprops only if props and patterns did not match
                # and to cumulate patterns

                pats = schema["patternProperties"]
                assert isinstance(pats, dict), f"dict pattern props at [{spath}]"

                pattern_props = {
                    f"/{pp}/": schema2model(ps, lid or url, path + (("patternProperties", pp), ),
                                            defs, strict, fix, False, resilient)
                        for pp, ps in pats.items()
                }

                assert len(pattern_props) == len(pats)

            # default property name filter is any string
            pnames = ""

            if "propertyNames" in schema:
                pn = schema["propertyNames"]

                if isinstance(pn, bool):
                    if pn:
                        pn = {"type": "string"}
                    else:  # not feasible
                        pn = {"type": []}
                assert isinstance(pn, dict)

                # TODO for other cases, we could create a new reference
                if not only(pn, "pattern", "type", "format", "minLength", "maxLength", "const", "enum", *IGNORE):
                    log.warning(f"props for prop names at [{spath}]")

                # if given a type, it must be string
                if "type" in pn:
                    if pn["type"] == []:
                        pnames = "$NONE"
                    else:
                        assert pn["type"] == "string", f"unexpected prop name type {pn['type']} at [{spath}]"
                else:
                    pnames = ""

                if only(pn, "type", *IGNORE):
                    pass
                elif only(pn, "const", "type", *IGNORE) and "const" in pn:
                    cst = pn["const"]
                    if isinstance(cst, str):
                        pnames = f"?{cst}"
                    else:  # resilient
                        pnames = "$NONE"
                elif only(pn, "enum", "type", *IGNORE) and "enum" in pn:
                    enums = list(filter(lambda s: isinstance(s, str), pn["enum"]))
                    if enums:
                        pnames = f"/^({'|'.join(re.escape(s) for s in enums)})$/"
                    else:  # empty list
                        pn = "$NONE"
                elif only(pn, "pattern", "type", *IGNORE) and "pattern" in pn:
                    pat = pn["pattern"]
                    assert isinstance(pat, str), f"pattern is string at [{spath}]"
                    pnames = f"/{pat}/"
                elif only(pn, "format", "type", *IGNORE) and "format" in pn:
                    fmt = pn["format"]
                    assert isinstance(fmt, str)  # pyright
                    pnames = format2model(fmt)
                else:  # general case with a reference
                    fname: str
                    count = 0
                    while (fname := f"_pname_{count}_") in defs:
                        count += 1
                    defs[fname] = schema2model(pn, lid or url, path + ("propertyNames",), defs, strict, fix, False, resilient)
                    pnames = "$" + fname

            # build expected properties
            if "properties" in schema:
                props = schema["properties"]
                required = schema.get("required", [])
                assert isinstance(props, dict), f"dict properties [{spath}]"
                for k, v in props.items():
                    if k in required:
                        model[f"_{k}"] = \
                            schema2model(v, lid or url, path + (("properties", f"_{k}"), ), defs, strict, fix, False, resilient)
                    else:
                        model[f"?{k}"] = \
                            schema2model(v, lid or url, path + (("properties", f"?{k}"), ), defs, strict, fix, False, resilient)
            elif "required" in schema:
                # required without properties
                doubt(only(schema, "type", "required", "maxProperties", "minProperties",
                           "patternProperties", *IGNORE), f"object props at [{spath}]", strict)
                required = schema["required"]
                assert isinstance(required, list) and all(isinstance(s, str) for s in required)
                model[""] = "$ANY"
                model.update({ f"_{k}": "$ANY" for k in required })
                # what about other props?

            # append misc props
            if "additionalProperties" in schema:
                ap = schema["additionalProperties"]
                if isinstance(ap, bool):
                    if ap:
                        model[""] = "$ANY"
                    # else nothing else is allowed
                    # model[""] = "$NONE"
                elif isinstance(ap, dict):
                    model[""] = schema2model(ap, lid or url, path + ("additionalProperties", ),
                                             defs, strict, fix, False, resilient)
                else:
                    assert False, f"not implemented yet at [{spath}]"
            elif "" not in model:  # JS default is open
                model[""] = "$ANY"

            # combine pattern props and prop names to mimic the expected semantics, at a cost…
            if pattern_props or pnames not in ("", "$ANY", "$STRING"):
                ands = []

                for pp in sorted(pattern_props.keys()):
                    # add to main model to mask additionalProperties
                    # FIXME not needed in some cases?
                    model[pp] = "$ANY"
                    # and check the pattern independently
                    ands.append({ pp: pattern_props[pp], "": "$ANY" })

                # property names must be checked independently
                if pnames not in ("", "$ANY", "$STRING"):
                    if pnames == "$NONE":
                        ands.append({})
                    else:
                        ands.append({ pnames: "$ANY" })

                model = { "&": [ model ] + ands }

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

# where to find schemas and models
GH = "https://raw.githubusercontent.com"
SS = "https://json.schemastore.org"
# JM = f"{GH}/clairey-zx81/json-model/main/models"
JM = "https://json-model.org/models"

# Schema $id/id to Model URL
ID2MODEL: dict[str, tuple[str, str]] = {
    # JSON Schema drafts
    "http://json-schema.org/draft-04/schema": (
        f"{JM}/json-schema-draft-04.model.json",
        f"{JM}/json-schema-draft-04-fuzzy.model.json",
    ),
    "http://json-schema.org/draft-06/schema": (
        f"{JM}/json-schema-draft-06.model.json",
        f"{JM}/json-schema-draft-06-fuzzy.model.json",
    ),
    "http://json-schema.org/draft-07/schema": (
        f"{JM}/json-schema-draft-07.model.json",
        f"{JM}/json-schema-draft-07-fuzzy.model.json",
    ),
    "https://json-schema.org/draft/2019-09/schema": (
        f"{JM}/json-schema-draft-2019-09.model.json",
        f"{JM}/json-schema-draft-2019-09-fuzzy.model.json",
    ),
    "https://json-schema.org/draft/2020-12/schema": (
        f"{JM}/json-schema-draft-2020-12.model.json",
        f"{JM}/json-schema-draft-2020-12-fuzzy.model.json",
    ),
    # Miscellaneous models
    f"{GH}/ansible/ansible-lint/main/src/ansiblelint/schemas/meta.json": (
        f"{JM}/ansiblelint-meta.model.json",
        f"{JM}/ansiblelint-meta.model.json",
    ),
    "https://geojson.org/schema/GeoJSON.json": (
        f"{JM}/geo.model.json",
        f"{JM}/geo.model.json",
    ),
    f"{SS}/lazygit.json": (
        f"{JM}/lazygit.model.json",
        f"{JM}/lazygit.model.json",
    ),
    "https://spec.openapis.org/oas/3.1/schema/2022-10-07": (
        f"{JM}/openapi-311.model.json",
        f"{JM}/openapi-311.model.json",  # TODO fuzzy
    ),
    "sha3:58df1e36909f3f8033f4da3e9a6179f3d3e53c51501d7f14a557e34ecef988e1": (
        f"{JM}/cypress.model.json",
        f"{JM}/cypress.model.json",
    )
}

# add ~# versions
for k in list(ID2MODEL.keys()):
    if k.endswith("/schema"):
        ID2MODEL[k + "#"] = ID2MODEL[k]

def schema2id(schema: JsonSchema, keep_format: bool = True) -> str:
    """Generate a (probably) unique Id for a schema structure."""

    # copy
    schema = copy.deepcopy(schema)

    # cleanup non essential stuff
    def nocomment(schema: JsonSchema, _: SchemaPath) -> bool:
        if isinstance(schema, dict):
            for p in ("$comment", "title", "description", "default",
                      "examples", "readOnly", "writeOnly", "deprecated"):
                if p in schema:
                    del schema[p]
            if not keep_format and "format" in schema:
                del schema["format"]
            return True
        return False

    recurseSchema(schema, "", flt=nocomment)

    # hash serialized json
    serial = json.dumps(schema, sort_keys=True)
    shid = "sha3:" + hashlib.sha3_256(serial.encode("UTF-8")).hexdigest()

    log.info(f"schema id: {shid}")
    return shid

def schema_to_model(
            schema: JsonSchema, schema_name: str,
            typer: bool = False, simpler: bool = False, fix: bool = True, modernize: bool = True,
            use_id: bool = False, strict: bool = True, resolve: bool = True,
            resilient: bool = False, cache: str|None = None, version: int = 0,
            mapping: dict[str, str] = {}, level: int = logging.INFO,
        ):
    """Convert a JSON Schema to a JSON Model."""
    log.setLevel(level)
    rec_log.setLevel(level)
    reset()
    model = None
    if use_id and isinstance(schema, dict):
        sid = (schema["$id"] if "$id" in schema else
               schema["id"] if "id" in schema else
               schema2id(schema))
        if sid in ID2MODEL:
            log.info(f"using predefined model for {sid}")
            model = f"${ID2MODEL[sid][0 if strict else 1]}"
        # else unknown id, proceed
    if model is None:
        try:
            if resolve and isinstance(schema, dict):
                schema = resolveExternalRefs(schema, version=version, cache=cache,
                    modernize=modernize, mapping=mapping, level=level,
                )
            if typer and isinstance(schema, dict):
                log.debug("typing schema")
                schema = computeTypes(schema)
            if simpler and isinstance(schema, dict):
                log.debug("simplifying schema")
                scopeDefs(schema, version=version, level=level)
                url = schema.get("$id", ".")
                assert isinstance(url, str)
                schema = simplifySchema(schema, url, sversion=version, level=level)
            # then actually convert to model
            if level == logging.DEBUG:
                log.debug(f"convert in: {json.dumps(schema, indent=2)}")
            model = schema2model(schema, ".", strict=strict, fix=fix, resilient=resilient)
            if level == logging.DEBUG:
                log.debug(f"model: {json.dumps(model, indent=2)}")
        except BaseException as e:
            log.error(f"schema to model conversion for {schema_name} failed: {e}")
            if resilient:
                model = "$ANY"
            raise e
    return model
