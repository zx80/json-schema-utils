#
# Convert JTD (JSON Type Definition) to JSON Model or JSON Schema
#

import argparse
import copy
import json
import logging
import sys
import traceback

from .utils import Jsonable, log

#
# JTD Utils
#
# NOTE about Claude Test (Sonnet 5 on 2026-08-27)
#
# - prompt: Generate a Python script which checks the validity of a JSON Type Definition (see RFC 8927) in a file.
# - code generated in about a minute
# - code over twice as big (260 lines), partly because of indentation rules, mostly because of heavy style
# - code proceeds to collect "all" errors, which is debatable
# - code in a class with methods for each node check, no "match" syntax used
#

# expected JTD schemas property names

JTD_SHARED_PROPS = {"metadata", "nullable"}

JTD_PROPS: dict[str, set[str]] = {
    "empty": set(),
    "ref": {"ref"},
    "type": {"type"},
    "enum": {"enum"},
    "elements": {"elements"},
    "properties": {"properties", "optionalProperties", "additionalProperties"},
    "values": {"values"},
    "discriminator": {"discriminator", "mapping"}
}

def jtd_category(schema: Jsonable) -> str:
    """Return JTD schema node category."""
    assert isinstance(schema, dict)
    scat = set(schema) & set(JTD_PROPS)
    if scat:  # non empty
        return scat.pop()
    elif "optionalProperties" in schema:
        return "properties"
    else:
        return "empty"

# TODO check for potential infinite recursion through ref?
def _valid_jtd_schema(schema: Jsonable, root: bool, defs: set[str], path: list[str]) -> bool:
    """Check JTD schema validity recursively."""
    spath = "." + ".".join(path)
    assert isinstance(schema, dict), f"JTD schema is an object at {spath}"
    category = jtd_category(schema)
    assert all(isinstance(p, str) for p in schema), f"JTD schema uses string props at {spath}"
    ok_props = JTD_SHARED_PROPS | JTD_PROPS[category] | ({"definitions"} if root else set())
    assert set(schema) <= set(ok_props), f"JTD schema has valid category properties at {spath}"
    # commons
    if "metadata" in schema:
        metadata = schema["metadata"]
        assert isinstance(metadata, dict), f"JTD metadata is an object at {spath}.metadata"
        # TODO more?
    if "nullable" in schema:
        assert isinstance(schema["nullable"], bool), f"JTD nullable is a boolean at {spath}.nullable"
    # per category
    match category:
        case "empty":
            pass
        case "ref":
            ref = schema["ref"]
            assert isinstance(ref, str) and ref in defs, f"JTD ref target is defined at {spath}.ref"
        case "type":
            stype = schema["type"]
            assert isinstance(stype, str) and stype in TYPE_MODEL, f"JTD type is known at {spath}.type"
        case "enum":
            enum = schema["enum"]
            assert isinstance(enum, list) and all(isinstance(e, str) for e in enum), f"JTD enum is a list of strings at {spath}.enum"
            assert len(enum) > 0, f"JTD enum is not empty at {spath}.enum"
        case "elements":
            elems = schema["elements"]
            assert _valid_jtd_schema(elems, False, defs, path + ["elements"]), f"JTD elements is a valid schema at {spath}.elements"
        case "properties":
            assert isinstance(schema.get("additionalProperties", False), bool), f"JTD additional properties is a boolean at {spath}.additionalProperties"
            mprops, oprops = {}, {}
            if "properties" in schema:
                mprops = schema["properties"]
                assert isinstance(mprops, dict), f"JTD properties is an object at {spath}.properties"
            if "optionalProperties" in schema:
                oprops = schema["optionalProperties"]
                assert isinstance(oprops, dict), f"JTD optional properties is an object at {spath}.optionalProperties"
            assert len(mprops.keys() & oprops.keys()) == 0, f"JTD object prop cannot be both mandatory and optional at {spath}"
            for prop, sub in (mprops | oprops).items():
                assert isinstance(prop, str) and _valid_jtd_schema(sub, False, defs, path + ["*props", prop]), "JTD object property and subschemas at {spath}.*props"
        case "values":
            assert _valid_jtd_schema(schema["values"], False, defs, path + ["values"])
        case "discriminator":
            dis, mapping = schema["discriminator"], schema["mapping"]
            assert isinstance(dis, str) and len(dis) > 0, f"JTD object tag is non empty string at {spath}.discriminator"
            assert isinstance(mapping, dict), f"JTD discriminator mapping is an object at {spath}.mapping"
            for tag, sub in mapping.items():
                lval = spath + f".mapping.{tag}"
                assert isinstance(tag, str), f"JTD mapping tag is a string at {lpath}"
                assert isinstance(sub, dict), f"JTD mapping value is an object at {lpath}"
                assert len({"properties", "optionalProperties"} & set(sub)) > 0, f"JTD mapping value is properties at {lpath}."
                assert dis not in (sub.get("properties", {}) | sub.get("optionalProperties", {})), f"JTD discriminator is set once at {lpath}"
                assert _valid_jtd_schema(sub, False, defs, path + ["mapping", tag]), f"JTD mapping value is valid at {lpath}"
                assert not sub.get("nullable", False), f"JTD mapping subschema must not be nullable at {lpath}"
        case _:
            assert False, f"JTD schema unknown category: {category} at {spath}"
    return True

