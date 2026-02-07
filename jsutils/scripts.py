import sys
from typing import Any
import copy
import json
import hashlib
import logging
import argparse
import tempfile
import subprocess
from importlib.metadata import version as pkg_version

logging.basicConfig()

from .schemas import Schemas
from .utils import log, JSUError, JsonSchema
from .recurse import hasDirectRef, recurseSchema
from .inline import inlineRefs
from .simplify import simplifySchema, scopeDefs
from .stats import json_schema_stats, json_metrics, normalize_ods
from .convert import schema_to_model

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

    ap = argparse.ArgumentParser(
        prog="jsu-inline",
        description="Inline references in a JSON Schema",
    )
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

    ap = argparse.ArgumentParser(
        prog="jsu-simpler",
        description="Simplify JSON Schema while preserving its semantics",
    )
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

    ap = argparse.ArgumentParser(
        prog="jsu-check",
        description="Check JSON values against a JSON Schema using various implementations",
    )
    ap_common(ap)
    ap.add_argument("--draft", "-D", default="2020-12", help="JSON Schema draft")
    ap.add_argument("--engine", "-e", choices=["jmc", "jsonschema", "jschon"], default="jmc",
                    help="select JSON Schema implementation, default is 'jmc'")
    ap.add_argument("--force", action="store_true", help="accept any JSON as a schema")
    ap.add_argument("--pass-through", action="store_true", default=False,
                    help="revert to pass through on compilation error")
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

        elif args.engine == "jsonschema":
            import jsonschema
            schema = jsonschema.Draft202012Validator(
                jschema, format_checker=jsonschema.FormatChecker())

            def check(data):
                errors = list(e.message for e in schema.iter_errors(data))
                return { "passed": len(errors) == 0, "errors": errors }

        elif args.engine == "jmc":
            import json_model
            jmodel = schema_to_model(jschema, args.schema)
            checker = json_model.model_checker_from_json(jmodel)

            def check(data):
                errors = []
                ok = checker(data, "", errors)
                return { "passed": ok, "errors": None if ok else errors}

    except Exception as e:
        if args.debug:
            log.error(e, exc_info=not args.quiet)
        if args.pass_though:
            log.error(f"{args.schema}: SCHEMA COMPILATION ERROR ({e})")
        else:
            print(f"{args.schema}: SCHEMA COMPILATION ERROR ({e})")
            sys.exit(5)

        def check(data):
            return { "passed": True, "errors": "unchecked value is accepted" }

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

    ap = argparse.ArgumentParser(
        prog="jsu-stats",
        description="Lint a JSON Schema",
    )
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

    ap = argparse.ArgumentParser(
        prog="jsu-pretty",
        description="Prettyprint JSON Schema",
    )
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

def jsu_model():

    ap = argparse.ArgumentParser(
        prog="jsu-model",
        description="Convert JSON Schema to JSON Model",
    )
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
            model = schema_to_model(
                schema, fn,
                use_id=args.id, strict=args.strict, fix=args.fix, simpler=False,
            )
        except Exception as e:
            log.error(e, exc_info=args.debug)
            errors += 1
            model = {"ERROR": str(e)}
        print(json.dumps(model, sort_keys=args.sort_keys, indent=args.indent))

    sys.exit(1 if errors else 0)

