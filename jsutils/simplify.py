# TODO
# oneOf [ { "enum": [] }, { "const": } ]
# import urllib
import logging
from typing import Any
import copy
import json
import re

from .utils import JsonSchema, SchemaPath, JSUError
from .utils import only, schemapath_to_urlpath, decode_url, encode_url, has_none, is_any
from .utils import ALL_TYPES, IGNORE
from .recurse import recurseSchema
from .inline import mergeProperty, mergeSchemas

log = logging.getLogger("simpler")
# log.setLevel(logging.DEBUG)

type JsonPath = list[str|int]

# type-specific properties
# TODO complete
TYPED_PROPS: dict[str, set[str]] = {
    # format: not in theory, quite often in practice
    "string": {"minLength", "maxLength", "pattern"},
    "number": {"minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum", "multipleOf"},
    "object": {
        "additionalProperties", "unevaluatedProperties", "propertyNames", "required",
        "properties", "minProperties", "maxProperties", "patternProperties", "dependencies"
     },
    "array": {
        "items", "minItems", "maxItems", "prefixItems", "contains", "minContains",
        "maxContains", "unevaluatedItems", "additionalItems"
    },
    "boolean": set(),
    "null": set()
}


def incompatibleProps(st: str):
    props = set()
    [ props := props.union(p) for t, p in TYPED_PROPS.items() if t != st ]
    return props


# string-specific predefined formats
# NOTE some extensions use other formats, eg for "int32" for numbers
STRING_FORMATS: set[str] = {
    "date", "date-time", "time", "duration",
    "email", "idn-email",
    "hostname", "idn-hostname", "ipv4", "ipv6",
    "uri", "uri-reference", "uri-template",
    "iri", "iri-reference",
    "uuid",
    "json-pointer", "relative-json-pointer",
    "regex",
}


def counts(lv: list[Any]) -> dict[Any, int]:
    """Count values in list. Probably exists elsewhere."""
    cnt = {}
    for v in lv:
        cnt[v] = (cnt[v] + 1) if v in cnt else 1
    return cnt


def getEnum(ls: list[JsonSchema], is_one: bool) -> list[Any]|None:
    """Attempt to extract a list of constants."""
    assert isinstance(ls, list)
    lv = []
    for s in ls:
        if isinstance(s, dict):
            if "const" in s:
                lv.append(s["const"])
            elif "enum" in s:
                assert isinstance(s["enum"], list)
                lv.extend(dict.fromkeys(s["enum"]))
            else:
                return None
        else:
            return None
    cnt = counts(lv)
    if is_one:
        # fully remove duplicates
        lv = list(filter(lambda i: cnt[i] == 1, lv))
    else:
        # only remove duplicates
        lv = list(dict.fromkeys(lv))
    return lv


def _typeCompat(t: str, v: Any) -> bool:
    """Check JSON type / value compatibility."""
    return ((t == "null" and v is None) or
            (t == "boolean" and isinstance(v, bool)) or
            (t == "number" and isinstance(v, (int, float))) or
            (t == "string" and isinstance(v, str)) or
            (t == "array" and isinstance(v, (list, tuple))) or
            (t == "object" and isinstance(v, dict)))


_IGNORABLE = (
    # core
    "$schema", "$id", "$comment", "$vocabulary", "$anchor", "$dynamicAnchor",
    # metadata
    "description", "title", "readOnly", "writeOnly", "default", "examples", "deprecated",
    # namespace
    "definitions", "$defs",
)

def _ignored(schema: JsonSchema) -> JsonSchema:
    """Remove preperties dans do not need to be considered."""
    if isinstance(schema, bool):
        return schema
    schema = copy.deepcopy(schema)
    for keyword in _IGNORABLE:
        if keyword in schema:
            del schema[keyword]
    return schema

def same(s1: JsonSchema, s2: JsonSchema) -> bool:
    return _ignored(s1) == _ignored(s2)

