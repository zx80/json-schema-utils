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
                local_only: bool = False,
            ):
        self._cache = cache
        if cache is not None:
            Path(cache).mkdir(parents=True, exists_ok=True)
        self._mapping = {}
        for m in mapping:
            src, dst = m.split("=", 1)
            self._mapping[src] = dst

    def urlHash(self, url: str) -> str:
        return hashlib.sha3_256(url.encode()).hexdigest()[:16]

    def get(self, url: str) -> JsonSchema:

        js, loaded, filed, cached, cfn = None, False, False, False, None

        if self._cache is not None:  # we cache the **initial** url only
            uh = self.urlHash(url)
            cfn = f"{self._cache}/{uh}.json"
            try:
                with open(cfn) as f:
                    js = json.load(f)
                log.info(f"# loaded from cache: {url}")
                loaded, cached = True, True
            except Exception as e:
                log.debug(f"not found in cache: {url}")
        else:
            uh = None

        if not loaded and self._mapping:
            for src, dst in self._mapping.items():
                if url.startswith(src):
                    init_url = url
                    url = dst + url[len(src):]
                    log.info(f"remapping {init_url} to {url}")
                    break  # stop on first match

        if not loaded and (not url.startswith(HTTP_URL) and not url.startswith(HTTPS_URL)):
            fn = url[len(FILE_URL):] if url.startswith(FILE_URL) else url
            for suffix in ("", ".json", ".schema.json"):
                fns = fn + suffix
                if Path(fns).exists():
                    with open(fns) as f:
                        js = json.load(f)
                    log.info(f"# loaded from file: {url}")
                    loaded, filed = True, True
                    break

        if not loaded:
            res = requests.get(url)
            log.info(f"# loaded from net: {url!r}")
            js, loaded = res.json(), True

            # store in cache
            if self._cache is not None and not cached:
                assert isinstance(cfn, str)  # pyright
                with open(cfn, "w") as f:
                    f.write(res.text)

        assert isinstance(js, (bool, dict)), "JSON Schema is boolean or object"
        return js
