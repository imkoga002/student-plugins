"""Database searches that log themselves. Every run appends one record to research/search-log.jsonl
(db, query, date, hit count as reported, the student's sub-question id, purpose) - nobody has to remember to log.
The question id must exist in research/questions.md, which only the student writes (the hooks deny AI writes);
an unknown id stops the search before any request is sent. `--purpose counter` marks a search for
counter-evidence or rival explanations, counted by the bias check.

Endpoints (only those documented by the provider or seen working in a live response during development,
2026-11-04, marked "observed"; others are not implemented):
  crossref        https://api.crossref.org/works?query.bibliographic=...&rows=N   (list queries were limited to
                  ~1 rps, observed; pools: https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)
  datacite        https://api.datacite.org/dois?query=...&page[size]=N           (observed 200 JSON:API;
                  https://support.datacite.org/docs/api)
  cinii-books     https://ci.nii.ac.jp/books/opensearch/search?q=...&format=json  (observed 200 JSON-LD)
  cinii-research  https://cir.nii.ac.jp/opensearch/{all|articles|books|dissertations|data|projects}
                  ?q=...&format=json&count=N&appid=...  (appid REQUIRED: https://support.nii.ac.jp/ja/cir/r_opensearch ;
                  from userConfig cinii_appid)
  ndl             https://ndlsearch.ndl.go.jp/api/sru?operation=searchRetrieve&maximumRecords=N&query=CQL
                  (https://ndlsearch.ndl.go.jp/help/api/specifications ; sequential; title="..." by default, --cql
                  for a full CQL query)
  jstage          https://api.jstage.jst.go.jp/searchapi/do?service=3&keyword=...&count=N (observed 200 Atom;
                  other service values unverified). Show "Powered by J-STAGE" (J-STAGE WebAPI 利用規約 第9条,
                  https://www.jstage.jst.go.jp/static/pages/WebAPI/-char/ja).
Candidate lists go to .ryukoku/cache/search/ (git-ignored) and are deleted after 24 hours (J-STAGE terms
art. 3(5)). Nothing is selected automatically: the agent or student chooses and gives the reason with
`searchlog annotate`, then `ledger add-source` and `refcheck check` (never auto-select the top hit).
"""
import html
import json
import os
import re
import time

from . import searchlog
from .common import RkError
from .netutil import Net, q, redact

DBS = ("crossref", "datacite", "cinii-books", "cinii-research", "ndl", "jstage")
CINII_TYPES = ("all", "articles", "books", "dissertations", "data", "projects")


def purge_expired_cache(proj):
    """Delete search-API responses older than 24 hours (J-STAGE WebAPI terms art. 3(5) restrict keeping them).
    Run at every search, at SessionStart and by `rk check` (not only at the next search)."""
    d = os.path.join(proj, ".ryukoku", "cache", "search")
    if not os.path.isdir(d):
        return 0
    n = 0
    now = time.time()
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        try:
            if now - os.path.getmtime(p) > 24 * 3600:
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n


def _cache_dir(proj):
    d = os.path.join(proj, ".ryukoku", "cache", "search")
    os.makedirs(d, exist_ok=True)
    purge_expired_cache(proj)
    now = time.time()
    for fn in []:
        p = os.path.join(d, fn)
        try:
            if now - os.path.getmtime(p) > 24 * 3600:
                os.remove(p)
        except OSError:
            pass
    return d


def _first(v):
    if isinstance(v, list):
        return _first(v[0]) if v else ""
    if isinstance(v, dict):
        return v.get("@value") or v.get("title") or ""
    return v or ""


def parse_crossref(data):
    msg = data.get("message") or {}
    items = []
    for it in msg.get("items") or []:
        y = None
        dp = ((it.get("issued") or {}).get("date-parts") or [[None]])
        if dp and dp[0]:
            y = dp[0][0]
        au = "; ".join("%s, %s" % (a.get("family", ""), a.get("given", "")) for a in (it.get("author") or [])[:4])
        items.append({"id": "doi:" + str(it.get("DOI", "")), "title": _first(it.get("title")), "year": y, "authors": au})
    hits = msg.get("total-results")
    return (hits if isinstance(hits, int) else None), items


