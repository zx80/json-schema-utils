#
# Convert JTD (JSON Type Definition) to JSON Model
#

import argparse
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
        assert isinstance(dict, defs)
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
        assert all(isinstance(s, str) for s in enums)
        smodel = { "|": [ f"_{s}" for s in enums ] }
    elif "elements" in jtd:
        smodel = [ _jtd2jm(jtd["elements"]) ]
    elif "values" in jtd:
        smodel = { "": _jtd2jm(jtd["values"]) }
    elif "discriminator" in jtd:
        dis = "_" + jtd["discriminator"]
        smodel = {
            "^": [
                { dis: val } | _jtd2jm(jtype)
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
        

def jtd2jm(xargs: list[str]|None = None):

    ap = argparse.ArgumentParser(
        prog="jtd-2-jm",
        description="Convert JSON Type Description to JSON Model"
    )
    arg = ap.add_argument
    arg("--output", "-o", type=str, default="-", help="Output file")
    arg("jtd", type=str, default="-", help="File to convert")
    args = ap.parse_args(xargs)

    if args.jtd == "-":
        jtd = json.load(sys.stdin)
    else:
        with open(args.jtd) as f:
            jtd = json.load(f)

    output = sys.stdout if args.output == "-" else open(args.output)

    print(json.dumps(_jtd2jm(jtd, True)), file=output, flush=True)
