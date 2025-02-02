import sys
import json
import argparse
import logging

logging.basicConfig()

from jsutils.schemas import Schemas
from jsutils.utils import log
from jsutils.inline import inlineRefs

def jsu_inline():
    """Command entry point."""
    schemas = Schemas()
    # schemas.addMap(".", ".")

    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", "-d", action="store_true", help="debug mode")
    ap.add_argument("--map", "-m", action="append", help="url local mapping")
    ap.add_argument("schema", type=str, help="schema to inline")
    args = ap.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)

    if args.map:
        for m in args.map:
            url, target = m.split(" ", 1)
            schemas.addMap(url, target)

    log.debug(f"considering file: {args.schema}")
    schema = json.load(open(args.schema))
    if isinstance(schema, bool):
        inlined = schema
    elif isinstance(schema, dict):
        url = schema.get("$id", args.schema)
        schemas.store(url, schema)
        inlined = inlineRefs(schema, url, schemas)
        if isinstance(inlined, dict) and "$defs" in inlined:
            del inlined["$defs"]
    else:
        raise utils.JSUError("invalid JSON Schema")

    json.dump(inlined, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
