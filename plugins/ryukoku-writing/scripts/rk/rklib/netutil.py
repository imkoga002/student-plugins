"""HTTP helper for verification and search (standard library only). Used only when the user runs a
verification or search command; hooks never call the network.

* User-Agent carries a mailto only when the student configured one - never a hard-coded address. (Crossref's
  polite pool: https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/ ;
  DataCite's "identified" limits: https://support.datacite.org/docs/rate-limit)
* Secrets (CiNii appid) are added to the request URL but never printed or logged: redact() replaces them.
* NDL Search: strictly sequential across processes (a lock file in .ryukoku/cache/), at least 1.5 s between
  requests, back off on HTTP 429 (concurrent requests are limited, no number published: NDLサーチ「API利用について」,
  https://ndlsearch.ndl.go.jp/help/api ; a 429 was observed during development, 2026-11-04).
* Raw responses are not stored. J-STAGE WebAPI terms art. 3(5) forbid machine-readable caching for 24h+.
"""
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "ryukoku-writing/1.0 (student research verification)"
SECRET_PARAMS = ("appid", "appId", "api_key", "key")


def redact(url):
    for p in SECRET_PARAMS:
        url = re.sub(r"([?&]%s=)[^&]*" % p, r"\1***", url)
    return url


class Lock:
    def __init__(self, path, wait=90, stale=180):
        self.path, self.wait, self.stale = path, wait, stale

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        t0 = time.time()
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > self.stale:
                        os.remove(self.path)
                        continue
                except OSError:
                    continue
                if time.time() - t0 > self.wait:
                    raise RuntimeError("NDL lock busy: another search is running (sequential access only)")
                time.sleep(0.5)

    def __exit__(self, *a):
        try:
            os.remove(self.path)
        except OSError:
            pass


class Net:
    def __init__(self, mailto=None, timeout=25, delay=0.25, cache_dir=None):
        self.mailto, self.timeout, self.delay = mailto, timeout, delay
        self.cache_dir = cache_dir or os.path.join(os.getcwd(), ".ryukoku", "cache")
        self._last_ndl = 0.0

    def ua(self):
        return UA + (" (mailto:%s)" % self.mailto if self.mailto else "")

    def get(self, url, accept="application/json"):
        req = urllib.request.Request(url, headers={"User-Agent": self.ua(), "Accept": accept})
        time.sleep(self.delay)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b""
            return e.code, body

    def get_ndl(self, url):
        with Lock(os.path.join(self.cache_dir, "ndl.lock")):
            for attempt in range(3):
                gap = time.time() - self._last_ndl
                if gap < 1.5:
                    time.sleep(1.5 - gap)
                code, body = self.get(url, accept="application/xml")
                self._last_ndl = time.time()
                if code != 429:
                    return code, body
                time.sleep(5 * (attempt + 1))
            return code, body


def q(s):
    return urllib.parse.quote(s, safe="")
