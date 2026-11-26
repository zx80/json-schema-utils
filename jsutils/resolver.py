from pathlib import Path
import hashlib
import json
import requests

from .utils import JsonSchema, log

FILE_URL = "file://"
HTTP_URL = "http://"
HTTPS_URL = "https://"

class Resolver:

    def __init__(
            self,
            cache: str|None = None,
            mapping: list[str] = [],
            local_only: bool = False):
        # dir/file cache
        self._cache = cache
        if cache is not None:
            Path(cache).mkdir(parents=True, exist_ok=True)
        # url to local file mapping
        self._mapping = {}
        for m in mapping:
            src, dst = m.split("=", 1)
            self._mapping[src] = dst

    def _urlHash(self, url: str) -> str:
        return hashlib.sha3_256(url.encode()).hexdigest()[:16]

    def put(self, url: str, schema: JsonSchema):
        assert self._cache, "put requires a cache!"
        uh = self._urlHash(url)
        cfn = f"{self._cache}/{uh}.json"
        with open(cfn, "w") as f:
            f.write(json.dumps(schema))

    def delete(self, url: str):
        assert self._cache, "delete requires a cache!"
        uh = self._urlHash(url)
        cpath = Path(f"{self._cache}/{uh}.json")
        cpath.unlink(missing_ok=True)

    def get(self, url: str) -> JsonSchema:
        """Download JSON from URL."""

        js, loaded, cached, cfn = None, False, False, None

        # try loading from cache
        if self._cache is not None:  # we cache the **initial** url only
            uh = self._urlHash(url)
            cfn = f"{self._cache}/{uh}.json"
            try:
                with open(cfn) as f:
                    js = json.load(f)
                log.info(f"# loaded from cache: {url}")
                loaded, cached = True, True
            except FileNotFoundError:
                log.debug(f"not found in cache: {url}")
            except Exception as e:
                log.error(f"ignoring invalid cache file: {url} ({e})")
        else:
            uh = None

        # handle mapping
        if not loaded and self._mapping:
            for src, dst in self._mapping.items():
                if url.startswith(src):
                    init_url = url
                    url = dst + url[len(src):]
                    log.info(f"remapping {init_url} to {url}")
                    break  # stop on first match

        # load file
        if not loaded and not url.startswith((HTTP_URL, HTTPS_URL)):
            fn = url.removeprefix(FILE_URL)
            for suffix in ("", ".json", ".schema.json"):
                fns = fn + suffix
                if Path(fns).exists():
                    with open(fns) as f:
                        js = json.load(f)
                    log.info(f"# loaded from file: {url}")
                    loaded = True
                    break

        # actual url resolution
        if not loaded:
            res = requests.get(url)
            log.info(f"# loaded from net: {url!r}")
            js, loaded = res.json(), True

            # store in cache
            if self._cache is not None and not cached:
                assert isinstance(cfn, str)  # pyright
                with open(cfn, "w") as f:
                    f.write(res.text)

        # sanity check
        assert isinstance(js, (bool, dict)), "JSON Schema is boolean or object"
        return js