def parse_datacite(data):
    items = []
    for d in data.get("data") or []:
        a = d.get("attributes") or {}
        items.append({"id": "doi:" + str(a.get("doi", "")), "title": _first([t.get("title") for t in a.get("titles") or []]),
                      "year": a.get("publicationYear"),
                      "authors": "; ".join("%s, %s" % (c.get("familyName", ""), c.get("givenName", "")) for c in (a.get("creators") or [])[:4])})
    meta = data.get("meta") or {}
    hits = meta.get("total") if isinstance(meta.get("total"), int) else None  # key UNVERIFIED -> null if absent
    return hits, items


def parse_cinii(data):
    items, hits = [], None
    for node in _walk(data):
        if not isinstance(node, dict):
            continue
        if hits is None and isinstance(node.get("opensearch:totalResults"), (int, str)):
            try:
                hits = int(node["opensearch:totalResults"])
            except ValueError:
                pass
        i = str(node.get("@id", ""))
        if ("/ncid/" in i or "/crid/" in i) and not i.endswith(".json") and "title" in node:
            items.append({"id": i, "title": _first(node.get("title") or node.get("dc:title")), "year": _first(node.get("dc:date") or node.get("prism:publicationDate")), "authors": ""})
    return hits, items


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def parse_ndl(xml_text):
    t = html.unescape(html.unescape(xml_text))
    m = re.search(r"<numberOfRecords>(\d+)</numberOfRecords>", t)
    hits = int(m.group(1)) if m else None
    items = []
    for rec in re.findall(r"<record>(.*?)</record>", t, re.S) or re.findall(r"<recordData>(.*?)</recordData>", t, re.S):
        ti = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", rec, re.S)
        if ti:
            v = re.search(r"<rdf:value>(.*?)</rdf:value>", ti.group(1), re.S)
            ti_text = re.sub(r"<[^>]+>", "", v.group(1) if v else ti.group(1)).strip()
        else:
            ti_text = ""
        about = re.search(r'rdf:about="([^"#]+)"', rec)
        yr = re.search(r"<dcterms:issued[^>]*>([^<]+)<", rec)
        items.append({"id": about.group(1) if about else "", "title": ti_text, "year": yr.group(1) if yr else "",
                      "authors": ""})
    return hits, items


def parse_jstage(xml_text):
    """Atom feed (observed in a live response during development, 2026-11-04). The element names used for display
    (article_title/ja, pubyear, prism:doi) were also observed then; they only affect the candidate list."""
    m = re.search(r"<opensearch:totalResults>(\d+)</opensearch:totalResults>", xml_text)
    hits = int(m.group(1)) if m else None
    unc = lambda x: html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", x, flags=re.S))).strip()
    items = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml_text, re.S):
        ti = re.search(r"<article_title>.*?<ja>(.*?)</ja>", e, re.S) or re.search(r"<title[^>]*>(.*?)</title>", e, re.S)
        doi = re.search(r"<prism:doi>(.*?)</prism:doi>", e)
        link = re.search(r'<link[^>]*href="([^"]+)"', e)
        yr = re.search(r"<pubyear>(\d{4})</pubyear>", e)
        items.append({"id": ("doi:" + doi.group(1)) if doi else (link.group(1) if link else ""),
                      "title": unc(ti.group(1)) if ti else "", "year": yr.group(1) if yr else "", "authors": ""})
    return hits, items


PURPOSES = ("main", "counter")