# a property presence in the object triggers other validations, eg versions 7/8
# {
#   "type": "object",
#   "dependencies": {
#     -- schema form: if foo appears then schema must validate
#     "foo": {
#       ...
#     },
#     -- list form: if bla appears, all liste names are required
#     "bla": [ "xxx", "yyy" ]
#   }
# }
# in later versions this is changed to dependentSchemas (schemas) and dependentRequired (list)
# it is translated as an if/then.
def noDependencies(schema: JsonSchema, path: SchemaPath):
    """Remove "dependencies" in place."""
    assert isinstance(schema, dict)
    # get dependency stuff
    if "dependencies" in schema:
        deps = schema["dependencies"]
        del schema["dependencies"]
        list_ok, schema_ok = True, True
    elif "dependentRequired" in schema:
        deps = schema["dependentRequired"]
        del schema["dependentRequired"]
        list_ok, schema_ok = True, False
    elif "dependentSchemas" in schema:
        deps = schema["dependentSchemas"]
        del schema["dependentSchemas"]
        list_ok, schema_ok = False, True
    assert isinstance(deps, dict)
    # transfer significant props to the copy
    subschema: JsonSchema = {}
    for k, v in list(schema.items()):
        if k not in _IGNORABLE:
            subschema[k] = schema[k]
            del schema[k]
    allOf = [ subschema ]
    # process dependencies
    for key, val in deps.items():
        if isinstance(val, list):
            assert list_ok
            dep = {
                "if": {
                    "type": "object",
                    "required": [ key ]
                 },
                "then": {
                    "type": "object",
                    "required": val
                }
            }
        else:
            assert schema_ok and isinstance(val, (dict, bool))
            dep = {
                "if": {
                    "type": "object",
                    "required": [ key ],
                },
                "then": val
            }
        allOf.append(dep)
    # set root allof
    schema["allOf"] = allOf

