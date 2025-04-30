from typing import Callable
import os.path
from urllib.parse import urlsplit
import json
import requests
from .utils import JsonSchema, JSUError, log
from .recurse import recurseSchema

ProcessFun = Callable[[JsonSchema, str], JsonSchema]


def _full_url(url: str, ref: str) -> str:
    """Build full normalized URL from a reference.

    :param url: the url of the schema.
    :param ref: the reference (relative) url.
    """
    if "#" in ref:
        lurl, lpath = ref.split("#", 1)
    else:
        lurl, lpath = ref, ""
    # build the full url
    if lurl == "":
        return url + "#" + lpath
    elif lurl.startswith("/"):
        u = urlsplit(url)
        return u.scheme + "://" + u.netloc + lurl + "#" + lpath
    else:
        return lurl + "#" + lpath


def _fullURL(schema: JsonSchema, url: str) -> JsonSchema:
    """Replace relative references with absolute references.

    :param schema: schema to consider.
    :param url: the url of the schema.
    """

    # we need full references to avoid ambiguities on inline!
    def fullref(schema: JsonSchema, _path: list[str]) -> JsonSchema:
        if isinstance(schema, dict) and "$ref" in schema:
            ref = schema["$ref"]
            assert isinstance(ref, str)
            nref = _full_url(url, ref)
            log.debug(f"updating {ref} in {url}: {nref}")
            schema["$ref"] = nref
        return schema

    return recurseSchema(schema, url, rwt=fullref)


class Schemas:
    """Hold a set of identified schemas and sub-schemas."""

    def __init__(self):
        # url mapping for local storage: https://schema.psl.eu -> .
        self._urlmap: dict[str, str] = {}
        # cache of schema references
        self._schemas: dict[str, JsonSchema] = {}
        # additional processing on store
        self._process: list[ProcessFun] = [_fullURL]

    def addProcess(self, process: ProcessFun):
        self._process.append(process)

    def addMap(self, url: str, target: str):
        """Add local mapping for URLs."""
        self._urlmap[url] = target

    def store(self, url: str, schema: JsonSchema):
        """Store schema associated to URL."""
        log.info(f"adding schema {url}")

        if isinstance(schema, dict):
            for prop in ("$id", "id"):
                if prop in schema:
                    if url != schema[prop]:
                        log.warning(f"{prop}={schema[prop]} / {url}")
                    # del schema["$id"]  # FIXME?

        # NOTE intermediate to avoid an infinite recursion
        self._schemas[url] = schema

        # process schema through all filters
        for process in self._process:
            schema = process(schema, url)

        # store final processed version
        self._schemas[url] = schema

    def _load(self, url: str):
        """Load schema from URL if needed."""
        log.info(f"loading schema: {url}")

        assert "#" not in url

        # rewrite url for local search
        path = url
        for u, t in self._urlmap.items():
            if path.startswith(u):
                path = t + path[len(u):]
                break

        # FIXME what about actual http download?
        schema: JsonSchema|None
        if path.startswith("http://") or path.startswith("https://"):
            schema = requests.get(path).json  # type: ignore
        else:
            schema = None
            for suffix in ("", ".json", ".schema.json"):
                fn = f"{path}{suffix}"
                if os.path.isfile(fn):
                    log.debug(f"loading file: {fn}")
                    schema = json.load(open(fn))
                    break

        if schema is None:
            raise JSUError(f"schema {url} not found")

        self.store(url, schema)

    def _resolve(self, schema: JsonSchema, lpath: str) -> JsonSchema:
        """Extract sub-schema from schema following path.

        :param schema: schema to consider.
        :param path: path to consider.

        FIXME this does not handle URL escaping?
        """
        for p in lpath.split("/"):
            if p in (".", ""):
                pass
            else:
                assert isinstance(schema, dict) and p in schema
                schema = schema[p]  # type: ignore

        return schema

    def schema(self, url: str, ref: str) -> JsonSchema:
        """Resolve schema reference.

        :param url: url of schema.
        :param ref: reference to resolve in url.
        """
        assert isinstance(ref, str) and len(ref) > 0
        fref = _full_url(url, ref)
        assert "#" in fref
        curl, path = fref.split("#", 1)
        if curl not in self._schemas:
            self._load(curl)
        return self._resolve(self._schemas[curl], path)
