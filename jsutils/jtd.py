#
# Convert JTD (JSON Type Definition) to JSON Model
#

import argparse
import copy
import json
import sys

from .utils import Jsonable

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
    model = {}
    if root:
        model |= { "~": "https://json-model.org/models/json-model" }
    assert isinstance(jtd, dict)
    if "definitions" in jtd:
        assert root, "definitions only at root"
        defs = jtd["definitions"]
        assert isinstance(defs, dict)
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
    """JSON Type Definition to JSON Schema conversion."""

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

    ap = argparse.ArgumentParser(
        prog="jsu-jtd",
        description="Convert JSON Type Definition to JSON Schema or JSON Model"
    )
    arg = ap.add_argument
    arg("--output", "-o", type=str, default="-", help="Output file, default stdout")
    arg("--format", "-f", choices=["s", "m"], default=None, help="Output format: s=schema, m=model")
    arg("jtd", default="-", nargs="?", help="File to convert")
    args = ap.parse_args(xargs)

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

    output = sys.stdout if args.output == "-" else open(args.output, "w")

    jms = _jtd2jm(jtd, True) if args.format == "m" else _jtd2js(jtd, True)

    print(json.dumps(jms), file=output, flush=True)
    output.close()

    return 0