def simplifySchema(
            schema: JsonSchema,
            url: str,
            sversion: int = 0,
            level: int = logging.INFO,
        ):
    """Simplify a JSON Schema with various rules."""

    log.setLevel(level)
    if level == logging.DEBUG:
        log.debug(f"simpler in: {json.dumps(schema, indent=2)}")

    # schema version for $ref aggressive pruning
    version: int
    if isinstance(schema, dict) and "$schema" in schema and isinstance(schema["$schema"], str):
        ds = schema["$schema"]
        version = \
            9 if "2020-12" in ds else \
            8 if "2019-09" in ds else \
            7 if "draft-07" in ds else \
            6 if "draft-06" in ds else \
            4 if "draft-04" in ds else \
            3 if "draft-03" in ds else \
            2 if "draft-02" in ds else \
            1 if "draft-01" in ds else \
            sversion or 9
    else:
        version = sversion or 9  # 2020-12

    if sversion and version != sversion:
        log.error(f"incompatible versions, {sversion} set but schema is {version}")

    # TODO more generic dynamicAnchor removal
    # TODO anchor removal?
    # FIXME check that there is only one dynamicAnchor of this name?!
    dynroot: str|None = None
    if isinstance(schema, dict) and "$dynamicAnchor" in schema:
        assert isinstance(schema["$dynamicAnchor"], str)
        dynroot = schema["$dynamicAnchor"]
        del schema["$dynamicAnchor"]

    def fltSimpler(local: JsonSchema, path: SchemaPath) -> bool:
        if isinstance(local, dict):
            if ("dependencies" in local or  # <= 7
                "dependentRequired" in local or "dependentSchemas" in local  # >= 8
            ):
                noDependencies(local, path)

            # resolve some simple local references which may be optimized out
            # but not at/for the root, nor definitions which are all kept
            if "$ref" in local and path != ():
                dest = local["$ref"]
                assert isinstance(dest, str)
                if dest.startswith("#/") and dest != "#/" and \
                        not re.search(r"/(definitions|\$defs)/[^/]+$", dest):
                    log.debug(f"inlining {dest}")
                    js = schema
                    for segment in dest.split("/")[1:]:
                        # log.debug(f"segment = {segment}")
                        segment = decode_url(segment)
                        if isinstance(js, dict):
                            js = js[segment]
                        elif isinstance(js, list):
                            js = js[int(segment)]
                        else:
                            raise Exception(f"unexpected type while following {dest}")
                    if isinstance(js, bool):
                        del local["$ref"]
                        if not js:
                            local.clear()
                            local["type"] = []  # no types is false
                        # else keep local as-is
                    else:
                        del local["$ref"]
                        if sversion and sversion <= 7:
                            for p in list(local.keys()):
                                if p not in _IGNORABLE:
                                    del local[p]
                            local.update(copy.deepcopy(js))
                        else:
                            # actual merge
                            nlocal = mergeSchemas(local, copy.deepcopy(js))
                            local.clear()
                            if isinstance(nlocal, bool):
                                if not nlocal:
                                    local["type"] = []
                            else:
                                local.update(nlocal)
                        log.debug(f"desc schema: {local}")

                # TODO keep track of used path to avoid removing stuff which is referenced
        return True

    def rwtSimpler(local: JsonSchema, path: SchemaPath) -> JsonSchema:

        lpath = ".".join(str(s) for s in path) if path else "."

        if isinstance(local, bool):
            return local
        assert isinstance(local, dict)

        # references
        if "$ref" in local and version <= 7:
            # https://json-schema.org/draft-07/draft-handrews-json-schema-01#rfc.section.8.3
            keep = { p: v for p, v in local.items() if p in _IGNORABLE or p == "$ref" }
            if len(keep) != len(local):
                # FIXME spurious warning on "type" added by an ealier phase
                log.warning(f"dropping all props adjacent to $ref on old schemas at {path}")
            return keep

        if isinstance(dynroot, str):
            if path and "$dynamicAnchor" in local and local["$dynamicAnchor"] == dynroot:
                log.error(f"Ooops: multiple root dynamic anchor: {dynroot}")
                raise Exception("FIXME!")

            if "$dynamicRef" in local:
                dref = local["$dynamicRef"]
                if dref == "#" + dynroot:
                    log.info(f"replacing root $dynamicAnchor with simple $ref at {path}")
                    del local["$dynamicRef"]
                    local["$ref"] = "#"

        # minimum (val >= M) + exclusiveMinimum (val > M)
        if "minimum" in local and "exclusiveMinimum" in local:
            inmini, exmini = local["minimum"], local["exclusiveMinimum"]
            if not isinstance(exmini, bool):  # skip draft4
                assert isinstance(inmini, (int, float)) and isinstance(exmini, (int, float))
                if inmini > exmini:
                    del local["exclusiveMinimum"]
                else:  # exmini >= inmini
                    del local["minimum"]

        # maximum + exclusiveMaximum
        if "maximum" in local and "exclusiveMaximum" in local:
            inmaxi, exmaxi = local["maximum"], local["exclusiveMaximum"]
            if not isinstance(exmaxi, bool):  # skip draft4
                assert isinstance(inmaxi, (int, float)) and isinstance(exmaxi, (int, float))
                if inmaxi < exmaxi:
                    del local["exclusiveMaximum"]
                else:  # exmaxi <= inmaxi
                    del local["maximum"]

        # TODO allOf with some inclusions { "&": [ "", "/.../" ] }
        # TODO anyOf/oneOf/allOf of length 0? are they already dropped?

        # anyOf/oneOf/allOf of length 1
        for prop in ("anyOf", "oneOf", "allOf"):
            if (isinstance(local, dict) and prop in local and
                    len(local[prop]) == 1):  # type: ignore
                saved = copy.deepcopy(local)
                xofs = local[prop][0]
                # NOTE filter out older versions in some cases
                if isinstance(xofs, dict) and "$ref" in xofs and version <= 7:
                    if only(local, prop, *IGNORE):
                        pass
                    elif only(local, "type", prop, *IGNORE) and set(local["type"]) == ALL_TYPES:
                        pass
                    else:
                        # skip as it would induce an adjacent removal optimization
                        continue
                # merge attempt
                try:
                    sub = local.pop(prop)[0]  # pyright: ignore
                    if isinstance(sub, bool):
                        if sub:
                            nschema = local
                        else:
                            nschema = False
                    else:
                        nschema = mergeSchemas(local, sub)
                    # success!
                    local = nschema
                except JSUError as e:
                    log.debug(e)
                    log.warning(f"{prop} of one merge failed")
                    local = saved

        if isinstance(local, bool):
            return local
        assert isinstance(local, dict)

        # TODO detect inconsistent allOf?

        # switch oneOf/anyOf const/enum to enum/const
        for prop in ("oneOf", "anyOf"):
            if prop in local:
                val = local[prop]
                assert isinstance(val, list)
                lv = getEnum(val, prop == "oneOf")  # pyright: ignore
                if lv is not None:
                    del local[prop]
                    log.info(f"{prop} to enum/const/false at {lpath}")
                    if len(lv) == 0:
                        # FIXME check
                        return False
                    else:  # at least one
                        if "enum" in local:
                            lev = local["enum"]
                            del local["enum"]
                            assert isinstance(lev, list)
                            # intersect in initial order
                            nlv = []
                            for v in lev:
                                if v in lv:
                                    nlv.append(v)
                            local["enum"] = nlv
                        else:
                            local["enum"] = lv

        # void condition application
        for kw in ("then", "else"):
            if kw in local:
                subs = local[kw]
                if isinstance(subs, bool):
                    continue
                assert isinstance(subs, dict)
                compat = True
                for k, v in subs.items():
                    if k in _IGNORABLE:
                        pass
                    elif k in local and v == local[k]:
                        pass
                    elif k in local:
                        # special case, check for inclusion
                        if k == "required":
                            assert "required" in local and isinstance(local["required"], list)
                            assert isinstance(v, list)  # and str
                            for n in v:
                                if n not in local["required"]:
                                    compat = False
                    else:
                        compat = False
                if compat:
                    log.info(f"removing ineffective {kw}")
                    del local[kw]

        # if/then/else
        if "if" not in local:
            for kw in ("then", "else"):
                if kw in local:
                    log.info(f"removing {kw} without if")
                    del local[kw]
        if "if" in local and not ("then" in local or "else" in local):
            log.info(f"removing lone if at {path}")
            del local["if"]

        # simplify condition if possible
        if "if" in local:
            cond = local["if"]
            if isinstance(cond, bool):
                if cond and "else" in local:
                    del local["else"]
                    if "then" not in local:
                        del local["if"]
                if not cond and "then" in local:
                    if "else" in local:
                        local["if"] = True
                        local["then"] = local["else"]
                        del local["else"]
                    else:
                        del local["then"]
                        del local["if"]
            elif "not" in cond and only(cond, "not", *_IGNORABLE):
                log.info("simplifying if not")
                local["if"] = cond["not"]
                sthen = local.get("then", None)
                selse = local.get("else", None)
                if sthen is not None:
                    local["else"] = sthen
                    if selse is not None:
                        local["then"] = selse
                    else:
                        del local["then"]
                else:
                    assert selse is not None
                    local["then"] = selse
                    del local["else"]

        if "not" in local:
            nots = local["not"]
            if isinstance(nots, bool):
                if nots:  # "not true"
                    del local["not"]
                    if "allOf" not in local:
                        local["allOf"] = []
                    local["allOf"].append(False)
                else:  # ignore "not false"
                    del local["not"]
            # else:
            #     assert isinstance(nots, dict)
            #     if only(nots, "not", "type", *_IGNORABLE):
            #         # not not X = X (is this true with schemas)
            #         notnots = nots["not"]
            #         del local["not"]
            #         if "allOf" not in local:
            #             local["allOf"] = []
            #         local["allOf"].append(notnots)
            #     # else keep it

        if "unevaluatedProperties" in local:
            up = local["unevaluatedProperties"]
            # NOTE cannot remove up as it may be shadowing another up
            # thus cleanup is delayed to convert
            if ("additionalProperties" not in local and
                  has_none(local, "allOf", "anyOf", "oneOf", "$ref", "$dynamicRef",
                           "if", "then", "else", "patternProperties")):
                # FIXME consider more in-place stuff? if/then/else
                local["additionalProperties"] = local.pop("unevaluatedProperties")
                # NOTE cannot move to additionalProperties in constructed cases

        # short type list
        if "type" in local and isinstance(local["type"], list):
            types = local["type"]
            if len(types) == 0:
                return False
            elif len(types) == 1:
                local["type"] = types[0]
        # type/props…
        if "type" in local and isinstance(local["type"], str):
            stype = local["type"]
            if stype == "number":
                if "multipleOf" in local and local["multipleOf"] == 1:
                    local["type"] = "integer"
                    del local["multipleOf"]
            if stype == "integer":
                if "multipleOf" in local and local["multipleOf"] == 1:
                    del local["multipleOf"]
                # use this for later type-related checks
                stype = "number"
            # remove type-specific properties
            if stype in TYPED_PROPS:
                for p in incompatibleProps(stype):
                    if p in local:
                        log.info(f"unused property {p} for {stype} at {lpath}")
                        del local[p]
            if stype != "string" and "format" in local and local["format"] in STRING_FORMATS:
                log.info(f"unused string format on {stype}: {schema['format']}")
                del local["format"]
            # type/const
            if "const" in local:
                cst = local["const"]
                if _typeCompat(stype, cst):
                    log.info(f"removing redundant type with const at {lpath}")
                    del local["type"]
                else:
                    log.info(f"incompatible type {stype} for {cst} at {lpath}")
                    return False
            # type/enum
            if "enum" in local:
                vals = local["enum"]
                assert isinstance(vals, list)
                nvals = list(filter(lambda v: _typeCompat(stype, v), vals))
                if len(vals) != len(nvals):
                    log.info(f"removing {len(vals) - len(nvals)} incompatible values "
                             f"from enum at {lpath}")
                    local["enum"] = nvals
                del local["type"]
            # simplify any array
            if stype == "array":
                simpler = _ignored(local)
                assert isinstance(simpler, dict)  # pyright hint
                if len(simpler) == 2 and "type" in local:
                    # lone keyword
                    for kw in ("items", "additionalItems", "unevaluatedItems"):
                        if kw in local:
                            subschema = _ignored(local[kw])  # pyright: ignore
                            if subschema in (True, {}):
                                log.info(f"removing useless {kw} keyword at {lpath}")
                                del local[kw]
            # simplify any object
            if stype == "object":
                simpler = _ignored(local)
                assert isinstance(simpler, dict)  # pyright hint
                if len(simpler) == 2 and "type" in local:
                    # lone keyword without effect
                    for kw in ("additionalProperties", "unevaluatedProperties"):
                        if kw in local:
                            subschema = _ignored(local[kw])  # pyright: ignore
                            if subschema in (True, {}):
                                log.info(f"removing useless {kw} keyword at {lpath}")
                                del local[kw]

                # simplify propertyNames + additionalProperties to patternProperties
                if "propertyNames" in local and "additionalProperties" in local and \
                        "properties" not in local and "patternProperties" not in local:
                    pn = local["propertyNames"]
                    assert isinstance(pn, dict)
                    ap = local["additionalProperties"]
                    if "pattern" in pn and only(pn, "pattern", "type", *_IGNORABLE):
                        log.info("switching propertyNames and additionalProperties to "
                                 f"patternProperties at {lpath}")
                        del local["propertyNames"]
                        del local["additionalProperties"]
                        assert isinstance(pn["pattern"], str)
                        local["patternProperties"] = { pn["pattern"]: ap }

        # const/enum
        if "const" in local and "enum" in local:
            log.info(f"const/enum at {lpath}")
            assert isinstance(local["enum"], list)
            if local["const"] in local["enum"]:
                del local["enum"]
            else:
                return False
        elif "enum" in local:
            assert isinstance(local["enum"], list)
            nenum = len(local["enum"])
            if nenum == 0:
                log.info(f"empty enum at {lpath}")
                return False
            elif nenum == 1:
                log.info(f"enum of one at {lpath}")
                local["const"] = local["enum"][0]
                del local["enum"]

        # min/maxContains without contains are ignored, and should be ints
        if "minContains" in local:
            if "contains" not in local:
                del local["minContains"]
            elif isinstance(local["minContains"], float):
                local["minContains"] = int(local["minContains"])
        if "maxContains" in local:
            if "contains" not in local:
                del local["maxContains"]
            elif isinstance(local["maxContains"], float):
                local["maxContains"] = int(local["maxContains"])

        return local

    schema = recurseSchema(schema, url, flt=fltSimpler, rwt=rwtSimpler)

    if level == logging.DEBUG:
        log.debug(f"simpler out: {json.dumps(schema, indent=2)}")

    return schema

