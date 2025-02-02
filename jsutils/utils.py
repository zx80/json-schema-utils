from typing import Any, Callable
import logging

log = logging.getLogger("JSU")

# simplistic typing
JsonSchema = dict[str, Any]|bool
FilterFun = Callable[[JsonSchema, list[str]], bool]
RewriteFun = Callable[[JsonSchema, list[str]], JsonSchema]


class JSUError(BaseException):
    pass
