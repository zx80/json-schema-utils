import json

from .utils import JsonSchema, SchemaPath, Jsonable, log, only, IGNORE
from .recurse import recurseSchema, goFlt, noRwt

type Types = int

NONE: Types = 0
NULL: Types = 1
BOOLEAN: Types = 2
INTEGER: Types = 4
FLOAT: Types = 8
NUMBER: Types = 8 # 12
STRING: Types = 16
ARRAY: Types = 32
OBJECT: Types = 64
ALL: Types = 127


def types2list(t: Types) -> list[str]:
    types: list[str] = []
    if t & NULL:
        types.append("null")
    if t & BOOLEAN:
        types.append("boolean")
    if t & INTEGER:
        types.append("integer")
    if t & NUMBER:
        types.append("number")
    if t & STRING:
        types.append("string")
    if t & ARRAY:
        types.append("array")
    if t & OBJECT:
        types.append("object")
    return types

TYPE2TYPE: dict[type, Types] = {
    type(None): NULL,
    bool: BOOLEAN,
    int: INTEGER,
    float: FLOAT,
    str: STRING,
    list: ARRAY,
    dict: OBJECT,
}

def val2type(value: Jsonable) -> Types:
    tvalue = type(value)
    if tvalue in TYPE2TYPE:
        return TYPE2TYPE[tvalue]
    else:
        raise Exception(f"unexpected constant value for typing: {value}")

NAME2TYPE: dict[str, Types] = {
    "null": NULL,
    "boolean": BOOLEAN,
    "bool": BOOLEAN,
    "integer": INTEGER,  # int?
    "float": FLOAT,  # FIXME
    "number": NUMBER,
    "string": STRING,
    "array": ARRAY,
    "object": OBJECT,
    "any": ALL,
}

def name2type(name: str) -> Types:
    if name in NAME2TYPE:
        return NAME2TYPE[name]
    else:
        raise Exception(f"unexpected type name for typing: {name}")

# TODO move as a context?
_types: dict[SchemaPath, Types] = {}

# how definitions are named
defs: str = "$defs"

# where are dynamicAnchor defined and used
dynAnchors: dict[str, set[SchemaPath]] = {}
dynRefs: dict[str, set[SchemaPath]] = {}

# dynRefPaths: dict[SchemaPath, str] = {}

# where are references (normalized keys?!)
references: dict[SchemaPath, set[SchemaPath]] = {}


class FILOSet:

    def __init__(self):
        self._set: set[SchemaPath] = set()
        self._list: list[SchemaPath] = []

    def __len__(self) -> int:
        return len(self._set)

    def pop(self) -> SchemaPath:
        item = self._list.pop()
        self._set.remove(item)
        return item

    def add(self, item: SchemaPath) -> None:
        if item not in self._set:
            self._list.append(item)
            self._set.add(item)

    def append(self, paths: set[SchemaPath]) -> None:
        for p in sorted(paths):
            self.add(p)


# propagation iterations
todo: FILOSet = FILOSet()

# type initialization
def typeFlt(schema: JsonSchema, path: SchemaPath) -> bool:

    # we will have to come back
    todo.add(path)

    if isinstance(schema, bool):
        _types[path] = ALL if schema else NONE
    else:
        assert isinstance(schema, dict)

        # collect direct type hints from type, const and enum
        types: Types = ALL

        # hmmm?!
        if path and path[-1] == "propertyNames":
            types &= STRING

        if "const" in schema:
            types &= val2type(schema["const"])

        if "type" in schema:
            stype = schema["type"]
            if isinstance(stype, str):
                types &= name2type(stype)
            elif isinstance(stype, list):
                ltypes = NONE
                for tn in stype:
                    ltypes |= name2type(tn)  # type: ignore
                types &= ltypes
            else:
                raise Exception("unexpected prop \"type\" value: {stype}")

        if "enum" in schema:
            values = schema["enum"]
            assert isinstance(values, list)
            if "const" in schema:
                if schema["const"] in values:
                    del schema["enum"]
                else:  # not feasible
                    types = NONE
            else:
                ntypes = NONE
                todelete = []
                for i, v in enumerate(values):
                    ltypes = val2type(v)
                    ntypes |= ltypes
                    # filter enum with type information
                    if ltypes & types == 0:
                        todelete.append(i)
                if todelete:
                    for i in reversed(sorted(todelete)):
                        del values[i]
                    schema["enum"] = values
                    todo.add(path)
                types &= ntypes

        # not: true
        if "not" in schema:
            nots = schema["not"]
            if isinstance(nots, bool) and nots:
                types = NONE

        _types[path] = types

        # build propagation graph
        if "$ref" in schema:
            name = schema["$ref"]
            assert isinstance(name, str)
            if name.startswith("#/"):
                name = name[2:]
            elif name.startswith("#./"):
                name = name[3:]
            else:
                log.warning(f"unclear $ref: {name}")
            rpath = tuple(name.split("/"))
            if len(rpath) != 2:
                log.warning(f"$ref depth?: {name}")
            if name not in references:
                references[rpath] = set()
            references[rpath].add(path)

        # dynamic anchors X and reference #X (why?)
        if "$dynamicAnchor" in schema:
            name = schema["$dynamicAnchor"]
            assert isinstance(name, str)
            if name not in dynAnchors:
                dynAnchors[name] = set()
            dynAnchors[name].add(path)

        if "$dynamicRef" in schema:
            name = schema["$dynamicRef"]
            assert isinstance(name, str)
            if name.startswith("#"):
                name = name[1:]
            if name not in dynRefs:
                dynRefs[name] = set()
            dynRefs[name].add(path)

    return True


