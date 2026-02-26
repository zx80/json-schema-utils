import json
import logging

from .utils import ALL_TYPES, IGNORE
from .utils import JsonSchema, SchemaPath
from .utils import log, only
from .recurse import recurseSchema, noRwt

cur_version: int = 0

def oldDraftFlt(schema: JsonSchema, path: SchemaPath) -> bool:

    if isinstance(schema, bool):
        return False
    assert isinstance(schema, dict)

    # obviously there are examples with both $id and id… see ui5-manifest
    if "$id" in schema and "id" in schema:
        log.error(f"removing `id` next to `$id` at {path}")
        del schema["id"]

    if cur_version <= 5 and "id" in schema and "$id" not in schema:
        schema["$id"] = schema.pop("id")

    if "divisibleBy" in schema:
        assert "multipleOf" not in schema, "should not have both multipleOf and divisibleBy"
        schema["multipleOf"] = schema.pop("divisibleBy")

    if "extends" in schema:
        if "allOf" not in schema:
            schema["allOf"] = []
        extends = schema.pop("extends")
        if isinstance(extends, list):
            schema["allOf"] += extends
        else:
            schema["allOf"].append(extends)

    if "type" in schema:
        ts = schema["type"]
        if (isinstance(ts, list) and "any" in ts or
            isinstance(ts, str) and ts == "any"):
            schema["type"] = sorted(ALL_TYPES)
        elif isinstance(ts, list) and any(map(lambda t: isinstance(t, dict), ts)):
            # full type in type list is translated as anyOf
            del schema["type"]
            tl = [ {"type": t} if isinstance(t, str) else t for t in ts ]
            if "anyOf" not in schema:
                schema["anyOf"] = tl
            elif "allOf" in schema:
                schema["allOf"].append({"anyOf": tl})
            else:
                schema["allOf"] = [{"anyOf": tl}]

    if "disallow" in schema:  # not this type
        dis = schema["disallow"]
        if not isinstance(dis, list):
            dis = [dis]
        ts = schema["type"] if "type" in schema else sorted(ALL_TYPES)
        for t in dis:
            if t == "any":
                ts.clear()
            elif t == "integer" and ("number" in ts or "number" not in dis):  # integer/number issue
                if "allOf" not in schema:
                    schema["allOf"] = []
                schema["allOf"].append({"not": {"type": t}})
            elif isinstance(t, str) and t in ts:
                ts.remove(t)
            elif t == only(schema, "type", *IGNORE):
                ts.clear()
            else:
                if "allOf" not in schema:
                    schema["allOf"] = []
                schema["allOf"].append({"not": t})
        del schema["disallow"]
        schema["type"] = ts[0] if len(ts) == 1 else ts

    if "exclusiveMinimum" in schema and isinstance(schema["exclusiveMinimum"], bool):
        # NOTE minimum is really mandatory
        if schema["exclusiveMinimum"] and "minimum" in schema:
            schema["exclusiveMinimum"] = schema["minimum"]
            del schema["minimum"]
        else:
            del schema["exclusiveMinimum"]

    if "exclusiveMaximum" in schema and isinstance(schema["exclusiveMaximum"], bool):
        # NOTE maximum is really mandatory
        if schema["exclusiveMaximum"] and "maximum" in schema:
            schema["exclusiveMaximum"] = schema["maximum"]
            del schema["maximum"]
        else:
            del schema["exclusiveMaximum"]

    # boolean required
    if "properties" in schema:
        reqs = []
        for p, s in schema["properties"].items():
            if isinstance(s, dict) and "required" in s and isinstance(s["required"], bool):
                if s["required"]:
                    reqs.append(p)
                del s["required"]
        if reqs:
            assert "required" not in schema
            schema["required"] = reqs

    # scalar dependencies
    if "dependencies" in schema:
        deps = schema["dependencies"]
        for p in list(deps):
            s = deps[p]
            if isinstance(s, str):
                deps[p] = [ s ]

    # recursiveAnchor/Ref to dynamicAnchor/Ref
    if "recursiveAnchor" in schema:
        assert "dynamicAnchor" not in schema
        schema["dynamicAnchor"] = schema["recursiveAnchor"]
        del schema["recursiveAnchor"]
    if "recursiveRef" in schema:
        assert "dynamicRef" not in schema
        schema["dynamicRef"] = schema["recursiveRef"]
        del schema["recursiveRef"]

    return True

def modernizeOldDraft(schema: JsonSchema, version: int, level: int = logging.INFO):
    """More or less convert old stuff to draft7/better."""
    log.setLevel(level)
    if level == logging.DEBUG:
        log.debug(f"modernize in: {json.dumps(schema, indent=2)}")

    global cur_version
    cur_version = version
    # TODO add a context
    recurseSchema(schema, (), oldDraftFlt, noRwt)

    if level == logging.DEBUG:
        log.debug(f"modernize out: {json.dumps(schema, indent=2)}")