#
# move definitions at the root and resolve ids
#
def _defId(schema) -> tuple[str|None, str|None]:
    """return name of definitions and id properties."""
    if not isinstance(schema, dict):
        return (None, None)
    defn = "$defs" if "$defs" in schema else \
           "definitions" if "definitions" in schema else \
           None
    idn = "$id" if "$id" in schema else \
          "id" if "id" in schema else \
          None
    return (defn, idn)


_SUBCOUNT: int = 0

def _scopeSubDefs(
            schema: JsonSchema,
            defs: dict[str, JsonSchema],
            rootdef: str,
            moved: dict[str, str],
            ids: dict[str, str],
            delete: list[tuple[Any, str, str|None, str|None, str|None, JsonPath]],
            path: JsonPath = []
        ):
    """Move definitions at the root."""

    log.debug(f"handing $ids/$defs at {path}")

    global _SUBCOUNT
    defn, idn = _defId(schema)
    if defn is None:
        return

    assert isinstance(schema, dict)
    assert isinstance(defn, str)
    sdefs = schema[defn]
    assert isinstance(sdefs, dict)
    log.debug(f"defn={defn}")

    if path and defn and not idn:
        # nested definitions, move them up

        prefix = f"_defs_{_SUBCOUNT}_"
        _SUBCOUNT += 1

        for name, sschema in sdefs.items():

            assert isinstance(sschema, dict)

            # FIXME name may be quite ugly… eg a full URL
            if "/" not in name and "%" not in name:  # reuse name if simple
                new_name = prefix + name
                old_name = name
            else:
                new_name = f"_dsub_{_SUBCOUNT}_"
                _SUBCOUNT += 1
                old_name = encode_url(name)
            npath = rootdef + "/" + new_name
            opath = f"#/{schemapath_to_urlpath(path)}/{defn}/{old_name}"  # type: ignore
            sschema["$comment"] = f"origin: {opath}"
            moved[opath] = npath
            defs[new_name] = sschema

        schema["$comment"] = f"{defn} {_SUBCOUNT} moved"

        assert defn in schema
        delete.append((schema, defn, None, None, None, path))

    elif path and defn and idn:
        # if we have a nested id, we move definitions to defs and rewrite local refs

        sid = schema[idn]
        assert isinstance(sid, str)

        del schema[idn]
        if "id" in schema:  # WTF: both $id and id…
            log.warning(f"schema has both 'id' and '$id' at {path}")
            del schema["id"]

        # keep track of changes
        schema["$comment"] = f"{idn} {_SUBCOUNT}: {sid}"

        prefix = f"_id_{_SUBCOUNT}_"
        _SUBCOUNT += 1

        # to remap long references later
        # we have a local path for an external url
        ids[sid] = rootdef + "/" + prefix
        iddefs = f"#/{defn}/"
        # id's defs with be there
        moved[sid + iddefs] = rootdef + "/" + prefix

        # remap all sub-schema local references
        def rwtRef(schema, lpath):
            if isinstance(schema, dict) and "$ref" in schema:
                dest = schema["$ref"]
                assert isinstance(dest, str)
                if dest.startswith(iddefs):  # local ref
                    schema["$ref"] = rootdef + "/" + prefix + dest[len(iddefs):]
                elif dest in ("#", "#/"):  # myself, will have to be made consistent later!
                    schema["$ref"] = ids[sid]
            return schema

        recurseSchema(schema, "", rwt=rwtRef)

        # move local definitions as global
        for name, sschem in sdefs.items():
            pname = prefix + name
            assert pname not in defs
            assert isinstance(sschem, (bool, dict))
            defs[pname] = sschem

        # we need to keep the schema in place for handling arbitrary url
        # whole object will be moved later
        assert defn in schema
        delete.append((schema, defn, prefix, ids[sid], sid, path))