# iterative type mostly upward propagation
def updateTypes(schema: JsonSchema, path: SchemaPath):

    init_types: Types = _types.get(path, ALL)

    if isinstance(schema, bool):
        if schema:
            assert init_types == ALL
        else:
            assert init_types == NONE
        return

    assert isinstance(schema, dict)
    types: Types = init_types

    if "allOf" in schema:
        assert isinstance(schema["allOf"], list)
        for i, _ in enumerate(schema["allOf"]):
            lpath = path + (("allOf", i), )
            ltypes = _types.get(lpath)
            types &= ltypes  # type: ignore
            if ltypes != types:  # smaller, push downward!
                _types[lpath] = types
                todo.add(path)  # we may have to retry

    for op in ("anyOf", "oneOf"):
        if op in schema:
            ntypes = NONE
            assert isinstance(schema[op], list)
            for i, s in enumerate(schema[op]):  # type: ignore
                lpath = path + ((op, i), )
                ltypes = _types.get(lpath)
                ntypes |= ltypes  # type: ignore
                if ltypes & types != ltypes:  # type: ignore
                    _types[lpath] = ltypes & types  # type: ignore
                    todo.add(path)  # we may have to retry
            types &= ntypes  # type: ignore

    if "$ref" in schema:
        name = schema["$ref"]
        assert isinstance(name, str)  # pyright
        for prefix in (f"#/{defs}/", f"#./{defs}/"):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        types &= _types.get(((defs, name),), ALL)  # type: ignore

    if "$dynamicRef" in schema:
        name = schema["$dynamicRef"]
        assert isinstance(name, str)  # pyright
        if name.startswith("#"):
            name = name[1:]
        if name in dynAnchors:
            ntypes = NONE
            for p in sorted(dynAnchors[name]):
                ntypes |= _types[p]
            types &= ntypes  # type: ignore
        else:
            log.warning(f"undefined anchor {name} used at {path}")

    # derive type from then/else if they may be executed
    if "if" in schema and "then" in schema and "else" in schema:
        types &= _types[path + ("then",)] | _types[path + ("else",)]

    # "if" is a pain, we cannot know easily whether we are inside, so we push down for here
    # let's ignore then/else for now?
    if "if" in schema and isinstance(schema["if"], dict):
        if_path: SchemaPath = path + ("if", )  # type: ignore
        if_types: Types = _types[if_path]
        if if_types != types:
            _types[if_path] = types & if_types  # type: ignore

    # NOTE propagate only if type-only
    if "not" in schema and isinstance(schema["not"], dict):
        if only(schema["not"], "type", *IGNORE):
            types &= ~ _types[path + ("not",)]

    # on changes keep iterating
    if types != init_types:
        # propagate upwards, if there is one
        if len(path) > 0:
            todo.add(path[:-1])  # type: ignore
        # and to references
        if path in references:
            todo.append(references[path])
        # and to dynamic references
        if "$dynamicAnchor" in schema:
            name = schema["$dynamicAnchor"]
            assert isinstance(name, str)
            todo.append(dynRefs[name])
        # where else?
        _types[path] = types

    return

def recomputeTypesOnPath(root: JsonSchema, path: SchemaPath) -> None:
    schema = root
    for segment in path:
        if isinstance(segment, str):
            schema = schema[segment]  # type: ignore
        else:
            assert isinstance(segment, tuple) and len(segment) == 2
            schema = schema[segment[0]][segment[1]]  # type: ignore
    updateTypes(schema, path)  # type: ignore

# TODO do not set "type" in some cases
def typeRwt(schema: JsonSchema, path: SchemaPath) -> JsonSchema:
    if isinstance(schema, dict):
        types: list[str] = types2list(_types[path])
        if len(types) == 0:
            # schema = False
            schema["type"] = []
        elif len(types) == 1:
            schema["type"] = types[0]
        else:
            schema["type"] = types  # type: ignore
    return schema

def computeTypes(schema: JsonSchema) -> JsonSchema:
    """Set possible types everywhere."""

    log.debug(f"types in: {json.dumps(schema, indent=2)}")

    if isinstance(schema, bool):
        return schema
    assert isinstance(schema, dict)

    global _types, _dynAnchors, _dynRefs, references, defs, todo
    _types, _dynAnchors, _dynRefs, references, defs = {}, {}, {}, {}, "$defs"

    if "definitions" in schema:
        defs = "definitions"

    todo = FILOSet()

    recurseSchema(schema, ".", typeFlt, noRwt)

    # iterate over names and root
    while len(todo) > 0:
        recomputeTypesOnPath(schema, todo.pop())

    # store types back in schema
    recurseSchema(schema, ".", goFlt, typeRwt)

    log.debug(f"types out: {json.dumps(schema, indent=2)}")

    return schema
