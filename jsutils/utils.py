from typing import Any
import logging

log = logging.getLogger("JSU")

# simplistic typing
JsonSchema = dict[str, Any]|None

class JSUError(BaseException):
    pass
