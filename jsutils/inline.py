from typing import Any
import copy
import math
import re
from urllib.parse import urlsplit, urljoin
import requests
import hashlib
import json

from .utils import JsonSchema, SchemaPath, JSUError, log, KEYWORD_TYPE
from .schemas import Schemas
from .recurse import recurseSchema

# TODO fix recursion handling

def mergeProperty(schema: JsonSchema, prop: str, value: Any) -> JsonSchema:
    """Merge an additional property into en existing schema.

    Note: this is in a best effort basis, on failure a backup plan is required.
    """
    # handle boolean schema
    if isinstance(schema, bool):
        return { prop: value } if schema else False
    assert isinstance(schema, dict)  # pyright helper

    # log.debug(f"merging {prop} in {schema}")

    # if the type is known and singular, incompatible props can be dropped!
    stype: str|None = None
    if "type" in schema and isinstance(schema["type"], str):
        stype = schema["type"]
        if stype == "integer":
            stype = "number"
        if prop in KEYWORD_TYPE and KEYWORD_TYPE[prop] != stype:
            log.info(f"skipping adding {prop} to incompatible {stype} schema")
            return schema

    # then object
    if prop in ("$defs"):  # ignore
        pass
    elif prop == "enum":
        if prop in schema:
            # intersect in order
            vals = []
            for v in schema[prop]:  # pyright: ignore
                if v in value:
                    vals.append(v)
            if len(vals) == 0:
                log.warning("incompatible enum/enum makes schema unsatisfiable")
                schema = False
            else:
                schema[prop] = vals
        elif "const" in schema:
            if schema["const"] in value:
                pass
            else:
                log.warning("incompatible enum/const makes schema unsatisfiable")
                schema = False
        else:
            schema[prop] = value
    elif prop == "const":
        if prop in schema:
            if schema[prop] == value:
                pass
            else:
                log.warning("incompatible const/const makes schema unsatisfiable")
                schema = False
        elif "enum" in schema:
            schema[prop] = value
            if value in schema["enum"]:
                del schema["enum"]
            else:
                log.warning("incompatible const/enum makes schema unsatisfiable")
                schema = False
        else:
            schema[prop] = value
    elif prop == "required":
        assert isinstance(value, list)
        if prop in schema:
            # append in order and without duplicates
            for p in value:
                if p not in schema["required"]:
                    schema["required"].append(p)  # pyright: ignore
        else:
            schema["required"] = value
    elif prop == "properties":
        if prop in schema:
            props = schema[prop]
            assert isinstance(value, dict) and isinstance(props, dict)
            for p, s in value.items():
                if p in props:
                    if props[p] == s or s is True:
                        pass
                    else:
                        props[p] = { "allOf": [ props[p], s ] }
                else:
                    props[p] = s
        else:
            schema[prop] = value
    elif prop in ("allOf", "anyOf", "oneOf"):
        assert isinstance(value, list)
        if prop in schema:
            schema[prop].extend(value)  # pyright: ignore
        else:
            schema[prop] = value
    elif prop in ("title", "$comment"):
        # best effort
        if prop not in schema:
            schema[prop] = value
    # FIXME: what about "else"?
    # TODO extend list of supported validations?
    elif prop == "multipleOf":
        # switch to int
        if isinstance(value, float) and value == int(value):
            value = int(value)
        if prop in schema:
            ival = schema[prop]
            if isinstance(ival, float) and ival == int(ival):
                ival = int(ival)
            if ival == value:
                schema[prop] = value  # may switch to int in passing
            elif type(ival) is int and type(value) is int:
                schema[prop] = math.lcm(ival, value)
            else:
                raise JSUError(f"cannot merge prop {prop} distinct values")
        else:
            schema[prop] = value
    elif prop in ("minimum", "exclusiveMinimum"):
        if prop in schema:
            schema[prop] = max(schema[prop], value)
        else:
            schema[prop] = value
    elif prop in ("maximum", "exclusiveMaximum"):
        if prop in schema:
            schema[prop] = min(schema[prop], value)
        else:
            schema[prop] = value
    elif prop in ("minLength", "minProperties", "minItems", "minContains"):
        if isinstance(value, float):
            assert value == int(value), "integer min length spec"
            value = int(value)
        assert type(value) is int, "integer min length spec"
        if prop in schema:
            ival = schema[prop]
            if isinstance(ival, float):
                assert ival == int(ival), "integer min length spec"
                ival = int(ival)
            assert type(ival) is int, "integer min length spec"
            schema[prop] = max(value, ival)
        else:
            schema[prop] = value
    elif prop in ("maxLength", "maxProperties", "maxItems", "maxContains"):
        if isinstance(value, float):
            assert value == int(value), "integer max length spec"
            value = int(value)
        assert type(value) is int, "integer max length spec"
        if prop in schema:
            ival = schema[prop]
            if isinstance(ival, float):
                assert ival == int(ival), "integer max length spec"
                ival = int(ival)
            assert type(ival) is int, "integer max length spec"
            schema[prop] = min(value, ival)
        else:
            schema[prop] = value
    # TODO
    # - $ref pattern with allOf?
    elif prop in ("type", "$ref", "pattern",
                  "additionalProperties", "additionalItems", "items", "uniqueItems"):
        # allow identical values only (for now)
        if prop in schema:
            if schema[prop] == value:
                pass
            else:
                raise JSUError(f"cannot merge prop {prop} distinct values")
        else:
            schema[prop] = value
    else:
        raise JSUError(f"merging of prop {prop} is not supported (yet)")

    # log.debug(f"result: {schema}")
    return schema


