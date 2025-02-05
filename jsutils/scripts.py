from typing import Any
import copy
import json
import hashlib
import logging
import argparse

logging.basicConfig()

from .schemas import Schemas
from .utils import log, JSUError
from .recurse import hasDirectRef
from .inline import inlineRefs
from .simplify import simplifySchema
from .stats import json_schema_stats, json_metrics, normalize_ods


def ap_common(ap, with_json=True):
    ap.add_argument("--debug", "-d", action="store_true", help="debug mode")
    if with_json:
        ap.add_argument("--indent", "-i", type=int, default=2, help="json indentation")
        ap.add_argument("--sort-keys", "-s", default=True, action="store_true", help="json sort keys")
        ap.add_argument("--no-sort-keys", dest="sort_keys", action="store_false", help="json sort keys")
        ap.add_argument("--ascii", "-a", type=bool, default=False, help="json ensure ascii")
        ap.add_argument("--no-ascii", dest="ascii", action="store_false", help="no json ensure ascii")


def json_dumps(j: Any, args):
    return json.dumps(j, indent=args.indent, sort_keys=args.sort_keys, ensure_ascii=args.ascii)


def jsu_inline():
    """Inline command entry point."""

    ap = argparse.ArgumentParser()
    ap_common(ap)
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

        print(json_dumps(inlined, args))


def jsu_simpler():

    ap = argparse.ArgumentParser()
    ap_common(ap)
    ap.add_argument("schemas", nargs="*", help="schemas to inline")
    args = ap.parse_args()

    log.setLevel(logging.DEBUG if args.debug else logging.INFO)

    for fn in args.schemas:
        log.debug(f"considering file: {fn}")
        schema = json.load(open(fn))
        if isinstance(schema, dict):
            schema = simplifySchema(schema, schema.get("$id", "."))

        print(json_dumps(schema, args))


def jsu_check():
    import jschon

    ap = argparse.ArgumentParser()
    ap_common(ap)
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
            log.error(json_dumps(res.output('basic'), args))


def shash(s: str):
    return hashlib.sha3_256(s.encode()).hexdigest()[:20]


def jsu_stats():

    ap = argparse.ArgumentParser()
    ap_common(ap)
    ap.add_argument("schemas", nargs="*", help="JSON Schema to analyze")
    args = ap.parse_args()

    log.setLevel(logging.DEBUG if args.debug else logging.INFO)

    for fn in args.schemas:
        log.info(f"considering: {fn}")
        with open(fn) as f:
            try:
                # raw data and its hash
                data = f.read()
                jdata = json.loads(data)

                # JSON Schema specific stats
                stats = json_schema_stats(jdata)
                small: dict[str, Any] = { k: v for k, v in stats.items() if v or isinstance(v, bool) }

                # basic JSON structural stats
                small["<json-metrics>"] = json_metrics(jdata)

                # normalized version with its hash
                normalize_ods(fn, jdata)  # OpenDataSoft generated schemas
                normed = json.dumps(jdata, sort_keys=True, indent=None, ensure_ascii=True)
                small["<normed-hash>"] = shash(normed)

                small["<input-file>"] = fn
                small["<file-hash>"] = shash(data)

                print(json_dumps(small, args))

            except Exception as e:
                log.error(f"{fn}: {e}", exc_info=True)