def scopeDefs(schema: JsonSchema, version: int|None = None, level: int = logging.INFO):
    """Move internal definitions/$defs to root schema, possibly handing nested $id"""

    log.setLevel(level)
    if level == logging.DEBUG:
        log.debug(f"scope in: {json.dumps(schema, indent=2)}")

    # collect $id/id and $defs/definitions
    todo_ids, todo_defs = [], []

    def fltDefs(schema, path):
        if path and isinstance(schema, dict):
            defn, idn = _defId(schema)
            if idn is not None:
                todo_ids.append((schema, path))
            # FIXME elif?
            elif defn is not None:
                todo_defs.append((schema, path))
        return True

    recurseSchema(schema, "", flt=fltDefs)

    # early exit if nothing to scope
    if not todo_ids and not todo_defs:
        return

    # ensure definitions root
    assert isinstance(schema, dict)
    defn, idn = _defId(schema)

    if defn is None:
        defn = "$defs" if not version or version >= 8 else "definitions"
        schema[defn] = {}

    # do internal renamings
    rootdef, moved, ids, delete = f"#/{defn}", {}, {}, []

    for s, p in todo_ids:
        _scopeSubDefs(s, schema[defn], rootdef, moved, ids, delete, p)  # type: ignore

    for s, p in todo_defs:
        _scopeSubDefs(s, schema[defn], rootdef, moved, ids, delete, p)  # type: ignore

    # move arbitrary references
    def mvRef(rschema, path):
        if isinstance(rschema, dict) and "$ref" in rschema:
            dest = rschema["$ref"]
            log.debug(f"found {dest} at {path}")
            if dest in ("#/", "#"):
                pass
            elif dest.startswith("#/") and dest not in moved:
                dpath = dest[2:].split("/")
                if len(dpath) != 2 or dpath[0] != defn:
                    # not a simple name, follow path
                    jdest = schema
                    for segment in dpath:
                        if isinstance(jdest, dict):
                            segment = decode_url(segment)
                            jdest = jdest[segment]
                        elif isinstance(jdest, list):
                            jdest = jdest[int(segment)]  # TODO proper exception
                        else:
                            raise Exception(f"cannot follow path {dpath} at {segment}")
                    global _SUBCOUNT
                    name = f"_psub_{_SUBCOUNT}_"
                    _SUBCOUNT += 1
                    ndest = f"#/{defn}/{name}"
                    # log.info(f"moving {dest} to {ndest}")
                    schema[defn][name] = copy.deepcopy(jdest)  # type: ignore
                    rschema["$ref"] = ndest
                    moved[dest] = ndest  # for other identical references
                # TODO also rename ugly references?
        return rschema

    recurseSchema(schema, "", rwt=mvRef)

    # do full url renamings and other references renamings
    def rwtGref(schema, path):
        if isinstance(schema, dict) and "$ref" in schema:
            dest = schema["$ref"]
            assert isinstance(dest, str), f"str $ref at {path}"
            if dest in moved:
                schema["$ref"] = moved[dest]
            elif dest and dest[0] != "#":
                # inefficient
                for old, new in moved.items():
                    if dest.startswith(old):
                        # log.warning(f"dest={dest} old={old} new={new}")
                        schema["$ref"] = new + dest[len(old):]
                    if dest in ids:
                        log.warning(f"rewriting raw url: {dest} as {ids[dest]}")
                        schema["$ref"] = ids[dest]
        return schema

    recurseSchema(schema, ".", rwt=rwtGref)

    # cleanup internal definitions
    for j, n, prefix, dest, sid, path in delete:
        log.debug(f"cleanup {n} at {path}")
        # if n in j:  # NOTE maybe it was already deleted…
        #     del j[n]
        #     log.debug(f"cleaned: j={j}")
        if prefix is not None:
            # move whole id-ed object as global as well, replaced with a ref
            schema[defn][prefix] = { p: s for p, s in j.items() }  # type: ignore
            j.clear()
            j["$comment"] = f"{sid} moved as $def"
            j["$ref"] = dest

    # remove non root "$defs" and "definitions"
    def rwtCleanDefs(schema: JsonSchema, path: SchemaPath) -> JsonSchema:
        if path and isinstance(schema, dict):
            if "$defs" in schema:
                del schema["$defs"]
            if "definitions" in schema:
                del schema["definitions"]
        return schema

    recurseSchema(schema, ".", rwt=rwtCleanDefs)

    if level == logging.DEBUG:
        log.debug(f"scope out: {json.dumps(schema, indent=2)}")
