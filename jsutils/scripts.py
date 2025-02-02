import json
import argparse
import logging
import copy

logging.basicConfig()

from .schemas import Schemas
from .utils import log, JSUError
from .recurse import hasDirectRef
from .inline import inlineRefs
from .simplify import simplifySchema


def jsu_inline():
    """Inline command entry point."""

    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", "-d", action="store_true", help="debug mode")
    ap.add_argument("--map", "-m", action="append", help="url local mapping")
    ap.add_argument("schemas", nargs="*", help="schemas to inline")
    args = ap.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)

    schemas = Schemas()
    schemas.addProcess(lambda s, u: inlineRefs(s, u, schemas))

    if args.map:
        for m in args.map:
            url, target = m.split(" ", 1)
            schemas.addMap(url, target)

    for fn in args.schemas:
        log.debug(f"considering file: {fn}")
        schema = json.load(open(fn))
        if isinstance(schema, bool):
            inlined = schema
        elif isinstance(schema, dict):
            url = schema.get("$id", fn)
            schemas.store(url, schema)

            # cleanup definitions
            inlined = copy.deepcopy(schemas.schema(url, "#"))
            if isinstance(inlined, dict) and "$defs" in inlined and not hasDirectRef(inlined, url):
                del inlined["$defs"]
        else:
            raise JSUError(f"invalid JSON Schema: {fn}")

        print(json.dumps(inlined, indent=2, sort_keys=True, ensure_ascii=False))


def jsu_simpler():

    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", "-d", action="store_true", help="debug mode")
    ap.add_argument("schemas", nargs="*", help="schemas to inline")
    args = ap.parse_args()

    if args.debug:
        log.setLevel(logging.DEBUG)

    for fn in args.schemas:
        log.debug(f"considering file: {fn}")
        schema = json.load(open(fn))
        if isinstance(schema, dict):
            schema = simplifySchema(schema, schema.get("$id", "."))

        print(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False))
