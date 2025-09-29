import sys
from typing import Any
import copy
import json
import hashlib
import logging
import argparse
from importlib.metadata import version as pkg_version

logging.basicConfig()

from .schemas import Schemas
from .utils import log, JSUError, JsonSchema
from .recurse import hasDirectRef, recurseSchema
from .inline import inlineRefs
from .simplify import simplifySchema, scopeDefs
from .stats import json_schema_stats, json_metrics, normalize_ods

__version__ = pkg_version("json_schema_utils")

def ap_common(ap, with_json=True):
    ap.add_argument("--version", action="store_true", help="show version")
    ap.add_argument("--debug", "-d", action="store_true", help="debug mode")
    ap.add_argument("--quiet", "-q", action="store_true", help="quiet mode")
    if with_json:
        ap.add_argument("--indent", "-i", type=int, default=2, help="json indentation")
        ap.add_argument("--sort-keys", "-s", default=True,
                        action="store_true", help="json sort keys")
        ap.add_argument("--no-sort-keys", "-ns", dest="sort_keys",
                        action="store_false", help="json sort keys")
        ap.add_argument("--ascii", action="store_true", default=False, help="json ensure ascii")
        ap.add_argument("--no-ascii", dest="ascii", action="store_false",
                        help="no json ensure ascii")


def json_dumps(j: Any, args):
    return json.dumps(j, indent=args.indent, sort_keys=args.sort_keys, ensure_ascii=args.ascii)


def rm_suffix(s, *suffixes):
    for suffix in suffixes:
        if s.endswith(suffix):
            return s[:-len(suffix)]
    return s


def jsu_inline():
    """Inline command entry point."""

    ap = argparse.ArgumentParser()
    ap_common(ap)
    ap.add_argument("--map", "-m", action="append", help="url local mapping")
    ap.add_argument("--auto", "-a", action="store_true", help="automatic url mapping")
    ap.add_argument("schemas", nargs="*", help="schemas to inline")
    args = ap.parse_args()

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    if not args.schemas:
        args.schemas = ["-"]

    schemas = Schemas()
    schemas.addProcess(lambda s, u: inlineRefs(s, u, schemas))

    if args.map:
        for m in args.map:
            url, target = m.split(" ", 1)
            schemas.addMap(url, target)

    for fn in args.schemas:
        log.debug(f"considering file: {fn}")
        schema = json.load(open(fn) if fn != "-" else sys.stdin)
        if isinstance(schema, bool):
            inlined = schema
        elif isinstance(schema, dict):
            url = schema.get("$id", fn)
            if args.auto and url != fn:
                # https://schema.gouv.fr/stuff ./stuff(.schema.json)
                u = rm_suffix(url, ".schema.json", ".json")
                f = rm_suffix(fn, ".schema.json", ".json")
                while u and f and u[-1] == f[-1]:
                    u, f = u[:-1], f[:-1]
                if u and f:
                    log.info(f"map: {u} -> {f}")
                    schemas.addMap(u, f)

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
    ap.add_argument("schemas", nargs="*", help="schemas to simplify")
    args = ap.parse_args()

    if not args.schemas:
        args.schemas = ["-"]

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    for fn in args.schemas:
        log.debug(f"considering file: {fn}")
        schema = json.load(open(fn) if fn != "-" else sys.stdin)
        if isinstance(schema, dict):
            scopeDefs(schema)
            schema = simplifySchema(schema, schema.get("$id", "."))

        print(json_dumps(schema, args))


def jsu_check():

    from .stats import SCHEMA_KEYS

    ap = argparse.ArgumentParser()
    ap_common(ap)
    ap.add_argument("--draft", "-D", default="2020-12", help="JSON Schema draft")
    ap.add_argument("--engine", "-e", choices=["jsonschema", "jschon"], default="jsonschema",
                    help="select JSON Schema implementation")
    ap.add_argument("--force", action="store_true", help="accept any JSON as a schema")
    ap.add_argument("--test", "-t", action="store_true", help="test vector mode")
    ap.add_argument("schema", type=str, help="JSON Schema")
    ap.add_argument("values", nargs="*", help="values to match against schema")
    args = ap.parse_args()

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    try:
        with open(args.schema) if args.schema != "-" else sys.stdin as f:
            jschema = json.load(f)
    except FileNotFoundError as e:
        if args.debug:
            log.error(e, exc_info=args.debug)
        print(f"{args.schema}: FILE ERROR ({e})")
        sys.exit(1)
    except BaseException as e:
        if args.debug:
            log.error(e, exc_info=args.debug)
        print(f"{args.schema}: JSON ERROR ({e})")
        sys.exit(2)

    # sanity check…
    if not isinstance(jschema, (bool, dict)):
        print(f"{args.schema}: SCHEMA TYPE ERROR")
        sys.exit(3)
    if isinstance(jschema, dict) and not (SCHEMA_KEYS & jschema.keys()):
        if args.force:
            log.warning(f"{args.schema}: json probably not a schema")
            # go on, per spec…
        else:
            log.error(f"{args.schema}: json probably not a schema, use --force to proceed anyway")
            print(f"{args.schema}: SCHEMA ERROR - not a schema, use --force to proceed anyway")
            sys.exit(4)

    # be nice
    if isinstance(jschema, dict) and "$schema" not in jschema:
        jschema["$schema"] = f"https://json-schema.org/draft/{args.draft}/schema"

    try:
        if args.engine == "jschon":
            import jschon
            jschon.create_catalog(args.draft)
            schema = jschon.JSONSchema(jschema)

            def check(data):
                res = schema.evaluate(jschon.JSON(data))
                return { "passed": res.passed, "errors": res.output("basic") }
        else:
            import jsonschema
            schema = jsonschema.Draft202012Validator(
                jschema, format_checker=jsonschema.FormatChecker())

            def check(data):
                errors = list(e.message for e in schema.iter_errors(data))
                return { "passed": len(errors) == 0, "errors": errors }

    except Exception as e:
        if args.debug:
            log.error(e, exc_info=not args.quiet)
        print(f"{args.schema}: SCHEMA ERROR ({e})")
        sys.exit(5)

    def check_data(name: str, data, expect: bool|None) -> bool:
        res = check(data)
        okay = res["passed"]
        success = expect is None or okay == expect
        if success:
            print(f"{name}: {'PASS' if okay else 'FAIL'}")
        else:  # res != expect
            print(f"{name}: ERROR unexpected {'PASS' if okay else 'FAIL'}")
        if not okay and not args.quiet:
            log.error(json_dumps(res["errors"], args))
        return success

    nerrors = 0
    for fn in args.values:
        with open(fn) if fn != "-" else sys.stdin as f:
            try:
                data = json.load(f)
                if args.test:
                    ntests = 0
                    assert isinstance(data, list)
                    for item in data:
                        if isinstance(item, str):  # comment
                            continue
                        assert len(item) in (2, 3)
                        name = f"{fn}[{ntests}]"
                        ntests += 1
                        if len(item) == 2:
                            expect, data = item
                            case = ""
                        else:
                            expect, case, data = item
                        assert isinstance(expect, bool) and isinstance(case, str)
                        if not check_data(name, data, expect):
                            nerrors += 1
                else:
                    if not check_data(fn, data, None):
                        nerrors += 1
            except Exception as e:
                nerrors += 1
                log.debug(e, exc_info=True)
                print(f"{fn}: ERROR ({e})")