# properties keept at the root while merging
_KEEP_PROPS = {
    "$schema", "$id", "$comment", "title", "description", "examples",
    # containers
    "$defs", "oneOf", "anyOf", "allOf",
    # special cases
    "unevaluatedProperties", "unevaluatedItems",
    # older version compatibility?
    "definitions",
}


def mergeSchemas(schema: JsonSchema, refschema: JsonSchema) -> JsonSchema:
    """Merge two schemas."""

    if isinstance(refschema, bool):
        return schema if refschema else False
    elif isinstance(schema, bool):
        return refschema if schema else False
    assert isinstance(schema, dict) and isinstance(refschema, dict)

    saved = schema
    schema = copy.deepcopy(schema)

    try:
        # best effort
        for p, v in refschema.items():
            schema = mergeProperty(schema, p, v)

        # log.debug(f"merged: {schema}")

    except JSUError as e:
        # backup merge with allOf
        log.warning(f"merge error: {e}")
        log.info("merging schemas with allOf")
        schema = saved
        separate = {}
        for p in list(schema.keys()):
            if p not in _KEEP_PROPS:
                separate[p] = schema[p]
                del schema[p]
        if "allOf" not in schema:
            schema["allOf"] = []
        if len(separate) > 0:
            schema["allOf"].append(separate)  # pyright: ignore
        if len(refschema) > 0:
            schema["allOf"].append(refschema)  # pyright: ignore

    return schema


def _url(ref):
    """Extract base URL from full reference."""
    u = urlsplit(ref)
    return u.scheme + "://" + u.netloc


def inlineRefs(schema: JsonSchema, url: str, schemas: Schemas) -> JsonSchema:
    """Recursively inline $ref in schema, which is modified."""

    def rwtRef(schema: JsonSchema, path: SchemaPath) -> JsonSchema:

        # recursion avoidance (FIXME insufficient)
        spath = "/".join(str(s) for s in path)
        skips = {url + "#" + spath, url + "#/" + spath, url + "#./" + spath}

        while isinstance(schema, dict) and "$ref" in schema:
            ref = schema["$ref"]
            assert isinstance(ref, str)

            # (direct) recursion detection
            if ref in skips:
                log.info(f"skipping recursive ref: {ref}")
                break

            # actual substitution
            sub = schemas.schema(url, ref)
            del schema["$ref"]
            if isinstance(sub, dict):
                schema = mergeSchemas(schema, sub)
            else:
                assert isinstance(sub, bool)
                if not sub:
                    schema = False
                # else True is coldly ignored

        return schema

    return recurseSchema(schema, url, rwt=rwtRef)

# convert a schema path to a working reference
def _sp2ref(path: SchemaPath) -> str:
    # FIXME what about ~ / % chars?
    return "#" + "/".join("/".join(str(x) for x in s) if isinstance(s, tuple) else str(s) for s in path)

is_abs_url = re.compile(r"(https?|file)://").match

