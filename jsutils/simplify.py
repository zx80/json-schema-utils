# TODO
# oneOf [ { "enum": [] }, { "const": } ]
# import urllib
from typing import Any
import copy
from .utils import JsonSchema, log, JSUError, only
from .recurse import recurseSchema
from .inline import mergeProperty

# type-specific properties
# TODO complete
TYPED_PROPS: dict[str, set[str]] = {
    # format: not in theory, quite often in practice
    "string": {"minLength", "maxLength", "pattern"},
    "number": {"minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum", "multipleOf"},
    "object": {"additionalProperties", "unevaluatedProperties", "propertyNames", "required",
               "properties", "minProperties", "maxProperties", "patternProperties"},
    "array": {"items", "minItems", "maxItems", "prefixItems", "contains", "minContains",
              "maxContains", "unevaluatedItems", "additionalItems"},
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

def simplifySchema(schema: JsonSchema, url: str):
    """Simplify a JSON Schema with various rules."""

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
            9
    else:
        version = 9  # 2020-12

    # TODO more generic dynamicAnchor removal
    # TODO anchor removal?
    # FIXME check that there is only one dynamicAnchor of this name?!
    dynroot: str|None = None
    if isinstance(schema, dict) and "$dynamicAnchor" in schema:
        assert isinstance(schema["$dynamicAnchor"], str)
        dynroot = schema["$dynamicAnchor"]
        del schema["$dynamicAnchor"]

    def rwtSimpler(schema: JsonSchema, path: list[str]) -> JsonSchema:

        lpath = ".".join(path) if path else "."

        if isinstance(schema, bool):
            return schema
        assert isinstance(schema, dict)

        # references
        if "$ref" in schema and version <= 7:
            # https://json-schema.org/draft-07/draft-handrews-json-schema-01#rfc.section.8.3
            keep = { p: v for p, v in schema.items() if p in _IGNORABLE or p == "$ref" }
            if len(keep) != len(schema):
                log.warning(f"dropping all props adjacent to $ref on old schemas at {path}")
            return keep

        if isinstance(dynroot, str):
            if path and "$dynamicAnchor" in schema and schema["$dynamicAnchor"] == dynroot:
                log.error(f"Ooops: multiple root dynamic anchor: {dynroot}")
                raise Exception("FIXME!")

            if "$dynamicRef" in schema:
                dref = schema["$dynamicRef"]
                if dref == "#" + dynroot:
                    log.info(f"replacing root $dynamicAnchor with simple $ref at {path}")
                    del schema["$dynamicRef"]
                    schema["$ref"] = "#"

        # TODO anyOf/oneOf/allOf of length 0?
        # anyOf/oneOf/allOf of length 1
        for prop in ("anyOf", "oneOf", "allOf"):
            if (isinstance(schema, dict) and prop in schema and
                    len(schema[prop]) == 1):  # type: ignore
                try:
                    nschema = copy.deepcopy(schema)
                    sub = schema[prop][0]  # pyright: ignore
                    for p, v in sub.items():  # pyright: ignore
                        nschema = mergeProperty(nschema, p, v)
                    # success!
                    schema = nschema
                    if isinstance(schema, dict):
                        del schema[prop]
                except JSUError as e:
                    log.debug(e)
                    log.warning(f"{prop} of one merge failed")

        if isinstance(schema, bool):
            return schema
        assert isinstance(schema, dict)

        # TODO detect inconsistent allOf?

        # switch oneOf/anyOf const/enum to enum/const
        for prop in ("oneOf", "anyOf"):
            if prop in schema:
                val = schema[prop]
                assert isinstance(val, list)
                lv = getEnum(val, prop == "oneOf")  # pyright: ignore
                if lv is not None:
                    del schema[prop]
                    log.info(f"{prop} to enum/const/false at {lpath}")
                    if len(lv) == 0:
                        # FIXME check
                        return False
                    else:  # at least one
                        if "enum" in schema:
                            lev = schema["enum"]
                            del schema["enum"]
                            assert isinstance(lev, list)
                            # intersect in initial order
                            nlv = []
                            for v in lev:
                                if v in lv:
                                    nlv.append(v)
                            schema["enum"] = nlv
                        else:
                            schema["enum"] = lv

        # void condition application
        for kw in ("then", "else"):
            if kw in schema:
                subs = schema[kw]
                assert isinstance(subs, dict)
                compat = True
                for k, v in subs.items():
                    if k in _IGNORABLE:
                        pass
                    elif k in schema and v == schema[k]:
                        pass
                    elif k in schema:
                        # special case, check for inclusion
                        if k == "required":
                            assert "required" in schema and isinstance(schema["required"], list)
                            assert isinstance(v, list)  # and str
                            for n in v:
                                if n not in schema["required"]:
                                    compat = False
                    else:
                        compat = False
                if compat:
                    log.info(f"removing ineffective {kw}")
                    del schema[kw]

        # if/then/else
        if "if" not in schema:
            for kw in ("then", "else"):
                if kw in schema:
                    log.info(f"removing {kw} without if")
                    del schema[kw]
        if "if" in schema and not ("then" in schema or "else" in schema):
            log.info(f"removing lone if at {path}")
            del schema["if"]

        # simplify condition if possible
        if "if" in schema:
            cond = schema["if"]
            assert isinstance(cond, dict)
            if "not" in cond and only(cond, "not", *_IGNORABLE):
                log.info("simplifying if not")
                schema["if"] = cond["not"]
                sthen = schema.get("then", None)
                selse = schema.get("else", None)
                if sthen is not None:
                    schema["else"] = sthen
                    if selse is not None:
                        schema["then"] = selse
                    else:
                        del schema["then"]
                else:
                    assert selse is not None
                    schema["then"] = selse
                    del schema["else"]

        # short type list
        if "type" in schema and isinstance(schema["type"], list):
            types = schema["type"]
            if len(types) == 0:
                return False
            elif len(types) == 1:
                schema["type"] = types[0]
        # type/props…
        if "type" in schema and isinstance(schema["type"], str):
            stype = schema["type"]
            if stype == "number":
                if "multipleOf" in schema and schema["multipleOf"] == 1:
                    schema["type"] = "integer"
                    del schema["multipleOf"]
            if stype == "integer":
                if "multipleOf" in schema and schema["multipleOf"] == 1:
                    del schema["multipleOf"]
                # use this for later type-related checks
                stype = "number"
            # remove type-specific properties
            if stype in TYPED_PROPS:
                for p in incompatibleProps(stype):
                    if p in schema:
                        log.info(f"unused property {p} for {stype} at {lpath}")
                        del schema[p]
            if stype != "string" and "format" in schema and schema["format"] in STRING_FORMATS:
                log.info(f"unused string format on {stype}: {schema['format']}")
                del schema["format"]
            # type/const
            if "const" in schema:
                cst = schema["const"]
                if _typeCompat(stype, cst):
                    log.info(f"removing redundant type with const at {lpath}")
                    del schema["type"]
                else:
                    log.info(f"incompatible type {stype} for {cst} at {lpath}")
                    return False
            # type/enum
            if "enum" in schema:
                vals = schema["enum"]
                assert isinstance(vals, list)
                nvals = list(filter(lambda v: _typeCompat(stype, v), vals))
                if len(vals) != len(nvals):
                    log.info(f"removing {len(vals) - len(nvals)} incompatible values "
                             f"from enum at {lpath}")
                    schema["enum"] = nvals
                del schema["type"]
            # simplify any array
            if stype == "array":
                simpler = _ignored(schema)
                assert isinstance(simpler, dict)  # pyright hint
                if len(simpler) == 2 and "type" in schema:
                    # lone keyword
                    for kw in ("items", "additionalItems", "unevaluatedItems"):
                        if kw in schema:
                            subschema = _ignored(schema[kw])  # pyright: ignore
                            if subschema in (True, {}):
                                log.info(f"removing useless {kw} keyword at {lpath}")
                                del schema[kw]
            # simplify any object
            if stype == "object":
                simpler = _ignored(schema)
                assert isinstance(simpler, dict)  # pyright hint
                if len(simpler) == 2 and "type" in schema:
                    # lone keyword
                    for kw in ("additionalProperties", "unevaluatedProperties"):
                        if kw in schema:
                            subschema = _ignored(schema[kw])  # pyright: ignore
                            if subschema in (True, {}):
                                log.info(f"removing useless {kw} keyword at {lpath}")
                                del schema[kw]

                # simplify propertyNames + additionalProperties to patternProperties
                if "propertyNames" in schema and "additionalProperties" in schema and \
                        "properties" not in schema and "patternProperties" not in schema:
                    pn = schema["propertyNames"]
                    assert isinstance(pn, dict)
                    ap = schema["additionalProperties"]
                    if "pattern" in pn and only(pn, "pattern", "type", *_IGNORABLE):
                        log.info("switching propertyNames and additionalProperties to "
                                 f"patternProperties at {lpath}")
                        del schema["propertyNames"]
                        del schema["additionalProperties"]
                        assert isinstance(pn["pattern"], str)
                        schema["patternProperties"] = { pn["pattern"]: ap }

        # const/enum
        if "const" in schema and "enum" in schema:
            log.info(f"const/enum at {lpath}")
            assert isinstance(schema["enum"], list)
            if schema["const"] in schema["enum"]:
                del schema["enum"]
            else:
                return False
        elif "enum" in schema:
            assert isinstance(schema["enum"], list)
            nenum = len(schema["enum"])
            if nenum == 0:
                log.info(f"empty enum at {lpath}")
                return False
            elif nenum == 1:
                log.info(f"enum of one at {lpath}")
                schema["const"] = schema["enum"][0]
                del schema["enum"]

        return schema

    return recurseSchema(schema, url, rwt=rwtSimpler)


#
# move definitions at the root and resolve ids
#
from urllib.parse import quote, unquote


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

# TODO handle arbitrary path references

def _scopeSubDefs(schema: JsonSchema, defs: dict[str, JsonSchema], rootdef: str,
                  moved: dict[str, str], ids: dict[str, str],
                  delete: list[tuple[Any, str, str|None, str|None, str|None]],
                  path: list[str|int] = []):

    log.debug(f"handing $ids/$defs at {path}")

    global _SUBCOUNT
    defn, idn = _defId(schema)
    if defn is None:
        return

    assert isinstance(schema, dict)
    assert isinstance(defn, str)
    sdefs = schema[defn]
    assert isinstance(sdefs, dict)

    if path and defn and not idn:
        # nested definitions, move them up

        prefix = f"_defs_{_SUBCOUNT}_"
        _SUBCOUNT += 1

        for name, sschema in sdefs.items():

            assert isinstance(sschema, dict)

            # FIXME name may be quite ugly… eg a full URL
            if "/" not in name:  # reuse name if simple
                new_name = prefix + name
                old_name = name
            else:
                new_name = f"_dsub_{_SUBCOUNT}_"
                _SUBCOUNT += 1
                old_name = quote(name).replace("~", "~0").replace("/", "~1")
            npath = rootdef + "/" + new_name
            opath = f"#/{'/'.join(path)}/{defn}/{old_name}"  # type: ignore
            sschema["$comment"] = f"origin: {opath}"
            moved[opath] = npath
            defs[new_name] = sschema

        schema["$comment"] = f"{defn} {_SUBCOUNT} moved"

        delete.append((schema, defn, None, None, None))

    elif path and defn and idn:
        # if we have a nested id, we move definitions to defs and rewrite local refs

        sid = schema[idn]
        assert isinstance(sid, str)

        del schema[idn]
        if "id" in schema:  # WTF: both $id and id…
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
        # "#/" + "/".join(p if "/" not in p and "%" not in p else
        #                            quote(p).replace("~", "~0").replace("/", "~1")
        #                                for p in path)

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
        delete.append((schema, defn, prefix, ids[sid], sid))


def scopeDefs(schema: JsonSchema):
    """Move internal definitions/$defs to root schema, possibly handing nested $id"""

    # collect $id/id and $defs/definitions
    todo_ids, todo_defs = [], []

    def fltDefs(schema, path):
        if path and isinstance(schema, dict):
            defn, idn = _defId(schema)
            if idn is not None:
                todo_ids.append((schema, path))
            elif defn is not None:
                todo_defs.append((schema, path))
        return True

    recurseSchema(schema, "", flt=fltDefs)

    if not todo_ids and not todo_defs:
        return

    # ensure definitions root
    assert isinstance(schema, dict)
    defn, idn = _defId(schema)

    if defn is None:
        defn = "$defs"
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
            # log.debug(f"found {dest} at {path}")
            if dest.startswith("#/") and dest not in moved:
                dpath = dest[2:].split("/")
                if len(dpath) != 2 or dpath[0] != defn:
                    # not a simple name, follow path
                    jdest = schema
                    for segment in dpath:
                        if isinstance(jdest, dict):
                            # hmmm
                            if segment in jdest:
                                jdest = jdest[segment]
                            elif "~" in segment or "%" in segment:
                                segment = unquote(segment).replace("~1", "/").replace("~0", "~")
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

    recurseSchema(schema, "", rwt=rwtGref)

    # cleanup internal definitions
    for j, n, prefix, dest, sid in delete:
        del j[n]
        if prefix is not None:
            # move whole id-ed object as global as well, replaced with a ref
            schema[defn][prefix] = { p: s for p, s in j.items() }  # type: ignore
            j.clear()
            j["$comment"] = f"{sid} moved as $def"
            j["$ref"] = dest