def shash(s: str):
    return hashlib.sha3_256(s.encode()).hexdigest()[:20]


def jsu_stats():

    ap = argparse.ArgumentParser()
    ap_common(ap)
    ap.add_argument("schemas", nargs="*", help="JSON Schema to analyze")
    args = ap.parse_args()

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    if not args.schemas:
        args.schemas = ["-"]

    for fn in args.schemas:
        log.info(f"considering: {fn}")
        with open(fn) if fn != "-" else sys.stdin as f:
            try:
                # raw data and its hash
                data = f.read()
                jdata = json.loads(data)

                # JSON Schema specific stats
                stats = json_schema_stats(jdata)
                small: dict[str, Any] = {
                    k: v for k, v in stats.items() if v or isinstance(v, bool)
                }

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


def jsu_pretty():

    ap = argparse.ArgumentParser()
    ap_common(ap)
    ap.add_argument("schemas", nargs="*", help="schemas to inline")
    args = ap.parse_args()

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    if not args.schemas:
        args.schemas = ["-"]

    for fn in args.schemas:
        log.debug(f"considering file: {fn}")
        schema = json.load(open(fn) if fn != "-" else sys.stdin)
        print(json_dumps(schema, args))


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

# generate an id
def schema2id(schema: JsonSchema) -> str:

    # copy
    schema = copy.deepcopy(schema)

    # cleanup non essential stuff
    def nocomment(schema: JsonSchema, _: list[str]) -> bool:
        if isinstance(schema, dict):
            for p in ("$comment", "title", "description", "default",
                      "examples", "readOnly", "writeOnly", "deprecated"):
                if p in schema:
                    del schema[p]
            return True
        return False

    recurseSchema(schema, "", flt=nocomment)

    # hash serialized json
    serial = json.dumps(schema, sort_keys=True)
    shid = "sha3:" + hashlib.sha3_256(serial.encode("UTF-8")).hexdigest()

    log.info(f"schema id: {shid}")
    return shid

# add ~# versions
for k in list(ID2MODEL.keys()):
    if k.endswith("/schema"):
        ID2MODEL[k + "#"] = ID2MODEL[k]

def jsu_model():

    from .convert import schema2model

    ap = argparse.ArgumentParser()
    arg = ap.add_argument
    ap_common(ap)
    arg("--id", action="store_true", default=False, help="enable $id lookup")
    arg("--no-id", dest="id", action="store_false", help="disable $id lookup")
    arg("--strict", action="store_true", default=True, help="reject doubtful schemas")
    arg("--loose", dest="strict", action="store_false", help="accept doubtful schemas")
    arg("--fix", "-F", action="store_true", default=True, help="fix common schema issues")
    arg("--no-fix", "-nF", dest="fix", action="store_false", help="do not fix common schema issues")
    arg("schemas", nargs="*", help="schemas to process")
    args = ap.parse_args()

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    if args.version:
        print(__version__)
        sys.exit(0)

    if not args.schemas:
        args.schemas = ["-"]

    errors = 0

    for fn in args.schemas:
        log.debug(f"considering: {fn}")
        try:
            schema = json.load(open(fn) if fn != "-" else sys.stdin)
            model = None
            if args.id and isinstance(schema, dict):
                sid = (schema["$id"] if "$id" in schema else
                       schema["id"] if "id" in schema else
                       schema2id(schema))
                if sid in ID2MODEL:
                    log.info(f"using predefined model for {sid}")
                    model = f"${ID2MODEL[sid][0 if args.strict else 1]}"
            if model is None:
                model = schema2model(schema, strict=args.strict, fix=args.fix)
        except Exception as e:
            log.error(e, exc_info=args.debug)
            errors += 1
            model = {"ERROR": str(e)}
        print(json.dumps(model, sort_keys=args.sort_keys, indent=args.indent))

    sys.exit(1 if errors else 0)
