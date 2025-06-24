from typing import Callable
import logging
import sys

log = logging.getLogger("JSU")

# simplistic typing
type Jsonable = None|bool|int|float|str|list[Jsonable]|dict[str, Jsonable]
JsonSchema = dict[str, Jsonable]|bool
FilterFun = Callable[[JsonSchema, list[str]], bool]
RewriteFun = Callable[[JsonSchema, list[str]], JsonSchema]


class JSUError(BaseException):
    pass


def only(schema, *props):
    """Tell whether schema only contains these props."""
    assert isinstance(schema, dict)
    ok = set(schema.keys()).issubset(set(props))
    if not ok:
        ttype = schema.get("type", "<>")
        log.debug(f"BAD SCHEMA {ttype}: {list(schema.keys())} {props}")
    return ok

def has(schema, *props):
    """Tell whether schema has any of these props."""
    assert isinstance(schema, dict)
    for p in schema.keys():
        if p not in props:
            return False
    return True


def openfiles(args: list[str] = []):
    if not args:  # empty list is same as stdin
        args = ["-"]
    for fn in args:
        if fn == "-":
            yield fn, sys.stdin
        else:
            with open(fn) as fh:
                yield fn, fh