def jsu_compile():

    ap = argparse.ArgumentParser(
        prog="jsu-compile",
        description="Compile JSON Schema: generate checkers in various languages",
    )
    arg = ap.add_argument
    ap_common(ap)
    arg("--id", action="store_true", default=False, help="enable $id lookup")
    arg("--no-id", dest="id", action="store_false", help="disable $id lookup")
    arg("--strict", action="store_true", default=True, help="reject doubtful schemas")
    arg("--loose", dest="strict", action="store_false", help="accept doubtful schemas")
    arg("--fix", "-F", action="store_true", default=True, help="fix common schema issues")
    arg("--no-fix", "-nF", dest="fix", action="store_false", help="do not fix common schema issues")
    arg("schema", default="-", help="schema to process")
    arg("others", nargs="*", help="jmc backend options and arguments")
    args = ap.parse_args()

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    if args.version:
        print(__version__)
        sys.exit(0)

    # intermediate model
    model = None

    try:
        schema = json.load(open(args.schema) if args.schema != "-" else sys.stdin)
        model = schema_to_model(
            schema, args.schema,
            use_id=args.id, strict=args.strict, fix=args.fix, simpler=True
        )
    except Exception as e:
        log.error(f"schema to model conversion for {args.schema} failed")
        log.error(e, exc_info=args.debug)
        sys.exit(1) # conversion failed

    # TODO
    # - use standard input with jmc?
    # - skip command and call jmc internal machinery directly in some cases?

    # compile intermediate model through a temporary file
    with tempfile.NamedTemporaryFile(suffix=".model.json") as tmp:

        smodel = json.dumps(model, sort_keys=args.sort_keys, indent=args.indent)

        if args.debug:
            log.debug(f"intermediate model: {smodel}")

        tmp.write(smodel.encode("UTF8"))
        tmp.flush()

        # launch jmc
        done = subprocess.run(["jmc", "--model", tmp.name, "--no-predef"] + args.others)

        # exit status
        if done.returncode:
            log.error(f"backend jmc process return code: {done.returncode}")
        sys.exit(done.returncode)

def jsu_runner():

    ap = argparse.ArgumentParser(
        prog="jsu-test-runner",
        description="Test runner for JSON Schema Test Suite",
    )
    arg = ap.add_argument
    ap_common(ap)
    arg("--dump", default=False, action="store_true", help="show generated model as debug")
    arg("--no-dump", action="store_false", help="do not show generated model as debug")
    arg("cases", nargs="*", help="test cases to process")
    args = ap.parse_args()

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    import json_model

    CASES_MODEL = [
        {
            "description": "",
            "?specification": [ {"?core": "", "?quote": ""} ],
            "schema": "$ANY",
            "tests": [
                {
                    "description": "",
                    "data": "$ANY",
                    "valid": True
                }
            ]
        }
    ]

    check_cases = json_model.model_checker_from_json(CASES_MODEL)

    # stats counters
    n_args, n_cases, n_cases_passed, n_tests, n_tests_passed, n_errors = 0, 0, 0, 0, 0, 0

    for fname in args.cases:
        n_args += 1
        try:
            # load and sanity check
            cases = json.loads(open(fname).read())
            assert check_cases(cases)

            for ic, case in enumerate(cases):

                scase = f"{fname}[{ic}]"

                n_cases += 1
                n_tests += len(case["tests"])
                description = case["description"]

                log.info(f"considering {scase}: {description}")

                try:
                    # TODO set options
                    model = schema_to_model(case["schema"], scase, strict=False, fix=False)
                    if args.dump:
                        log.debug(f"model: {model}")
                    checker = json_model.model_checker_from_json(model)
                    n_tests_ok = 0

                    for it, test in enumerate(case["tests"]):
                        try:
                            if checker(test["data"]) == test["valid"]:
                                n_tests_passed += 1
                                n_tests_ok += 1
                            else:
                                log.warning(f"unexpected result on {scase}[{it}]: {test['description']}")
                        except BaseException as e:
                            n_errors += 1
                            if args.debug:
                                log.error(e, exc_info=args.debug)
                            log.error(f"case {description}/{test['description']}: FAILED")

                    if n_tests_ok == len(case["tests"]):
                        n_cases_passed += 1

                except BaseException as e:
                    n_errors += 1
                    if args.debug:
                        log.error(e, exc_info=args.debug)
                    log.error(f"case {scase} ({description}): FAILED")

        except BaseException as e:
            n_errors += 1
            if args.debug:
                log.error(e, exc_info=args.debug)
            log.error(f"cases {fname}: FAILED")

    # final report
    print(f"files={n_args} cases={n_cases} tests={n_tests} errors={n_errors}")
    if n_tests > 0:
        print(f"correct tests: {n_tests_passed} ({100.0 * n_tests_passed /n_tests :.1f}%)")
    if n_cases > 0:
        print(f"correct cases: {n_cases_passed} ({100.0 * n_cases_passed /n_cases :.1f}%)")
