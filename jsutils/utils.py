from typing import Callable
import logging

log = logging.getLogger("JSU")

# simplistic typing
type Jsonable = None|bool|int|float|str|list[Jsonable]|dict[str, Jsonable]
JsonSchema = dict[str, Jsonable]|bool
FilterFun = Callable[[JsonSchema, list[str]], bool]
RewriteFun = Callable[[JsonSchema, list[str]], JsonSchema]


class JSUError(BaseException):
    pass


def openfiles(args: list[str] = []):
    if not args:  # empty list is same as stdin
        args = ["-"]
    for fn in args:
        if fn == "-":
            yield fn, sys.stdin
        else:
            with open(fn) as fh:
                yield fn, fh
