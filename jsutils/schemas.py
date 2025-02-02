import os.path
from urllib.parse import urlsplit
import json
from .utils import JsonSchema, JSUError, log
from .recurse import recurseSchema


class Schemas:
    """Hold a set of identified schemas and sub-schemas."""

    def __init__(self):
        # url mapping for local storage: https://schema.psl.eu -> .
        self._urlmap: dict[str, str] = {}
        # cache of schema references
        self._schemas: dict[str, JsonSchema] = {}

    def addMap(self, url: str, target: str):
        """Add local mapping for URLs."""
        self._urlmap[url] = target

    def store(self, url: str, schema: JsonSchema):
        """Store schema associated to URL."""
        log.info(f"adding schema {url}")

        assert isinstance(schema, dict)
        if "$id" in schema:
            assert url == schema["$id"]
            # del schema["$id"]  # FIXME?
        elif "id" in schema:
            assert url == schema["id"]
            # del schema["id"]  # FIXME?

        # we need full references to avoid ambiguities!
        def fullref(s):
            if isinstance(s, dict) and "$ref" in s:
                ref = s["$ref"]
                nref = self._full_url(url, ref)
                log.debug(f"updating {ref} in {url}: {nref}")
                s["$ref"] = nref
            return s

        schema = recurseSchema(schema, url, fullref)

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

        FIXME this does not handle URL escaping.
        """
        for p in lpath.split("/"):
            if p in (".", ""):
                pass
            else:
                assert isinstance(schema, dict) and p in schema
                schema = schema[p]
        return schema

    def _full_url(self, url: str, ref: str) -> str:
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

    def schema(self, url: str, ref: str) -> JsonSchema:
        """Resolve schema reference."""
        assert isinstance(ref, str) and len(ref) > 0
        fref = self._full_url(url, ref)
        assert "#" in fref
        curl, path = fref.split("#", 1)
        if curl not in self._schemas:
            self._load(curl)
        ref_schema = self._resolve(self._schemas[curl], path)
        return ref_schema
