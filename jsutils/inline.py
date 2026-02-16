from typing import Any
import copy
import math
import re
from urllib.parse import urlsplit, urljoin
import requests
import hashlib
import json
import logging

from .utils import JsonSchema, SchemaPath, JSUError, KEYWORD_TYPE, is_abs_url, schemapath_to_urlpath
from .schemas import Schemas
from .recurse import recurseSchema

log = logging.getLogger("inline")
log.setLevel(logging.INFO)

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
    elif prop == "type":
        if prop in schema:
            sval = schema[prop]
            if sval == value:
                pass
            elif isinstance(sval, str):
                if isinstance(value, str):
                    if sval in ("integer", "number") and value in ("integer", "number"):
                        schema[prop] = "integer"  # keep stricter type
                    else:
                        return False  # not feasible as svalue != value
                assert isinstance(value, list)
                if sval in value:
                    pass
                else:
                    if sval == "integer" and "number" in value:
                        pass
                    elif sval == "number" and "integer" in value:
                        schema[prop] = "integer"
                    else:
                        return False
            else:
                assert isinstance(sval, list)
                if isinstance(value, str):
                    if value in sval:
                        schema[prop] = value
                    elif value in ("integer", "number") and "integer" in sval or "number" in sval:
                        schema[prop] = "integer"
                    else:
                        return False
                else:
                    assert isinstance(value, list)
                    # integer/number
                    if "number" in value and "integer" in svalue and "number" not in svalue:
                        svalue.append("number")
                    if "integer" in value and "number" in svalue and "integer" not in svalue:
                        svalue.append("integer")
                    # intersect lists
                    types = [ t for t in svalue if t in value ]
                    if len(types) == 0:
                        return False
                    elif len(types) == 1:
                        schema[prop] = types[0]
                    else:
                        schema[prop] = types
        else:
            schema[prop] = value
    # TODO
    # - $ref pattern with allOf?
    elif prop in ("$ref", "pattern",
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

FILE_URL = "file://"

def resolveExternalRefs(
            schema: JsonSchema, *,
            url: str = ".",
            cache: str|None = None,
            mapping: dict[str, str] = {},
            version: int|None = None,
            level: int = logging.INFO,
        ) -> JsonSchema:
    """Resolution of external schema references.

    JSON Schema schema is updated with external references ($ref with url values)
    pointing to local definitions at the outer level.

    This means dealing with $id on the path and iterating over inlined references.
    """
    # NOTE this should be finite because the same url should point to the already allocated def
    # FIXME this should probably require a two-pass recursion, first to collect local defs ($ids),
    # second to resolve what needs be.

    if isinstance(schema, bool):
        return schema
    assert isinstance(schema, dict)

    log.setLevel(level)
    if level == logging.DEBUG:
        log.debug(f"resolve ext in: {json.dumps(schema, indent=2)}")

    # set version if possible
    if version is None and "$schema" in schema:
        sversion = schema["$schema"]
        version = 8 if "draft/2019-09/schema" in sversion else \
                  9 if "draft/2020-12/schema" in sversion else \
                  7  # take a guess

    defs = ("$defs" if "$defs" in schema  else
            "definitions" if "definitions" in schema else
            "$defs" if version and version >= 8 else
            "definitions")
    if defs not in schema:
        schema[defs] = {}
    else:
        assert isinstance(schema[defs], dict)

    sid = "id" if "id" in schema else "$id"
    if sid in schema:
        assert isinstance(schema[sid], str), "schema {sid} must be a string"
        if url and schema[sid] != url:
            log.warning(f"inconsistent {sid}: {schema[sid]} vs {url}")
        url = schema[sid]

    # url -> local name in outer scope
    resolved: dict[str, str] = {}
    # url -> path in outer scope
    url_path: dict[str, str] = {}

    # counter when creating new names
    externs: int = 0

    # url $id stack
    pushed: list[tuple] = [ tuple() ]
    urls: list[str] = [ url ]

    # whether to cleanup ids
    keep_id: bool = True

    # defs already processed
    processed: set[str] = set()
    processed.update(schema[defs].keys())

    # keep track of current $id (absolute or relative) to resolve relative urls in $ref
    # argh, we have to throw in $anchor as well…
    def fltExtRef(local: JsonSchema, p: SchemaPath) -> bool:
        if isinstance(local, dict):
            # note $anchor is more or less a supplement to $id
            sid = "id" if "id" in local else "$id"
            anchor = local.get("$anchor", None)
            if anchor is not None:
                # move anchor as $id if possible
                del local["$anchor"]
                if sid not in local:
                    local[sid] = "#" + anchor
                    anchor = None
            if sid in local:
                url = local[sid]
                assert isinstance(url, str)
                if re.match(r"#[^/]", url):  # local identifier case ???
                    # FIXME is this actually the case
                    pass
                elif not is_abs_url(url):
                    url = urljoin(urls[-1], url)
                if anchor is not None:  # one more step…
                    url = urljoin(url, "#" + anchor)
                # else url kept as-is
                pushed.append(tuple(p))
                urls.append(url)
                # BTW this may be a local resolution in passing!
                # FIXME this is not true
                # resolved[url] = urls[0] + "#/" + schemapath_to_urlpath(p)
                url_path[url] = "#/" + schemapath_to_urlpath(p)
        return True

    def rwtScanPop(local: JsonSchema, p: SchemaPath) -> JsonSchema:
        if pushed and tuple(p) == pushed[-1]:
            pushed.pop()
            urls.pop()
            if not keep_id:
                sid = "$id" if "$id" in local else "id"
                if level == logging.DEBUG:
                    local["$comment"] = local[sid]
                del local[sid]
        return local

    # rewrite remote refs as local definitions, without ids
    def rwtExtRef(local: JsonSchema, p: SchemaPath) -> JsonSchema:

        nonlocal externs

        # shortcut
        if isinstance(local, bool):
            return local
        assert isinstance(local, dict)

        # handle a $ref
        # TODO ref
        if "$ref" in local:
            dest = local["$ref"]
            assert isinstance(dest, str) and dest
            log.debug(f"$ref={dest} ({urls} / {resolved} / {url_path})")

            if dest.endswith("#"):
                dest += "/"

            # reference patterns:
            # { "$ref": "<full-url>" }
            # { "$ref": "<full-url>#<path>" } # path = /xxx/yyy
            # { "$ref": "<partial-url>" }
            # { "$ref": "<partial-url>#<path>" }
            # { "$ref": "#<path>" }
            # { "$ref": "#<name>" }

            if is_abs_url(dest):  # full url with optional json path
                pass
            elif "#/" in dest or "#" not in dest:  # relative url with optional json path
                # this is kind of strange, if there is a $id it is for subschemas only,
                # not for here, so we have to skip it ?!
                # NOTE wtf, it seems to depend on the version :-(
                if urls:
                    if version and version >= 8:
                        idx = -1
                    else:
                        idx = -2 if "$id" in local or "id" in local else -1
                    dest = urljoin(urls[idx], dest)
                # log.debug(f"join: {local['$ref']} -> {dest}")
            elif dest and dest[0] == "#" :  # name? maybe with a path??
                pass
            else:
                log.error(f"cannot handle $ref: {dest}")
        else:
            dest = None

        # use existing resolutions
        if not dest:
            pass
        elif dest in url_path:
            local["$ref"] = url_path[dest]
        else:
            if is_abs_url(dest):
                if "#" in dest:
                    url, path = dest.split("#", 1)
                else:
                    url, path = dest, None
            else:
                url, path = None, None
            init_url = url

            log.debug(f"url={url} path={path}")

            if url is not None:

                # local url mapping for some JSTS tests
                if url in url_path:
                    dest = url_path[url]
                elif url in resolved:  # retrieve local name or path
                    dest = f"#/{defs}/{resolved[url]}"
                else:  # or create one
                    js, loaded, filed, cached, cfn = None, False, False, False, None

                    if cache:  # we cache the **initial** url only
                        uh = hashlib.sha3_256(url.encode()).hexdigest()
                        cfn = f"{cache}/{uh}.json"
                        try:
                            with open(cfn) as f:
                                js = json.load(f)
                            log.info(f"# loaded from cache: {url}")
                            loaded, cached = True, True
                        except Exception as e:
                            log.debug(f"not found in cache: {url}")
                    else:
                        uh = None

                    if not loaded and mapping:
                        for src, dst in mapping.items():
                            if url.startswith(src):
                                init_url = url
                                url = dst + url[len(src):]
                                log.warning(f"remapping {init_url} to {url}")
                                break  # stop on first match

                    if not loaded and url.startswith(FILE_URL):
                        fn = url[len(FILE_URL):]
                        try:
                            with open(fn) as f:
                                js = json.load(f)
                            log.info(f"# loaded from file: {url}")
                            loaded, filed = True, True
                        except Exception as e:
                            log.debug(f"file not found for: {url}")

                    if not loaded:
                        res = requests.get(url)
                        log.info(f"# loaded from net: {url!r}")
                        js, loaded = res.json(), True

                    # store in cache
                    if cache and not cached:
                        with open(cfn, "w") as f:
                            f.write(res.text)

                    # find next available name
                    while (name := f"_extern_{externs}_") in schema[defs]:
                        externs += 1

                    # ensure that hierarchical relative urls are consistent in the target
                    if "id" not in js and "$id" not in js:
                        js["$id"] = init_url
                    else:
                        sid = "id" if "id" in js else "$id"
                        if js[sid] != init_url:
                            log.warning(f"overriding {sid} in {init_url}")
                            # NOTE should it be #/$defs/name instead?
                            js[sid] = init_url
                        else:
                            # consistent
                            pass

                    # dest = urls[0] + f"#{defs}/{name}"
                    resolved[init_url] = name
                    dest = f"#/{defs}/{name}"
                    schema[defs][name] = js
                    log.warning(f"url_path: {init_url} -> {dest}")
                    url_path[init_url] = str(dest)

                # update external reference to local destination
                if path:
                    log.debug(f"adding path {path} to dest {dest}")
                    if dest in ("#", "#/"):
                        if path[0] == "/":
                            dest = "#" + path
                        else:  # it is an anchor
                            spath = "#" + path
                            if spath in url_path:
                                dest = url_path[spath]
                            else:
                                log.warning(f"undefined anchor #{path}")
                                dest = "#" + anchor
                    elif dest[0] == "#":
                        if path[0] == "/":
                            if path != "/":  # non trivial path
                                dest += path
                            # else: stay as-is
                        else:
                            spath = "#" + path
                            if spath in url_path:
                                dest = url_path[spath]
                            else:
                                log.warning(f"undefined anchor #{path}")
                                dest = "#" + anchor
                        # else ignore
                    else:
                        dest = urljoin(dest, "#" + path)
                local["$ref"] = dest

        return rwtScanPop(local, p)

    log.debug(f"initial scan")
    # first pass to populate url_path
    keep_id = True
    schema = recurseSchema(schema, ".", flt=fltExtRef, rwt=rwtScanPop, def_first=True)
    keep_id = False
    # then actual $ref rewriting
    schema = recurseSchema(schema, ".", flt=fltExtRef, rwt=rwtExtRef, def_first=True)

    # recurse in newly added names
    changed = True

    while changed:
        changed = False
        for name in list(sorted(schema[defs].keys())):
            if name in processed:
                continue
            processed.add(name)
            changed = True
            keep_id = True
            log.debug(f"onto {name}")
            recurseSchema(schema[defs][name], ".", path=((defs, name), ),
                flt=fltExtRef, rwt=rwtScanPop, def_first=True,
            )
            keep_id = False
            schema[defs][name] = recurseSchema(
                schema[defs][name], f"#/{defs}/{name}", path=((defs, name), ),
                flt=fltExtRef, rwt=rwtExtRef, def_first = True,
            )

    # remove defs if empty
    if not schema[defs]:
        del schema[defs]

    if level == logging.DEBUG:
        log.debug(f"resolve ext out: {json.dumps(schema, indent=2)}")

    return schema