def valid_jtd_schema(schema: Jsonable) -> bool:
    """Tell if JTD schema is valid."""
    try:
        assert isinstance(schema, dict), "JTD schema is an object at ."
        if "definitions" in schema:
            sdefs = schema["definitions"]
            assert isinstance(sdefs, dict), "JTD schema definitions is an object at .definitions"
            assert all(isinstance(name, str) for name in sdefs), "JTD definitions names are strings at .definitions"
            defs = set(sdefs)
            assert all(_valid_jtd_schema(subs, False, defs, ["definitions", name]) for name, subs in sdefs.items())
        else:
            defs = set()
        assert _valid_jtd_schema(schema, True, defs, [])
        return True
    except AssertionError as e:
        log.warning(f"JTD check exception: {e}")
        if log.isEnabledFor(logging.DEBUG):
            traceback.print_exception(e)
        return False

#
# JTD -> JM
#

TYPE_MODEL: dict[str, Jsonable] = {
    "boolean": True,
    "float32": "$F32",
    "float64": "$F64",
    "int8": "$I8",
    "uint8": "$U8",
    "int16": "$I16",
    "uint16": "$U16",
    "int32": "$I32",
    "uint32": "$U32",
    "string": "",
    "timestamp": "$DATETIME",
}

def _jtd2jm(jtd: Jsonable, root: bool = False) -> Jsonable:
    """JTD to JM internal recursive function."""
    model = {}
    if root:
        model |= { "~": "https://json-model.org/models/json-model" }
    assert isinstance(jtd, dict)
    if "definitions" in jtd:
        assert root, "definitions only at root"
        defs = jtd["definitions"]
        assert isinstance(defs, dict)
        assert all(isinstance(k, str) and isinstance(v, dict) for k, v in defs.items())
        model["$"] = {
            name: _jtd2jm(jtype)
                for name, jtype in defs.items()
        }
    if "metadata" in jtd:
        model["#"] = jtd["metadata"]
    smodel: Jsonable
    if "ref" in jtd:
        smodel = f"${jtd['ref']}"
    elif "type" in jtd:
        smodel = TYPE_MODEL[jtd["type"]]
    elif "enum" in jtd:
        enums = jtd["enum"]
        assert isinstance(enums, list) and len(enums) > 0
        assert all(isinstance(s, str) for s in enums) and len(set(enums)) == len(enums)
        smodel = { "|": [ f"_{s}" for s in enums ] }
    elif "elements" in jtd:
        smodel = [ _jtd2jm(jtd["elements"]) ]
    elif "values" in jtd:
        smodel = { "": _jtd2jm(jtd["values"]) }
    elif "discriminator" in jtd:
        dis = "_" + jtd["discriminator"]
        smodel = {
            "^": [
                { f"_{dis}": f"_{val}" } | _jtd2jm(jtype)
                    for val, jtype in jtd["mapping"].items()
            ]
        }
    elif "properties" in jtd or "optionalProperties" in jtd:
        smodel = {
            f"_{name}": _jtd2jm(jtype)
                for name, jtype in jtd.get("properties", {}).items()
        } | {
            f"?{name}": _jtd2jm(jtype)
                for name, jtype in jtd.get("optionalProperties", {}).items()
        }
        if jtd.get("additionalProperties", False):
            smodel[""] = "$ANY"
    else:
        smodel = "$ANY"

    if jtd.get("nullable", False):
        smodel = { "|": [ None, smodel ] }

    if model:
        if isinstance(smodel, dict):
            model.update(smodel)
        else:
            model["@"] = smodel
    else:
        model = smodel

    return model

#
# JTD -> JS
#

TYPE_SCHEMA: dict[str, Jsonable] = {
    "boolean": {"type": "boolean"},
    "float32": {"type": "number"},
    "float64": {"type": "number"},
    "int8": {"type": "integer", "minimum": -128, "maximum": 127},
    "uint8": {"type": "integer", "minimum": 0, "maximum": 255},
    "int16": {"type": "integer", "minimum": -32768, "maximum": 32767},
    "uint16": {"type": "integer", "minimum": 0, "maximum": 65535},
    "int32": {"type": "integer", "minimum": -2147483648, "maximum": 2147483647 },
    "uint32": {"type": "integer", "minimum": 0, "maximum":  4294967295},
    "string": {"type": "string"},
    "timestamp": {"type": "string", "format": "datetime"},
}

