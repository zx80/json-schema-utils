import sys
from typing import Any, Callable
import copy
import json
import hashlib
import logging
import argparse
import tempfile
import subprocess
from importlib.metadata import version as pkg_version

import json_model

logging.basicConfig()

from .schemas import Schemas
from .utils import log, JSUError, JsonSchema, Jsonable, FORMAT_HINT
from .recurse import hasDirectRef, recurseSchema
from .inline import inlineRefs
from .simplify import simplifySchema, scopeDefs
from .stats import json_schema_stats, json_metrics, normalize_ods
from .convert import schema_to_model
from .resolver import Resolver
from .types import computeTypes

#
# Pedestrian extraction of the version
#
def git_hash(script: str = __file__) -> str:
    """Return some git hash for the current script."""
    # may get git hash
    try:
        from .version import HASH
        return HASH
    except:
        pass
    try:
        dirname = Path(script).parent
        return subprocess.check_output(["git", "-C", str(dirname), "rev-parse", "--short", "HEAD"]).decode("ASCII").strip()
    except Exception:
        pass
    return "<unknown>"

def get_version(with_backend: bool = False) -> str:
    """Build and return version string."""
    version = pkg_version("json_schema_utils") + " [" + git_hash() + "]"
    if with_backend:
        version += " (jmc backend " + pkg_version("json_model_compiler")  + ")"
    return version

