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

    log.setLevel(logging.DEBUG if args.debug else logging.INFO)

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

    log.setLevel(logging.DEBUG if args.debug else logging.INFO)

    for fn in args.schemas:
        log.debug(f"considering file: {fn}")
        schema = json.load(open(fn))
        if isinstance(schema, dict):
            schema = simplifySchema(schema, schema.get("$id", "."))

        print(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False))


def jsu_check():
    import jschon

    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", "-d", action="store_true", help="debug mode")
    ap.add_argument("--version", "-v", default="2020-12", help="JSON Schema version")
    ap.add_argument("schema", type=str, help="JSON Schema")
    ap.add_argument("values", nargs="*", help="values to match against schema")
    args = ap.parse_args()

    jschon.create_catalog(args.version)
    log.setLevel(logging.DEBUG if args.debug else logging.INFO)

    with open(args.schema) as f:
        schema = jschon.JSONSchema(json.load(f))

    for fn in args.values:
        with open(fn) as f:
            data = json.load(f)
        res = schema.evaluate(jschon.JSON(data))
        if res.passed:
            log.info(f"{fn}: ok")
        else:
            log.error(f"{fn}: KO")
            log.error(json.dumps(res.output('basic'), indent=2))