def resolveExternalRefs(
            schema: JsonSchema, *,
            url: str|None = None,
            cache: str|None = None,
            mapping: dict[str, str] = {},
        ) -> JsonSchema:
    """Resolution of external schema references.

    JSON Schema schema is updated with external references ($ref with url values)
    pointing to local definitions.

    """
    # NOTE this should be finite because the same url should point to the already allocated def
    # FIXME this should probably require a two-pass recursion, first to collect local defs ($ids),
    # second to resolve what needs be.

    if isinstance(schema, bool):
        return schema
    assert isinstance(schema, dict)

    defs = "definitions" if "definitions" in schema else "$defs"
    if defs not in schema:
        schema[defs] = {}
    else:
        assert isinstance(schema[defs], dict)

    sid = "id" if "id" in schema else "$id"
    if sid in schema:
        assert isinstance(schema[sid], str), "schema {sid} must be a string"
        if url and schema[sid] != url:
            log.warning(f"inconsistent {sid}: {schema[sid]} vs {url}")

    # url -> local name
    resolved: dict[str, str] = {}
    externs: int = 0
    urls: list[str|None] = [ url ]

    # keep track of current $id to resolve relative urls
    def fltExtRef(local: JsonSchema, p: SchemaPath) -> bool:
        if isinstance(local, dict):
            sid = "id" if "id" in local else "$id"
            if sid in local:
                url = local[sid]
                if not is_abs_url(url):
                    url = urljoin(urls[-1], url)
                urls.append(url)
                # BTW this may be a resolution in passing!
                resolved[url] = _sp2ref(p)
        return True

    # rewrite remote refs as local definitions
    def rwtExtRef(local: JsonSchema, _: SchemaPath) -> JsonSchema:

        nonlocal externs

        # shortcut
        if isinstance(local, bool):
            return local
        assert isinstance(local, dict)

        # handle a $ref
        # TODO ref
        if "$ref" in local:
            dest = local["$ref"]
            assert isinstance(dest, str)
            log.debug(f"$ref: {dest} ({urls}/{resolved})")

            # FIXME handle ".#"?
            if re.match("[^#]", dest) and not is_abs_url(dest):  # relative URL
                # this is kind of strange, if there is a $id it is for subschemas only,
                # not for here, so we have to skip it ?!
                idx = -2 if "$id" in local or "id" in local else -1
                dest = urljoin(urls[idx], dest)

            # local url mapping for some JSTS tests
            if mapping:
                for src, dst in mapping.items():
                    if dest.startswith(src):
                        init_dest = dest
                        dest = dst + dest[len(src):]
                        log.warning(f"remapping {init_dest} to {dest}")
                        break

            if is_abs_url(dest):
                if "#" in dest:
                    url, path = dest.split("#", 1)
                else:
                    url, path = dest, None
            else:
                url, path = None, None

            # log.debug(f"$ref: url={url} path={path} dest={dest}")

            if url is not None:

                # retrieve local name
                if url in resolved:
                    name = resolved[url]
                else:
                    if cache:
                        uh = hashlib.sha3_256(url.encode()).hexdigest()
                        fn = f"{cache}/{uh}.json"
                    else:
                        fn = None
                    js, loaded, cached = None, False, False
                    if fn:
                        try:
                            with open(fn) as f:
                                js = json.load(f)
                            loaded, cached = True, True
                            log.info(f"# loaded from cache: {url}")
                        except Exception as e:
                            log.debug(f"# not found in cache: {url} ({e})")
                    if not loaded:
                        res = requests.get(url)
                        log.info(f"# loaded from net: {url}")
                        js, loaded = res.json(), True
                    if cache and not cached:  # store in cache
                        with open(fn, "w") as f:
                            f.write(res.text)

                    # find next available name
                    while (name := f"_extern_{externs}_") in schema[defs]:
                        externs += 1

                    # FIXME delay changes?
                    schema[defs][name] = js
                    resolved[url] = name

                # update external reference to local destination
                dest = f"#/{defs}/{name}"
                if path:
                    dest += path
                local["$ref"] = dest

        # pop current url
        sid = "id" if id in local else "$id"
        if sid in local:
            urls.pop()

        return local

    # initial recursion
    schema = recurseSchema(schema, ".", flt=fltExtRef, rwt=rwtExtRef, def_first=True)

    # recurse in new names
    recursed: set[str] = set()
    changed = True

    while changed:
        changed = False
        for name in list(sorted(schema[defs].keys())):
            if name in recursed:
                continue
            changed = True
            recursed.add(name)
            schema[defs][name] = recurseSchema(
                schema[defs][name], f"#/{defs}/{name}",
                flt=fltExtRef, rwt=rwtExtRef, def_first = True,
            )

    # remove defs if empty
    if not schema[defs]:
        del schema[defs]

    return schema