class VersionAction(argparse.Action):
    """Show version on --version."""
    def __init__(self, *args, with_backend: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._with_backend = with_backend
    def __call__(self, *args, **kwargs):
        print(get_version(self._with_backend))
        sys.exit(0)

def ap_common(arg, with_json: bool =True, with_backend: bool = False):
    arg("--version", nargs=0, action=VersionAction, with_backend=with_backend, help="show version")
    arg("--debug", "-d", action="store_true", help="debug mode")
    arg("--quiet", "-q", action="store_true", help="quiet mode")
    if with_json:
        arg("--indent", "-i", type=int, default=2,
            help="json indentation (2)")
        arg("--sort-keys", "-s", default=True, action="store_true",
            help="sort json keys (*)")
        arg("--no-sort-keys", "-ns", dest="sort_keys", action="store_false",
            help="do not sort json keys")
        arg("--ascii", action="store_true", default=False,
            help="ensure json ascii")
        arg("--no-ascii", dest="ascii", action="store_false",
            help="do not ensure json ascii (*)")


def json_dumps(j: Any, args):
    return json.dumps(j, indent=args.indent, sort_keys=args.sort_keys, ensure_ascii=args.ascii)


def rm_suffix(s, *suffixes):
    for suffix in suffixes:
        if s.endswith(suffix):
            return s[:-len(suffix)]
    return s


def jsu_inline(xargs: list[str]|None = None) -> int:
    """Inline command entry point."""

    ap = argparse.ArgumentParser(
        prog="jsu-inline",
        description="Inline references in a JSON Schema",
    )
    arg = ap.add_argument
    ap_common(arg)
    arg("--cache", type=str, default=None, help="cache directory for remote schemas")
    arg("--map", "-m", default=[], action="append", help="url local mapping \"src=dst\"")
    arg("--auto", "-a", action="store_true", default=False, help="automatic url mapping")
    arg("schemas", nargs="*", help="schemas to inline")
    args = ap.parse_args(xargs)

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    if not args.schemas:
        args.schemas = ["-"]

    schemas = Schemas(resolver=Resolver(cache=args.cache, mapping=args.map))
    schemas.addProcess(lambda s, u: inlineRefs(s, u, schemas))

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

    return 0

def jsu_simpler(xargs: list[str]|None = None) -> int:

    ap = argparse.ArgumentParser(
        prog="jsu-simpler",
        description="Simplify JSON Schema while preserving its semantics",
    )
    arg = ap.add_argument
    ap_common(arg)
    arg("schemas", nargs="*", help="schemas to simplify")
    arg("--type", default=True, action="store_true",
        help="type schema before simplification (*)")
    arg("--no-type", dest="type", action="store_false",
        help="do not type schema before simplification")
    args = ap.parse_args(xargs)

    if not args.schemas:
        args.schemas = ["-"]

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    for fn in args.schemas:
        log.debug(f"considering file: {fn}")
        schema = json.load(open(fn) if fn != "-" else sys.stdin)
        if args.type:
            schema = computeTypes(schema)
        if isinstance(schema, dict):
            scopeDefs(schema)
            schema = simplifySchema(schema, schema.get("$id", "."), remove_all_types=True)

        print(json_dumps(schema, args))

    return 0


def jsu_check(xargs: list[str]|None = None) -> int:

    from .stats import SCHEMA_KEYS

    ap = argparse.ArgumentParser(
        prog="jsu-check",
        description="Check JSON values against a JSON Schema using various implementations",
    )
    arg = ap.add_argument
    ap_common(arg, with_backend=True)
    arg("--cache", type=str, default=None, help="cache directory for remote schemas")
    arg("--map", "-m", default=[], action="append", help="url local mapping \"src=dst\"")
    arg("--draft", "-D", default="2020-12", help="JSON Schema draft")
    arg("--engine", "-e", choices=["jmc", "jsonschema", "jschon"], default="jmc",
        help="select JSON Schema implementation, default is 'jmc'")
    arg("--force", action="store_true", help="accept any JSON as a schema")

    arg("--resilient", default=False, action="store_true", help="return something whatever")
    arg("--no-resilient", dest="resilient", action="store_false", help="may fail (*)")
    arg("--format", default=True, action="store_true", help="check formats (*)")
    arg("--no-format", dest="format", action="store_false", help="do not check formats")
    arg("--extend", default=True, action="store_true", help="use jmc extensions (*)")
    arg("--no-extend", dest="extend", action="store_false", help="do not use jmc extensions")

    arg("--pass-through", action="store_true", default=False,
        help="revert to pass through on compilation error")
    arg("--test", "-t", action="store_true", help="test vector mode")
    arg("schema", type=str, help="JSON Schema")
    arg("values", nargs="*", help="values to match against schema")
    args = ap.parse_args(xargs)

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    try:
        with open(args.schema) if args.schema != "-" else sys.stdin as f:
            jschema = json.load(f)
    except FileNotFoundError as e:
        if args.debug:
            log.error(e, exc_info=args.debug)
        print(f"{args.schema}: FILE ERROR ({e})")
        return 1
    except BaseException as e:
        if args.debug:
            log.error(e, exc_info=args.debug)
        print(f"{args.schema}: JSON ERROR ({e})")
        return 2

    # sanity check…
    if not isinstance(jschema, (bool, dict)):
        print(f"{args.schema}: SCHEMA TYPE ERROR")
        return 3

    if isinstance(jschema, dict) and not (SCHEMA_KEYS & jschema.keys()):
        if args.force:
            log.warning(f"{args.schema}: json probably not a schema")
            # go on, per spec…
        else:
            log.error(f"{args.schema}: json probably not a schema, use --force to proceed anyway")
            print(f"{args.schema}: SCHEMA ERROR - not a schema, use --force to proceed anyway")
            return 4

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
            # TODO safest options?
            resolver = Resolver(cache=args.cache, mapping=args.map)
            jmodel = schema_to_model(
                jschema, args.schema, simpler=True, typer=True, resolver=resolver
            )
            checker = json_model.model_checker_from_json(
                jmodel, predef=args.format, extend=args.extend
            )

            def check(data):
                errors = []
                ok = checker(data, "", errors)
                return { "passed": ok, "errors": None if ok else errors}

    except Exception as e:
        if args.debug:
            log.error(e, exc_info=not args.quiet)
        if args.pass_through:
            log.error(f"{args.schema}: SCHEMA COMPILATION ERROR ({e})")
        else:
            print(f"{args.schema}: SCHEMA COMPILATION ERROR ({e})")
            return 5

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

    return 1 if nerrors else 0


def shash(s: str):
    return hashlib.sha3_256(s.encode()).hexdigest()[:20]


def jsu_stats(xargs: list[str]|None = None) -> int:

    ap = argparse.ArgumentParser(
        prog="jsu-stats",
        description="Lint a JSON Schema",
    )
    arg = ap.add_argument
    ap_common(arg)
    arg("schemas", nargs="*", help="JSON Schema to analyze")
    args = ap.parse_args(xargs)

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    oops = False

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
                oops = True
                log.error(f"{fn}: {e}", exc_info=True)

    return 1 if oops else 0


def jsu_pretty(xargs: list[str]|None = None):

    ap = argparse.ArgumentParser(
        prog="jsu-pretty",
        description="Prettyprint JSON Schema",
    )
    arg = ap.add_argument
    ap_common(arg)
    arg("schemas", nargs="*", help="schemas to inline")
    args = ap.parse_args(xargs)

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    if not args.schemas:
        args.schemas = ["-"]

    for fn in args.schemas:
        log.debug(f"considering file: {fn}")
        schema = json.load(open(fn) if fn != "-" else sys.stdin)
        print(json_dumps(schema, args))

    return 0

def jsu_model(xargs: list[str]|None = None) -> int:

    ap = argparse.ArgumentParser(
        prog="jsu-model",
        description="Convert JSON Schema to JSON Model",
    )
    arg = ap.add_argument
    ap_common(arg, with_backend=True)
    arg("--cache", type=str, default=None, help="cache directory for remote schemas")
    arg("--map", "-m", default=[], action="append", help="url local mapping \"src=dst\"")

    arg("--id", action="store_true", default=False,
        help="enable $id lookup")
    arg("--no-id", dest="id", action="store_false",
        help="disable $id lookup (*)")
    arg("--strict", action="store_true", default=False,
        help="reject doubtful schemas")
    arg("--no-strict", dest="strict", action="store_false",
        help="accept doubtful schemas (*)")
    arg("--fix", "-F", action="store_true", default=True,
        help="fix common schema issues (*)")
    arg("--no-fix", "-nF", dest="fix", action="store_false",
        help="do not fix common schema issues")
    arg("--resilient", default=False, action="store_true",
        help="return something whatever")
    arg("--no-resilient", dest="resilient", action="store_false",
        help="may fail (*)")
    arg("--type", default=True, action="store_true",
        help="type schema before conversion (*)")
    arg("--no-type", dest="type", action="store_false",
        help="do not type schema before conversion")
    arg("--simple", default=True, action="store_true",
        help="simplify schema before conversion (*)")
    arg("--no-simple", dest="simple", action="store_false",
        help="do not simplify schema before conversion")
    arg("--vocab", default=True, action="store_true",
        help="apply vocabulary filter (*)")
    arg("--no-vocab", dest="vocab", action="store_false",
        help="do not apply vocabulary filter")
    # NOTE this is necessary to handle older schema versions
    arg("--modernize", default=True, action="store_true",
        help="modernize schema (*)")
    arg("--no-modernize", dest="modernize", action="store_false",
        help="do not modernize schema")

    arg("--schema-version", "-V", dest="sversion", type=int, default=0, help="set JSON Schema version")
    arg("--out", "-o", default="-", help="set model output file")
    arg("schemas", nargs="*", help="schemas to process")
    args = ap.parse_args(xargs)

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    resolver = Resolver(cache=args.cache, mapping=args.map)

    if not args.schemas:
        args.schemas = ["-"]

    errors = 0

    for fn in args.schemas:
        log.debug(f"considering: {fn}")
        try:
            schema = json.load(open(fn) if fn != "-" else sys.stdin)
            model = schema_to_model(
                schema, fn,
                use_id=args.id, strict=args.strict, fix=args.fix,
                vocabularize=args.vocab, modernize=args.modernize,
                simpler=args.simple, typer=args.type, resilient=args.resilient,
                version=args.sversion, resolver=resolver,
                level=logging.DEBUG if args.debug else logging.INFO,
            )
        except Exception as e:
            log.error(e, exc_info=args.debug)
            errors += 1
            model = {"ERROR": str(e)}

        output = json.dumps(model, sort_keys=args.sort_keys, indent=args.indent)

        if args.out == "-":
            print(output, flush=True)
        else:
            with open(args.out, "w") as f:
                print(output, file=f, flush=True)

    return 1 if errors else 0

def jsu_compile(xargs: list[str]|None = None) -> int:
    """Compile schema into script or executable."""

    ap = argparse.ArgumentParser(
        prog="jsu-compile",
        description="Compile JSON Schema: generate checkers in various languages",
    )
    arg = ap.add_argument
    ap_common(arg, with_backend=True)

    arg("--runtime", default=False, action="store_true", help="output runtime directory and exit")

    # schema to model conversion
    arg("--schema-version", "-V", dest="sversion", type=int, default=0,
        help="set JSON Schema version")

    arg("--id", action="store_true", default=False,
        help="enable $id lookup")
    arg("--no-id", dest="id", action="store_false",
        help="disable $id lookup (*)")
    arg("--strict", action="store_true", default=True,
        help="reject doubtful schemas (*)")
    arg("--no-strict", dest="strict", action="store_false",
        help="accept doubtful schemas")
    arg("--fix", "-F", action="store_true", default=True,
        help="fix common schema issues (*)")
    arg("--no-fix", "-nF", dest="fix", action="store_false",
        help="do not fix common schema issues")
    arg("--resilient", default=False, action="store_true",
        help="return something whatever")
    arg("--no-resilient", dest="resilient", action="store_false",
        help="may fail (*)")
    arg("--vocab", default=True, action="store_true",
        help="apply vocabulary filter (*)")
    arg("--no-vocab", dest="vocab", action="store_false",
        help="do not apply vocabulary filter")
    arg("--modernize", default=True, action="store_true",
        help="modernize schema (*)")
    arg("--no-modernize", dest="modernize", action="store_false",
        help="do not modernize schema")
    arg("--type", default=True, action="store_true",
        help="type schema before conversion (*)")
    arg("--no-type", dest="type", action="store_false",
        help="do not type schema before conversion")
    arg("--simple", default=True, action="store_true",
        help="simplify schema before conversion (*)")
    arg("--no-simple", dest="simple", action="store_false",
        help="do not simplify schema before conversion")

    # remote schemas
    arg("--cache", type=str, default=None, help="cache directory for remote schemas")
    arg("--map", "-m", default=[], action="append", help="url local mapping \"src=dst\"")

    # how to run the jmc backend
    arg("--backend", type=str, default="p", choices=["p", "f"],
        help="how to run the backend: p=process, f=function")

    # forwarded to backend
    arg("--out", "-o", default=None, help="set output file")
    arg("--regex-engine", "-re", default=None, help="set regex engine")
    arg("--precompiled", default=False, action="store_true", help="use precompiled C runtime")
    arg("--loose", default=True, action="store_true",
        help="accept loose numbers (*)")
    arg("--no-loose", dest="loose", action="store_false",
        help="be strict about numbers")
    arg("--reporting", action="store_true", default=True,
        help="enable reporting (*)")
    arg("--no-reporting", dest="reporting", action="store_false",
        help="disable reporting")
    # on None, will try to take hints from vacabulary, if any
    arg("--format", default=None, action="store_true",
        help="do not ignore formats")
    arg("--no-format", dest="format", action="store_false",
        help="ignore formats, this is the default unless $vocabulary enables format")

    # schema to consider
    arg("schema", default="-", nargs="?", help="schema to process")

    # other stuff
    arg("others", nargs="*", help="jmc backend options and arguments")
    args = ap.parse_args(xargs)

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    resolver = Resolver(cache=args.cache, mapping=args.map)

    if args.runtime:
        subprocess.run(["jmc", "--runtime"], check=True)
        return 0

    # intermediate model
    model = None

    try:
        schema = json.load(open(args.schema) if args.schema != "-" else sys.stdin)
        resolver = Resolver(cache=args.cache, mapping=args.map)
        model = schema_to_model(
            schema, args.schema,
            use_id=args.id, strict=args.strict, fix=args.fix,
            vocabularize=args.vocab, modernize=args.modernize,
            typer=args.type, simpler=args.simple, resilient=args.resilient,
            version=args.sversion, resolver=resolver,
            level=logging.DEBUG if args.debug else logging.INFO,
        )
    except Exception as e:
        log.error(f"schema to model conversion for {args.schema} failed")
        log.error(e, exc_info=args.debug)
        return 1  # conversion failed

    # TODO
    # - use standard input with jmc?
    # - skip command and call jmc internal machinery directly in some cases?

    # forward some options to back-end, but do not overwrite explicit options
    if args.format is None:
        # set default depending on $vocabulary, else ignore formats
        if isinstance(model, dict) and "#.format" in model:
            args.format = model["#.format"]
        else:
            args.format = False
    args.others.insert(0, "--predef" if args.format else "--no-predef")
    args.others.insert(0, "--reporting" if args.reporting else "--no-reporting")
    if args.out is not None:
        args.others += [ "-o", args.out ]
    args.others.insert(0, "--loose-number" if args.loose else "--strict-number")
    if args.regex_engine is not None:
        args.others = ["--regex-engine", args.regex_engine, *args.others]
    if args.precompiled:
        args.others.insert(0, "--precompiled")

    # also forward verbosity options, debug wins
    if args.debug:
        args.others.insert(0, "--debug")
    if args.quiet:
        args.others.insert(0, "--quiet")

    # compile intermediate model through a temporary file
    with tempfile.NamedTemporaryFile(suffix=".model.json") as tmp:

        smodel = json.dumps(model, sort_keys=args.sort_keys, indent=args.indent)

        if args.debug:
            log.debug(f"intermediate model: {smodel}")

        tmp.write(smodel.encode("UTF8"))
        tmp.flush()

        # launch jmc command and report status
        jmc = ["jmc", "--model", tmp.name, "--extend", *args.others]

        if args.debug:
            log.debug(f"jmc: {' '.join(jmc)}")

        if args.backend == "p":
            done = subprocess.run(jmc, check=False)
            status = done.returncode
        else:
            status = json_model.jmc_script(jmc[1:])

        if status:
            log.error(f"backend jmc process return code: {status}")
        return status

def json_schema_to_python_checker(
        schema: JsonSchema,
        name: str|None = None,
        version: int = 0,
        strict: bool = True,
        fix: bool = False,
        vocabularize: bool = True,
        modernize: bool = True,
        typer: bool = True,
        simpler: bool = True,
        resilient: bool = True,
        cache: str|None = None,
        mapping: dict[str, str] = {},
        level: int = logging.INFO,
        loose_int: bool = True,
        loose_float: bool = True,
        predef: bool = False,
        extend: bool = True,
    ) -> Callable[[Jsonable], bool]:
    """Build a dynamic python checker function from a schema."""
    try:
        resolver = Resolver(cache=cache, mapping=mapping)
        # build the intermediate model
        model = schema_to_model(
            schema, name, strict=strict, fix=fix, modernize=modernize, typer=typer,
            simpler=simpler, version=version, resilient=resilient, vocabularize=vocabularize,
            resolver=resolver, level=level,
        )
        if level == logging.DEBUG:
            log.debug(f"intermediate model: {model}")
        # convert model to a checker function
        import json_model
        return json_model.model_checker_from_json(
            model, loose_int=loose_int, loose_float=loose_float, predef=predef, extend=extend,
        )
        return checker
    except BaseException as e:
        log.error(f"schema compilation failed: {e}")
        if level == logging.DEBUG:
            log.debug(e, exc_info=True)
        if not resilient:
            raise
        log.warning("using all-pass checker for {name} (resilient mode)")
        return lambda _: True

def jsu_runner(xargs: list[str]|None = None) -> int:

    ap = argparse.ArgumentParser(
        prog="jsu-test-runner",
        description="Test runner for JSON Schema Test Suite",
    )
    arg = ap.add_argument
    ap_common(arg, with_backend=True)

    # resolver settings
    arg("--cache", type=str, default=None, help="cache directory for remote schemas")
    arg("--map", "-m", default=[], action="append", help="url local mapping \"src=dst\"")

    # debug
    arg("--dump", default=False, action="store_true",
        help="show generated model as debug")
    arg("--no-dump", dest="dump", action="store_false",
        help="do not show generated model as debug (*)")

    # model and code generation options
    arg("--format", action="store_true", default=False,
        help="do not ignore formats")
    arg("--no-format", dest="format", action="store_false",
        help="ignore formats (*)")
    arg("--vocab", default=True, action="store_true",
        help="apply vocabulary filter (*)")
    arg("--no-vocab", dest="vocab", action="store_false",
        help="do not apply vocabulary filter")
    arg("--modernize", default=True, action="store_true",
        help="modernize schema (*)")
    arg("--no-modernize", dest="modernize", action="store_false",
        help="do not modernize schema")
    arg("--type", default=True, action="store_true",
        help="type schema before conversion (*)")
    arg("--no-type", dest="type", action="store_false",
        help="do not type schema before conversion")
    arg("--simple", default=True, action="store_true",
        help="simplify schema before conversion (*)")
    arg("--no-simple", dest="simple", action="store_false",
        help="do not simplify schema before conversion")
    arg("--strict", action="store_true", default=False,
        help="reject doubtful schemas")
    arg("--no-strict", dest="strict", action="store_false",
        help="accept doubtful schemas (*)")
    arg("--resilient", default=False, action="store_true",
        help="enable model conversion resilience")
    arg("--no-resilient", dest="resilient", default=False, action="store_true",
        help="disable model conversion resilience (*)")

    arg("--schema-version", "-V", dest="sversion", type=int, default=0,
        help="set JSON Schema version")
    arg("cases", nargs="*", help="test cases to process")
    args = ap.parse_args(xargs)

    log.setLevel(logging.DEBUG if args.debug else logging.WARNING if args.quiet else logging.INFO)

    resolver = Resolver(cache=args.cache, mapping=args.map)

    CASES_MODEL = [
        {
            "description": "",
            "schema": "$ANY",
            "tests": [
                {
                    "description": "",
                    "data": "$ANY",
                    "valid": True,
                    "?comment": ""
                }
            ],
            "?specification": [ {"?core": "", "?quote": "", "/^rfc[0-9]+$/": ""} ],
            "?comment": ""
        }
    ]

    check_cases = json_model.model_checker_from_json(CASES_MODEL)

    # stats counters
    n_cases, n_cases_passed, n_tests, n_tests_passed, n_errors, n_unsafe = 0, 0, 0, 0, 0, 0

    n_args = 0
    for fname in args.cases:
        n_args += 1
        try:
            # load and sanity check
            cases = json.loads(open(fname).read())
            # accept a single test for resilience
            if isinstance(cases, dict):
                cases = [ cases ]
            assert check_cases(cases)

            for ic, case in enumerate(cases):

                scase = f"{fname}[{ic}]"

                n_cases += 1
                n_tests += len(case["tests"])
                description = case["description"]

                log.info(f"considering {scase}: {description}")

                try:
                    checker = json_schema_to_python_checker(
                        case["schema"], scase, strict=args.strict, fix=False,
                        vocabularize=args.vocab, modernize=args.modernize, typer=args.type,
                        simpler=args.simple, predef=args.format,
                        version=args.sversion, resilient=args.resilient,
                        cache=args.cache, mapping=args.map,
                        level = logging.DEBUG if args.debug else logging.INFO,
                        # hardcoded expectations
                        loose_int=True, loose_float=True, extend=True,
                    )

                    n_case_tests_ok = 0
                    for it, test in enumerate(case["tests"]):
                        try:
                            valid = checker(test["data"])
                            if valid == test["valid"]:
                                n_tests_passed += 1
                                n_case_tests_ok += 1
                            else:
                                # count wrong rejects as unsafe false negative
                                if not valid:
                                    n_unsafe += 1
                                log.error(f"unexpected result on {scase}[{it}]: {test['description']}")
                        except BaseException as e:
                            n_errors += 1
                            if args.debug:
                                log.error(e, exc_info=args.debug)
                            log.error(f"case {description}/{test['description']}: FAILED")

                    if n_case_tests_ok == len(case["tests"]):
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
            log.error(f"cases {fname}: BAD case file {e}")

    # final report
    n_tests_failed = n_tests - n_tests_passed
    report = f"files={n_args} errors={n_errors} cases={n_cases_passed}/{n_cases}"
    report += f" ({100.0 * n_cases_passed / max(n_cases, 1):.1f}%)"
    report += f" tests={n_tests_passed}/{n_tests}"
    report += f" ({100.0 * n_tests_passed / max(n_tests, 1):.1f}%, {n_tests_failed} fails)"
    print(report)

    # tell whether all was well
    return 2 if n_unsafe else 1 if n_tests_failed else 0
