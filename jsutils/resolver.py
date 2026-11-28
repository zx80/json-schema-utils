from pathlib import Path
import hashlib
import copy
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
        self._cache_mem: dict[str, JsonSchema] = {}
        self._cache_dir = cache
        if cache is not None:
            Path(cache).mkdir(parents=True, exist_ok=True)
        # url to local file mapping
        self._mapping = {}
        for m in mapping:
            src, dst = m.split("=", 1)
            self._mapping[src] = dst

    def _urlHash(self, url: str) -> str:
        return hashlib.sha3_256(url.encode()).hexdigest()[:16]

    def put(self, url: str, schema: JsonSchema, *, in_file: bool = True):
        """Store url resolution in cache."""
        if url in self._cache_mem:
            log.warning(f"overriding cached {url}")
        self._cache_mem[url] = copy.deepcopy(schema)
        if in_file and self._cache_dir:
            uh = self._urlHash(url)
            cfn = f"{self._cache_dir}/{uh}.json"
            with open(cfn, "w") as f:
                f.write(json.dumps(schema))

    def delete(self, url: str):
        """Delete from cache."""
        if url in self._cache_mem:
            del self._cache_mem[url]
        if self._cache_dir:
            uh = self._urlHash(url)
            Path(f"{self._cache_dir}/{uh}.json").unlink(missing_ok=True)

    def get(self, url: str) -> JsonSchema:
        """Download JSON from URL."""

        init_url = url
        js, loaded, cfn = None, False, None

        # try loading from caches
        if url in self._cache_mem:
            log.info(f"# loaded from cache mem: {url}")
            return self._cache_mem[url]
        else:
            log.debug(f"not found in cache mem: {url}")

        if self._cache_dir is not None:  # we cache the **initial** url only
            uh = self._urlHash(url)
            cfn = f"{self._cache_dir}/{uh}.json"
            try:
                with open(cfn) as f:
                    js = json.load(f)
                log.info(f"# loaded from cache dir: {url}")
                # update memory cache
                if url not in self._cache_mem:
                    self._cache_mem[url] = copy.deepcopy(js)
                loaded = True
            except FileNotFoundError:
                log.debug(f"not found in cache dir: {url}")
            except Exception as e:
                log.error(f"ignoring invalid cached file dir: {url} ({e})")

        # handle mapping
        if not loaded and self._mapping:
            for src, dst in self._mapping.items():
                if url.startswith(src):
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
            self.put(init_url, js)

        # sanity check
        assert isinstance(js, (bool, dict)), "JSON Schema is boolean or object"
        return js