def _jtd2js(jtd: Jsonable, root: bool = False) -> Jsonable:
    """JSON Type Definition to JSON Schema conversion internal recursive function."""

    schema = {}
    if root:
        schema |= { "$schema": "https://json-schema.org/draft/2020-12/schema" }
    assert isinstance(jtd, dict)
    if "definitions" in jtd:
        assert root, "definitions only at root"
        defs = jtd["definitions"]
        assert isinstance(defs, dict)
        schema["$defs"] = {
            name: _jtd2js(jtype)
                for name, jtype in defs.items()
        }
    if "metadata" in jtd:
        schema["$comment"] = jtd["metadata"]
    if "ref" in jtd:
        schema |= { "$ref": f"#/$defs/{jtd['ref']}" }
    elif "type" in jtd:
        schema |= copy.deepcopy(TYPE_SCHEMA[jtd["type"]])
    elif "enum" in jtd:
        enums = jtd["enum"]
        assert isinstance(enums, list) and len(enums) > 0
        assert all(isinstance(s, str) for s in enums) and len(set(enums)) == len(enums)
        schema |= { "enum": enums }
    elif "elements" in jtd:
        schema |= { "type": "array", "items": _jtd2js(jtd["elements"]) }
    elif "values" in jtd:
        schema |= { "type": "object", "additionalProperties": _jtd2js(jtd["values"]) }
    elif "discriminator" in jtd:
        dis = jtd["discriminator"]
        lobjs = []
        for val, jtype in jtd["mapping"].items():
            obj = _jtd2js(jtype)  # properties
            obj["properties"][dis] = {"const": val}
            obj["required"].append(dis)
            lobjs.append(obj)
        schema |= { "type": "object", "oneOf": lobjs }
    elif "properties" in jtd or "optionalProperties" in jtd:
        schema |= {"type": "object", "properties": {}, "required": []}
        for name, jtype in jtd.get("properties", {}).items():
            schema["properties"][name] = _jtd2js(jtype)
            schema["required"].append(name)
        for name, jtype in jtd.get("optionalProperties", {}).items():
            schema["properties"][name] = _jtd2js(jtype)
        schema["additionalProperties"] = jtd.get("additionalProperties", False)
    else:  # empty
        schema |= {"type": ["null", "boolean", "integer", "number", "string", "array", "object"]}

    if jtd.get("nullable", False):
        if "const" in schema:
            schema["enum"] = [ None, schema["const"] ]
            del schema["const"]
        elif "enum" in schema:
            if None not in schema["enum"]:
                schema["enum"].append(None)
        elif "type" in schema:
            if not isinstance(schema["type"], list):
                schema["type"] = [ schema["type"] ]
            if "null" not in schema["type"]:
                schema["type"].append("null")
            if "oneOf" in schema:
                schema["oneOf"].append({"type": "null"})
        elif "$ref" in schema:
            schema["anyOf"] = [ {"type": "null"}, { "$ref": schema["$ref"] } ]
            del schema["$ref"]

    return schema

def jtd2jms(xargs: list[str]|None = None):

    logging.basicConfig()

    ap = argparse.ArgumentParser(
        prog="jsu-jtd",
        description="Convert JSON Type Definition to JSON Schema or JSON Model"
    )
    arg = ap.add_argument
    arg("--output", "-o", type=str, default="-", help="Output file, defaults to standard output")
    arg("--format", "-f", choices=["s", "m"], default=None, help="Output JSON format: s=schema, m=model")
    arg("--level", "-l", choices=["error", "warn", "info", "debug"], default="warn", help="Set verbosity level")
    arg("--debug", "-d", dest="level", action="store_const", const="debug", help="Set debug model")
    arg("--schema", "-s", dest="format", action="store_const", const="s", help="Use JSON Schema format")
    arg("--model", "-m", dest="format", action="store_const", const="m", help="Use JSON Model format")
    arg("jtd", default="-", nargs="?", help="File to convert, defaults to standard input")
    args = ap.parse_args(xargs)

    log.setLevel(logging.ERROR if args.level == "error" else
                 logging.WARNING if args.level == "warn" else
                 logging.INFO if args.level == "info" else
                 logging.DEBUG)

    if not args.format:
        if args.output.endswith(".schema.json"):
            args.format = "s"
        elif args.output.endswith(".model.json"):
            args.format = "m"
        else:
            args.format = "s"

    if args.jtd == "-":
        jtd = json.load(sys.stdin)
    else:
        with open(args.jtd) as f:
            jtd = json.load(f)

    assert valid_jtd_schema(jtd), "JTD schema is valid"

    jms = _jtd2jm(jtd, True) if args.format == "m" else _jtd2js(jtd, True)

    output = sys.stdout if args.output == "-" else open(args.output, "w")
    print(json.dumps(jms), file=output, flush=True)
    output.close()

    return 0