def question_ids(proj):
    """Ids of the questions the student wrote in research/questions.md ("Q1: ..." lines or "| Q1 | ... |" rows).
    Placeholder rows (empty, only a parenthesised hint, dashes) do not count."""
    try:
        with open(os.path.join(proj, "research", "questions.md"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return set()
    out = set()
    for line in text.splitlines():
        st = line.strip()
        if st.startswith("|"):
            cells = [c.strip() for c in st.strip("|").split("|")]
            qid, body = (cells[0], cells[1]) if len(cells) >= 2 else ("", "")
        else:
            m = re.match(r"^[-*]?\s*\**(Q\d+)\**\s*[:：]\s*(.*)$", st)
            qid, body = (m.group(1), m.group(2).strip()) if m else ("", "")
        qid = qid.strip("*")
        if re.fullmatch(r"Q\d+", qid) and body and not re.fullmatch(r"[（(].*[)）]|[-–—]+|…+|\.\.\.", body):
            out.add(qid)
    return out


class UnknownQuestion(RkError):
    pass


def run(proj, db, query, question_ref, rows=10, ctype="all", cql=None, mailto=None, appid=None, by="agent", purpose="main"):
    if db not in DBS:
        raise RkError("db は %s のどれか" % ", ".join(DBS))
    if purpose not in PURPOSES:
        raise RkError("--purpose は main か counter")
    qs = question_ids(proj)
    if (question_ref or "").strip() not in qs:
        raise UnknownQuestion("問い %s が research/questions.md にない(学生が書いた問い: %s)。調査の問いは学生の問いから導くので、"
                              "学生が問いを書くまで検索しない。通信はしていない / question id not found in research/questions.md; nothing was sent"
                              % (question_ref or "(空)", ", ".join(sorted(qs)) or "なし"))
    net = Net(mailto=mailto, cache_dir=os.path.join(proj, ".ryukoku", "cache"))
    rows = max(1, min(int(rows), 50))
    try:
        code, body, parse, url, filters = _request(net, db, query, rows, ctype, cql, mailto, appid)
    except RkError:
        raise
    except Exception as e:  # network failure: the search is still logged, with hits unknown
        rec = searchlog.add(proj, db, query, question_ref, hits=None, filters="",
                            reason="", by=by, purpose=purpose, note="ネットワークの失敗(%s)。件数は不明" % type(e).__name__)
        return rec, [], "network error: %s" % type(e).__name__
    return _finish(proj, db, query, question_ref, by, code, body, parse, url, filters, purpose)


def _request(net, db, query, rows, ctype, cql, mailto, appid):
    filters = ""
    if db == "crossref":
        url = "https://api.crossref.org/works?query.bibliographic=%s&rows=%d" % (q(query), rows)
        if mailto:
            url += "&mailto=" + q(mailto)
        code, body = net.get(url)
        parse = lambda b: parse_crossref(json.loads(b))
    elif db == "datacite":
        url = "https://api.datacite.org/dois?query=%s&page[size]=%d" % (q(query), rows)
        code, body = net.get(url)
        parse = lambda b: parse_datacite(json.loads(b))
    elif db == "cinii-books":
        url = "https://ci.nii.ac.jp/books/opensearch/search?q=%s&format=json&count=%d" % (q(query), rows)
        if appid:
            url += "&appid=" + q(appid)
        code, body = net.get(url)
        parse = lambda b: parse_cinii(json.loads(b))
    elif db == "cinii-research":
        if not appid:
            raise RkError("CiNii Research には appid が要る(NII の CiNii API デベロッパー登録。Plugin の設定 cinii_appid に入れる)")
        if ctype not in CINII_TYPES:
            raise RkError("--type は %s" % ", ".join(CINII_TYPES))
        filters = "type=" + ctype
        url = "https://cir.nii.ac.jp/opensearch/%s?q=%s&format=json&count=%d&appid=%s" % (ctype, q(query), rows, q(appid))
        code, body = net.get(url)
        parse = lambda b: parse_cinii(json.loads(b))
    elif db == "ndl":
        c = cql or 'title="%s"' % query.replace('"', " ")
        filters = "cql=" + c
        url = "https://ndlsearch.ndl.go.jp/api/sru?operation=searchRetrieve&maximumRecords=%d&recordSchema=dcndl&query=%s" % (rows, q(c))
        code, body = net.get_ndl(url)
        parse = lambda b: parse_ndl(b.decode("utf-8", "replace"))
    else:
        url = "https://api.jstage.jst.go.jp/searchapi/do?service=3&keyword=%s&count=%d" % (q(query), rows)
        filters = "service=3"
        code, body = net.get(url, accept="application/xml")
        parse = lambda b: parse_jstage(b.decode("utf-8", "replace"))
    return code, body, parse, url, filters


def _finish(proj, db, query, question_ref, by, code, body, parse, url, filters, purpose="main"):
    if code != 200:
        rec = searchlog.add(proj, db, query, question_ref, hits=None, filters=filters, by=by, endpoint=redact(url),
                            purpose=purpose, note="HTTP %s(検索は失敗。件数は不明)" % code)
        return rec, [], "HTTP %s" % code
    try:
        hits, items = parse(body)
    except (ValueError, KeyError) as e:
        hits, items = None, []
    rec = searchlog.add(proj, db, query, question_ref, hits=hits, filters=filters, by=by, endpoint=redact(url), purpose=purpose)
    cache = os.path.join(_cache_dir(proj), rec["id"] + ".jsonl")
    with open(cache, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    credit = "Powered by J-STAGE (https://www.jstage.jst.go.jp/)" if db == "jstage" else ""
    return rec, items, credit
