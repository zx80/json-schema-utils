from typing import Any
from dataclasses import dataclass
import copy
import math
import re
from urllib.parse import urlsplit, urljoin
import json
import logging

from .utils import JsonSchema, SchemaPath, JSUError, KEYWORD_TYPE, NO_SEMANTICS
from .utils import is_abs_url, schemapath_to_urlpath, is_any, is_none, has_any
from .schemas import Schemas
from .restruct import modernizeOldDraft
from .recurse import recurseSchema
from .resolver import Resolver
from .vocab import vocabularizeSchema

log = logging.getLogger("inline")
log.setLevel(logging.INFO)

# TODO fix recursion handling

#
# FIXME merge success is order dependent or could be improved if the order is controlled
#
# { prop: { foo: any } } U { addPro: X } may okay if there are no other props in the second.
#
def mergeProperty(schema: JsonSchema, prop: str, value: Any) -> JsonSchema:
    """Merge an additional property into en existing schema.

    NOTE this is in a best effort basis, on failure a backup plan is required.
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
                schema[prop] = vals  # type: ignore
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
                    schema["required"].append(p)  # type: ignore
        else:
            schema["required"] = value  # type: ignore
    elif prop == "properties":
        # FIXME probably not allowed unless some conditions
        assert isinstance(schema, dict)  # pyright
        if "additionalProperties" in schema and \
                not is_any(schema["additionalProperties"]):  # type: ignore
            raise JSUError(f"cannot merge prop {prop} with existing additionalProperties")
        if prop in schema:
            props = schema[prop]
            assert isinstance(value, dict) and isinstance(props, dict)
            for p, s in value.items():
                if p in props:
                    if props[p] == s or s is True:
                        pass
                    else:
                        props[p] = {"allOf": [ props[p], s ]}  # type: ignore
                else:
                    props[p] = s
        else:
            schema[prop] = value
    elif prop == "patternProperties":
        assert isinstance(value, dict)
        # NOTE patternProperties is pretty orthogonal to properties/additionalProperties
        # NOTE unevaluatedProperties can be ignored as it is processed later
        if value and "patternProperties" not in schema:
            schema["patternProperties"] = value
        elif value and "patternProperties" in schema:
            pp = schema["patternProperties"]
            for p, s in value.items():
                if p in pp:
                    pp[p] = {"allOf": [ pp[p], value] }
                else:
                    pp[p] = s
        else:
            # ignore empty patternProperties
            pass
    elif prop in ("allOf", "anyOf", "oneOf"):
        assert isinstance(value, list)
        if prop in schema:
            schema[prop].extend(value)  # type: ignore
        else:
            schema[prop] = value  # type: ignore
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
                schema[prop] = value  # type: ignore # may switch to int in passing
            elif type(ival) is int and type(value) is int:
                schema[prop] = math.lcm(ival, value)  # type: ignore
            else:
                raise JSUError(f"cannot merge prop {prop} distinct values")
        else:
            schema[prop] = value  # type: ignore
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
            schema[prop] = max(value, ival)  # type: ignore
        else:
            schema[prop] = value  # type: ignore
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
            schema[prop] = min(value, ival)  # type: ignore
        else:
            schema[prop] = value  # type: ignore
    elif prop == "type":
        if prop in schema:
            sval = schema[prop]
            if sval == value:
                pass
            elif isinstance(sval, str):
                if isinstance(value, str):
                    if sval in ("integer", "number") and value in ("integer", "number"):
                        schema[prop] = "integer"  # type: ignore # keep stricter type
                    else:
                        return False  # not feasible as svalue != value
                assert isinstance(value, list)
                if sval in value:
                    pass
                else:
                    if sval == "integer" and "number" in value:
                        pass
                    elif sval == "number" and "integer" in value:
                        schema[prop] = "integer"  # type: ignore
                    else:
                        return False
            else:
                assert isinstance(sval, list)
                if isinstance(value, str):
                    if value in sval:
                        schema[prop] = value  # type: ignore
                    elif value in ("integer", "number") and "integer" in sval or "number" in sval:
                        schema[prop] = "integer"  # type: ignore
                    else:
                        return False
                else:
                    assert isinstance(value, list)
                    # integer/number
                    if "number" in value and "integer" in sval and "number" not in sval:
                        sval.append("number")
                    if "integer" in value and "number" in sval and "integer" not in sval:
                        sval.append("integer")
                    # intersect lists
                    types = [ t for t in sval if t in value ]
                    if len(types) == 0:
                        return False
                    elif len(types) == 1:
                        schema[prop] = types[0]  # type: ignore
                    else:
                        schema[prop] = types  # type: ignore
        else:
            schema[prop] = value
    elif prop == "additionalProperties":
        # NOTE this is fun (or not): it cannot really be mixed with an open object
        # because the checks must be applied independently…
        # NOTE an existing unevaluatedProperties is not an issue because
        # it is expected to be shadowed?
        if prop in schema and schema[prop] == value:
            pass
        elif prop not in schema and is_any(value):
            # special case which will work because it does not need a double check
            schema[prop] = value
        else:
            raise JSUError(f"merging of prop {prop} is not supported (yet)")
    elif prop == "unevaluatedProperties":
        if "additionalProperties" in schema:
            # the prop is overshadowed
            pass
        else:
            # more thoughts needed
            raise JSUError(f"merging of prop {prop} is not supported (yet)")
    # TODO
    # - $ref pattern with allOf?
    elif prop == "prefixItems":
        # simplistic handling, advanced handling in next function
        if prop in schema:
            if schema[prop] == value:
                pass
            else:
                raise JSUError(f"cannot merge prop {prop}")
        else:
            schema[prop] = value
    elif prop == "items":
        if "items" not in schema or is_any(schema["items"]):
            schema[prop] = value
        elif "items" in schema and is_none(schema["items"]):
            # probably optimistic
            pass
        elif schema[prop] == value:
            pass
        else:
            # allOf?
            raise JSUError(f"cannot merge prop {prop}")
    elif prop == "unevaluatedItems":
        # FIXME may not always ok
        # if unevaluatedItems is above it is indeed shadowed, however
        # if there are at the "same" level items is shadowed, which seems to be
        # the reverse of unevaluatedProperties? see 11.2
        if "items" in schema:  # shadowed?!
            pass
        else:
            schema["items"] = value
    elif prop in ("$ref", "pattern", "additionalItems", "items", "uniqueItems"):
        # allow identical values only (for now)
        if prop in schema:
            if schema[prop] == value:
                pass
            else:
                raise JSUError(f"cannot merge prop {prop} distinct values")
        else:
            schema[prop] = value
    elif prop in NO_SEMANTICS:
        log.info(f"merging is dropping prop {prop}")
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
    """Merge two schemas.

    NOTE this always succeeds, either as a unified schema, in the worst case as
    a allOf of the two initial schemas.
    """

    if isinstance(refschema, bool):
        return schema if refschema else False
    elif isinstance(schema, bool):
        return refschema if schema else False
    assert isinstance(schema, dict) and isinstance(refschema, dict)

    saved, refsaved = schema, refschema
    schema, refschema = copy.deepcopy(schema), copy.deepcopy(refschema)

    try:
        # special handing of prefixItems/items(/additionalItems)
        if (has_any(schema, "prefixItems", "items", "additionalItems") or
                has_any(refschema, "prefixItems", "items", "additionalItems")):

            pil, pir = schema.pop("prefixItems", []), refschema.pop("prefixItems", [])
            itl, itr = schema.pop("items", True), refschema.pop("items", True)

            # handle old schemas, should be elsewhere
            if isinstance(itl, list):
                pil = itl
                itl = schema.pop("additionalItems", True)
            if isinstance(itr, list):
                pir = itr
                itr = refschema.pop("additionalItems", True)

            # common = min(len(pil), len(pir))
            extent = max(len(pil), len(pir))
            # log.debug(f"IN1 pil={pil} itl={itl}")
            # log.debug(f"IN2 pir={pir} itr={itr}")

            # NOTE about memory management: we just copy in the end
            pi = []
            for i in range(extent):
                lpi, truncated = [], False
                # commons
                pili = pil[i] if i < len(pil) else True
                piri = pir[i] if i < len(pir) else True
                if not is_any(pili) and not is_any(pili):
                    lpi.append(pili)
                if not is_any(piri) and piri != pili and not is_any(piri):
                    lpi.append(piri)
                # handle items
                if i >= len(pil):
                    if is_none(itl):  # truncate!
                        lpi, truncated = [], True
                    elif not is_any(itl):
                        lpi.append(itl)
                    # else do not add a useless true
                if i >= len(pir) and not truncated:
                    if is_none(itr):  # truncate!
                        lpi, truncated = [], True
                    elif not is_any(itr):
                        lpi.append(itr)
                    # else do not add a useless true
                # generate subschema
                if not truncated:
                    match len(lpi):
                        case 0:
                            pi.append(True)
                        case 1:
                            pi.append(copy.deepcopy(lpi[0]))
                        case _:
                            pi.append({"allOf": copy.deepcopy(lpi)})
                else:
                    break

            # generate merged prefixItems/items
            if pi:
                schema["prefixItems"] = pi

            if not is_any(itl):
                if not is_any(itr):
                    schema["items"] = {"allOf": [ copy.deepcopy(itl), copy.deepcopy(itr) ]}
                else:
                    schema["items"] = copy.deepcopy(itl)
            elif not is_any(itr):
                schema["items"] = copy.deepcopy(itr)
            else:
                # both are true
                pass

            pi_done = True
        else:
            pi_done = False

        # log.debug(f"OUT pi={schema.get('prefixItems', [])} it={schema.get('prefixItems', True)}")

        # best effort
        for p, v in refschema.items():
            if pi_done and p in ("prefixItems", "items", "additionalItems"):  # skip
                continue
            schema = mergeProperty(schema, p, v)

        # log.debug(f"merged: {schema}")

    except JSUError as e:
        # backup merge with allOf
        log.warning(f"merge error: {e}")
        log.info("merging schemas with allOf")
        schema, refschema = saved, refsaved
        separate = {}
        for p in list(schema.keys()):
            if p not in _KEEP_PROPS:
                separate[p] = schema[p]
                del schema[p]
        if "allOf" not in schema:
            schema["allOf"] = []  # type: ignore
        if len(separate) > 0:
            schema["allOf"].append(separate)  # type: ignore
        if len(refschema) > 0:
            schema["allOf"].append(refschema)  # type: ignore

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

#
# EXTERNAL REFERENCES HANDLING
#

@dataclass
class Id:
    url: str
    path: SchemaPath

def resolveExternalRefs(
        schema: JsonSchema, *,
        url: str = ".",
        vocabularize: bool = True,
        modernize: bool = True,
        resolver: Resolver = None,
        version: int = 0,
        level: int = logging.INFO) -> JsonSchema:
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
    if not version and "$schema" in schema:
        sversion = schema["$schema"]
        assert isinstance(sversion, str)  # pyright
        version = (
            8 if "/draft/2019-09/schema" in sversion else
            9 if "/draft/2020-12/schema" in sversion else
            7 if "/draft-07/schema" in sversion else
            6 if "/draft-06/schema" in sversion else
            4 if "/draft-04/schema" in sversion else
            3 if "/draft-03/schema" in sversion else
            0  # take a guess
        )
        if version == 0:
            log.warning(f"unexpected $schema: {sversion}")

    if vocabularize:
        fmt_assert = vocabularizeSchema(schema, resolver)
        # keep track of whether formats are expected to be asserted
        if fmt_assert is not None:
            schema["$__jsu_format__"] = fmt_assert

    # we need to do that here in order to manage external refs reliably
    if modernize:
        modernizeOldDraft(schema, version=version, level=level)

    # local definitions
    defs = ("$defs" if "$defs" in schema else
            "definitions" if "definitions" in schema else
            "$defs" if version and version >= 8 else
            "definitions")
    if defs not in schema:
        schema[defs] = {}
    else:
        assert isinstance(schema[defs], dict), "$defs is an object"

    # id at the root is a check, possibly override
    if "$id" in schema:
        assert isinstance(schema["$id"], str), "schema $id must be a string"
        if url and schema["$id"] != url:
            log.warning(f"inconsistent $id: {schema['$id']} vs {url}")
        url = schema["$id"]

    # we will have to re-scope internal references
    # url -> name in outer scope
    resolved: dict[str, str] = {}
    # url -> path in global outer scope
    url_path: dict[str, str] = {}

    # counter when creating new names for inlining
    externs: int = 0

    # url $id stack
    id_stack = [ Id(url=url, path=()) ]

    # whether to cleanup ids on this phase
    keep_id: bool = True

    # defs already processed
    processed: set[str] = set()
    processed.update(schema[defs].keys())  # type: ignore

    # keep track of current $id (absolute or relative) to resolve relative urls in $ref
    # argh, we have to throw in $anchor as well…
    def fltExtRef(local: JsonSchema, p: SchemaPath) -> bool:
        if isinstance(local, dict):
            # note $anchor is more or less a supplement to $id
            anchor = local.get("$anchor", None)
            assert anchor is None or isinstance(anchor, str)  # pyright
            if anchor is not None:
                # move anchor as $id if possible
                del local["$anchor"]
                if "$id" not in local:
                    local["$id"] = "#" + anchor  # type: ignore
                    anchor = None
            if "$id" in local:
                url = local["$id"]
                assert isinstance(url, str)
                if re.match(r"#[^/]", url):  # local identifier case ???
                    # FIXME is this actually the case
                    pass
                elif not is_abs_url(url):  # not http/file/urn…
                    # FIXME stack url may be a urn:... which is ignored by urljoin
                    url = urljoin(id_stack[-1].url, url)
                # else kept as is
                if anchor is not None:  # one more step…
                    url = urljoin(url, "#" + anchor)
                # else url kept as-is
                # BTW this may be a local resolution in passing!
                # FIXME this is not true
                # resolved[url] = urls[0] + "#/" + schemapath_to_urlpath(p)
                url_path[url] = "#/" + schemapath_to_urlpath(p)
                if url.endswith("#"):
                    nurl = url[:-1]
                    url_path[nurl] = url_path[url]
                else:
                    nurl = url
                # log.debug(f"id_stack push {p}")
                id_stack.append(Id(url=nurl, path=p))
        return True

    def rwtScanPop(local: JsonSchema, p: SchemaPath) -> JsonSchema:
        # NOTE do not pop the root which was manually set
        if isinstance(local, dict) and p and p == id_stack[-1].path:
            # log.debug(f"id_stack pop {p} [{id_stack}]")
            id_stack.pop()
            if not keep_id:
                if level == logging.DEBUG:
                    local["$comment"] = local["$id"]
                del local["$id"]
        return local

    # rewrite remote refs as local definitions, without ids
    def rwtExtRef(local: JsonSchema, p: SchemaPath) -> JsonSchema:

        nonlocal externs

        # shortcut
        if isinstance(local, bool):
            return local
        assert isinstance(local, dict)

        # extract $ref value
        if "$ref" in local:

            # get reference destination
            dest = local["$ref"]
            assert isinstance(dest, str) and dest, "non empty $ref"
            log.debug(f"$ref={dest} ({id_stack} / {resolved} / {url_path})")

            # normalize to root
            if dest.endswith("#"):
                dest += "/"

            # reference patterns, with path = /...:
            # { "$ref": "<full-url>" }
            # { "$ref": "<full-url>#<path>" }
            # { "$ref": "<partial-url>" }
            # { "$ref": "<partial-url>#<path>" }
            # { "$ref": "#<path>" }
            # { "$ref": "#<name>" }

            if is_abs_url(dest):  # full url (http, file, urn) with optional json path
                # log.debug("absolute url")
                pass
            elif "#/" in dest or "#" not in dest:  # relative url with optional json path
                # Oops, what a mess
                # if $id and $ref are together, $ref is NOT relative to this $id up to 7?
                # however the stack is with the local id...
                if version and version <= 7 and "$id" in local:
                    idx = -2
                else:
                    idx = -1
                # switch to full url
                # log.debug("switching to full url")
                base = id_stack[idx]
                if base.url.startswith(("http:", "https:", "file:")):
                    dest = urljoin(base.url, dest)
                elif dest.startswith("#/"):
                    # eg base is urn:...
                    if base.path:
                        dest = "#/" + schemapath_to_urlpath(base.path) + dest[1:]
                        url_path[dest] = dest
                    # else this is the root, dest is fine
                else:
                    log.error(f"cannot handle $ref {dest} at {p}")
                # log.debug(f"join: {local['$ref']} -> {dest}")
            elif dest and dest[0] == "#":  # name? maybe with a path??
                # log.debug("name?")
                pass
            else:
                log.error(f"cannot handle $ref: {dest}")
            # log.debug(f"$ref is now {dest}")
        else:
            dest = None

        # use existing resolutions
        if not dest:
            pass
        elif dest in url_path:
            # substitute with a path
            local["$ref"] = url_path[dest]
        elif is_abs_url(dest):
            # split as url + path
            # TODO path -> anchor
            if "#" in dest:
                url, path = dest.split("#", 1)
            else:
                url, path = dest, None

            log.debug(f"url={url} path={path}")

            # this is the real url part of the reference, without anchor stuff
            init_url = url

            if url is not None:
                assert isinstance(init_url, str)

                # local url mapping for some JSTS tests
                if url in url_path:
                    dest = url_path[url]
                elif url in resolved:  # retrieve local name or path
                    dest = f"#/{defs}/{resolved[url]}"
                else:  # or create a new name for the remote
                    js = resolver.get(url)
                    assert isinstance(js, dict)  # pyright

                    # find next available name
                    while (name := f"_extern_{externs}_") in schema[defs]:  # type: ignore
                        externs += 1

                    assert isinstance(name, str)

                    # upgrade schema for later processing, eg id -> $id
                    if modernize:
                        modernizeOldDraft(js, version=version, level=level)

                    # ensure that hierarchical relative urls are consistent in the target
                    if "$id" not in js:
                        js["$id"] = init_url
                    elif js["$id"] != init_url:
                        log.warning(f"overriding $id in {init_url}")
                        # NOTE should it be #/$defs/name instead?
                        js["$id"] = init_url
                    else:
                        # consistent
                        pass

                    # dest = urls[0] + f"#/{defs}/{name}"
                    # store retrieved url as a local definition
                    resolved[init_url] = name
                    schema[defs][name] = js  # type: ignore

                    dest = f"#/{defs}/{name}"
                    log.warning(f"url_path: {init_url} -> {dest}")
                    url_path[init_url] = dest

                # update external reference to local destination
                # FIXME is this is a local id from the imported schema we do not know it yet!
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
                                log.warning(f"undefined path #{path}")
                                dest = "#" + path
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
                                dest = "#" + path
                                jpath = None

                                # fish from within js
                                # FIXME maybe the recursion should stop on absolute $id?
                                # we look for mere equality, but should be based on the full url
                                def collectFlt(j, p) -> bool:
                                    nonlocal jpath
                                    if isinstance(j, dict) and "$id" in j:
                                        if j["$id"] == dest:
                                            jpath = p
                                            return False
                                        else:
                                            return True
                                    # shortcut once done
                                    return jpath is None

                                recurseSchema(js, init_url, path=(defs, name), flt=collectFlt)

                                if jpath is None:
                                    log.warning(f"undefined $id {dest}")
                                else:
                                    dest = "#/" + schemapath_to_urlpath(jpath)
                    else:
                        dest = urljoin(dest, "#" + path)

                local["$ref"] = dest
            else:
                log.error(f"cannot handle $ref to {dest}")

        return rwtScanPop(local, p)

    # root
    # first pass to populate url_path
    keep_id = True
    schema = recurseSchema(schema, ".", flt=fltExtRef, rwt=rwtScanPop, def_first=True)
    keep_id = False
    # then actual $ref rewriting
    schema = recurseSchema(schema, ".", flt=fltExtRef, rwt=rwtExtRef, def_first=True)

    # recurse in newly added names
    assert isinstance(schema, dict)
    changed = True

    while changed:
        changed = False
        for name in sorted(schema[defs].keys()):  # type: ignore
            if name in processed:
                continue
            processed.add(name)
            changed = True
            keep_id = True
            log.debug(f"onto {name}")
            recurseSchema(
                schema[defs][name], ".", path=((defs, name), ),  # type: ignore
                flt=fltExtRef, rwt=rwtScanPop, def_first=True,
            )
            keep_id = False
            schema[defs][name] = recurseSchema(  # type: ignore
                schema[defs][name], f"#/{defs}/{name}", path=((defs, name), ),  # type: ignore
                flt=fltExtRef, rwt=rwtExtRef, def_first=True,
            )

    # remove defs if empty
    if not schema[defs]:
        del schema[defs]

    if level == logging.DEBUG:
        log.debug(f"resolve ext out: {json.dumps(schema, indent=2)}")

    return schema
