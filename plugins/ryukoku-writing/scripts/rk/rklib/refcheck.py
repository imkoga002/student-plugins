"""refcheck - machine stage of source verification.

Writes machine columns only: IDENTITY_CONFIRMED / NOT_FOUND / METADATA_MISMATCH / RETRACTED / CANDIDATE.
Never VERIFIED (human only, via ./rk verify). Network only when the user runs `rk.py refcheck check`.

Order:
  DOI   syntax -> doi.org handle API (responseCode 1 = exists, 100 = not found; DOI resolution documentation,
        https://www.doi.org/the-identifier/resources/factsheets/doi-resolution-documentation)
        -> Crossref /works/{doi}; if Crossref has no record -> DataCite /dois/{doi} (https://support.datacite.org/docs/api)
        -> field comparison (title normalised; authors not by family name alone; year +-1 noted)
        -> retraction: Crossref updated-by[].type == retraction
                       Crossref update-to[] on the cited DOI: the DOI is itself a retraction notice
                       (Crossref, Retraction Watch: https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/)
                       DataCite / CiNii / NDL: no retraction coverage -> "not covered", never "not retracted"
  ISBN  ISBN-13 check digit only (ISBN Users' Manual, 6th International Edition, 2012, Appendix 1 A1.1,
        https://www.isbn-international.org/sites/default/files/ISBN%20Manual%202012%20-corr.pdf). ISBN-10: its
        algorithm was not found in that manual (unverified) -> not implemented. A valid checksum alone never gives
        IDENTITY_CONFIRMED.
  NCID  CiNii Books OpenSearch (search by the claimed title; the NCID must appear among result @id values). The
        JSON-LD layout (@graph/items) and items[].title were observed in live responses during development
        (2026-11-04), not taken from documentation. When no title matches, the result stays CANDIDATE (fails safe).
  CRID  CiNii Research OpenSearch v1 /opensearch/all (appid REQUIRED: CiNii Research OpenSearch,
        https://support.nii.ac.jp/ja/cir/r_opensearch ; the appid comes from userConfig cinii_appid and is never
        printed). The CRID must appear among result ids; field names unverified -> same fail-safe.
  NDL   NDL Search SRU searchRetrieve by title (+ creator when authors are given), recordSchema=dcndl
        (sequential, 429 back-off). The given NDL ID must appear in the response (rdf:about) and a dc:title
        (rdf:value) must match. Documented: SRU, CQL title= and DC-NDL as the base format (NDLサーチ「API仕様の概要」,
        https://ndlsearch.ndl.go.jp/help/api/specifications). recordSchema=dcndl, the creator= index and the
        rdf:about/rdf:value layout were observed during development (2026-11-04), not documented there. The SRU
        isbn= index was not tested -> not implemented.
Metadata missing (no title/authors/year to compare) -> CANDIDATE, never IDENTITY_CONFIRMED.
"""
import datetime
import difflib
import html
import json
import os
import re
import unicodedata

from .netutil import Net, q, redact

MACHINE_STATUSES = ("IDENTITY_CONFIRMED", "NOT_FOUND", "METADATA_MISMATCH", "RETRACTED", "CANDIDATE")
FORBIDDEN_WRITE = "VERIFIED"
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
NCID_RE = re.compile(r"^[A-Z]{2}\d{7}[0-9X]$")


# ---------------------------------------------------------------- normalisation
def normalize_doi(s):
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).strip()
    s = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", s, flags=re.I)
    return s.strip().rstrip(".,;").lower()


def valid_doi_syntax(doi):
    return bool(DOI_RE.match(doi))


def normalize_text(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.lower()
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        out.append(ch if (cat[0] in ("L", "N") or cat == "Mn") else " ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def titles_match(claimed, found, threshold=0.9):
    a, b = normalize_text(claimed), normalize_text(found)
    if not a or not b:
        return False
    if a == b:
        return True
    if difflib.SequenceMatcher(None, a, b).ratio() >= threshold:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 20 and long_.startswith(short)


def split_authors(s):
    if not s:
        return []
    return [x.strip() for x in re.split(r"[;；\n]|\s+and\s+|\s*&\s*", s) if x.strip()]


def author_key(name):
    n = unicodedata.normalize("NFKC", name).strip()
    if "," in n:
        fam, giv = [p.strip() for p in n.split(",", 1)]
    elif re.search(r"[぀-ヿ㐀-鿿]", n):
        fam, giv = re.sub(r"\s+", "", n), ""
    else:
        parts = n.split()
        fam, giv = (parts[-1], " ".join(parts[:-1])) if parts else ("", "")
    return normalize_text(fam).replace(" ", ""), normalize_text(giv)[:1]


def authors_match(claimed_list, found_list):
    found = []
    for a in found_list:
        fam = normalize_text(a.get("family", "")).replace(" ", "")
        giv = normalize_text(a.get("given", ""))
        found.append((fam, giv[:1], fam + giv.replace(" ", "")))
    missing = []
    for c in claimed_list:
        fam, gi = author_key(c)
        ok = False
        for f_fam, f_gi, f_full in found:
            if fam == f_fam and (not gi or not f_gi or gi == f_gi):
                ok = True
            elif fam and fam == f_full:
                ok = True
        if not ok:
            missing.append(c)
    return (not missing), missing


def first_year(item):
    for k in ("issued", "published", "published-print", "published-online"):
        dp = (item.get(k) or {}).get("date-parts") or []
        if dp and dp[0] and dp[0][0]:
            return int(dp[0][0])
    return None


def clean_isbn(s):
    return re.sub(r"[\s\-]", "", unicodedata.normalize("NFKC", str(s or ""))).upper()


def isbn13_valid(s):
    s = clean_isbn(s)
    if not re.fullmatch(r"97[89]\d{10}", s):
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(s[:12]))
    return (10 - total % 10) % 10 == int(s[12])


# ---------------------------------------------------------------- retraction signals
RETRACTION_TYPES = {"retraction"}
KNOWN_NONRETRACTION = {"addendum", "new_version", "correction", "erratum"}


def retraction_signals(item):
    """updated-by[] on the cited record. Unknown types go to notes for human review."""
    retracted, notes = [], []
    for u in item.get("updated-by") or []:
        t = str(u.get("type", "")).lower()
        entry = {"type": t, "source": u.get("source"), "doi": u.get("DOI")}
        if t in RETRACTION_TYPES:
            retracted.append(entry)
        elif t not in KNOWN_NONRETRACTION:
            notes.append("updated-by の型 '%s' は調査で未確認の種類。人間が確認すること" % t)
        else:
            notes.append("updated-by: %s(%s)。人間が内容を確認すること" % (t, u.get("DOI")))
    return retracted, notes


def notice_signals(item):
    """update-to[] on the cited record: the cited DOI is itself a notice that updates another work
    (a notice's update-to points at the retracted DOI: Crossref, Retraction Watch,
    https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/)."""
    out = []
    for u in item.get("update-to") or []:
        t = str(u.get("type", "")).lower()
        out.append({"type": t, "target": u.get("DOI"), "source": u.get("source")})
    return out


# ---------------------------------------------------------------- judgement (offline)
def judge(ref, item, registry="crossref"):
    details, notes, mism = {}, [], []
    title_found = (item.get("title") or [""])[0] if isinstance(item.get("title"), list) else (item.get("title") or "")
    if ref.get("title") and not titles_match(ref["title"], title_found):
        mism.append("title")
    claimed = split_authors(ref.get("authors", ""))
    if claimed:
        ok, missing = authors_match(claimed, item.get("author") or [])
        if not ok:
            mism.append("authors")
            details["authors_missing"] = missing
    fy, cy = first_year(item), ref.get("year")
    if cy and fy:
        diff = abs(int(cy) - fy)
        if diff > 1:
            mism.append("year")
        elif diff == 1:
            notes.append("年が1年ずれている(オンライン先行公開と掲載号の差の可能性)。人間が確認すること")
    empty = not (ref.get("title") or claimed or cy)
    if empty:
        notes.append("照合項目(題名・著者・年)が空。実在の確認のみで、同一性は確認していない")
    retracted, rn = retraction_signals(item) if registry == "crossref" else ([], [])
    notes += rn
    notices = [n for n in notice_signals(item) if n["type"] in RETRACTION_TYPES] if registry == "crossref" else []
    if registry != "crossref":
        notes.append("撤回の状況: 未確認(%s は Crossref の撤回データの対象外)。『撤回されていない』ではない" % registry)
    details.update({"registry": registry, "found_title": title_found, "found_year": fy,
                    "mismatch_fields": mism, "retraction": retracted, "retraction_notice_for": notices})
    if retracted:
        status = "RETRACTED"
    elif notices:
        status = "CANDIDATE"
        notes.append("この DOI は撤回通知(retraction notice)で、撤回された論文は %s。論文本体を引くなら、その DOI で確認し撤回済みとして扱う"
                     % ", ".join(str(n["target"]) for n in notices))
    elif mism:
        status = "METADATA_MISMATCH"
    elif empty:
        status = "CANDIDATE"
    else:
        status = "IDENTITY_CONFIRMED"
    out = {"status": status, "details": details, "notes": notes}
    if status == "IDENTITY_CONFIRMED":
        out["meta"] = registry_meta(item)
    return out


def _names(lst):
    out = []
    for a in lst or []:
        if not isinstance(a, dict):
            continue
        d = {k: str(a[k]) for k in ("family", "given", "literal") if a.get(k)}
        if d:
            out.append(d)
    return out


def registry_meta(item):
    """The bibliographic fields of a registry record (Crossref / DataCite as read above), as recorded at the identity
    check. The export renders the bibliography from these (citations.csl_items), never from a file the AI can edit."""
    def one(v):
        if isinstance(v, list):
            return str(v[0]) if v else ""
        return str(v or "")
    meta = {"title": one(item.get("title")), "author": _names(item.get("author")), "editor": _names(item.get("editor"))}
    fy = first_year(item)
    if fy:
        meta["year"] = fy
    for k in ("container-title", "publisher", "volume", "issue", "page", "type", "DOI"):
        v = one(item.get(k))
        if v:
            meta[k] = v
    return {k: v for k, v in meta.items() if v}


def datacite_item(attrs):
    """Map DataCite JSON:API attributes (OBSERVED shape: titles[{title}], creators[{givenName,familyName}],
    publicationYear) to the Crossref-like dict judge() reads."""
    titles = [t.get("title", "") for t in attrs.get("titles") or [] if isinstance(t, dict)]
    authors = []
    for c in attrs.get("creators") or []:
        if isinstance(c, dict):
            fam = c.get("familyName") or ""
            giv = c.get("givenName") or ""
            if not fam and c.get("name") and "," in c["name"]:
                fam, giv = [x.strip() for x in c["name"].split(",", 1)]
            authors.append({"family": fam, "given": giv})
    y = attrs.get("publicationYear")
    item = {"title": titles[:1] or [""], "author": authors}
    if y:
        try:
            item["issued"] = {"date-parts": [[int(y)]]}
        except (TypeError, ValueError):
            pass
    return item


def _titles_of(node):
    out = []
    for k in ("title", "dc:title"):
        v = node.get(k)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out += [x if isinstance(x, str) else (x.get("@value", "") if isinstance(x, dict) else "") for x in v]
        elif isinstance(v, dict):
            out.append(v.get("@value", ""))
    return [x for x in out if x]


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def judge_cinii(data, ident, kind, claimed_title):
    """data: parsed JSON-LD. ident: NCID or CRID. Fails safe to CANDIDATE."""
    hit = None
    for node in _walk(data):
        i = str(node.get("@id", "")) if isinstance(node, dict) else ""
        if i.rstrip("/").endswith("/%s/%s" % (kind, ident)) or i.rstrip("/").endswith("/" + ident):
            hit = node
            break
    if hit is None:
        return {"status": "CANDIDATE", "reason": "%s_not_in_results" % kind,
                "notes": ["題名で検索した結果に %s %s が見つからない。題名の表記や識別子を確かめ、OPAC・CiNii の画面でも確認する" % (kind.upper(), ident)]}
    titles = _titles_of(hit)
    if claimed_title and any(titles_match(claimed_title, t) for t in titles):
        return {"status": "IDENTITY_CONFIRMED", "reason": "%s_found_title_matched" % kind,
                "meta": {"title": next(t for t in titles if titles_match(claimed_title, t))},
                "notes": ["撤回の状況: 未確認(CiNii は対象外)", "CiNii Books の items[].title は開発時に観察した項目名(CiNii Research は appid がなく未観察)。画面でも確認すること"]}
    return {"status": "CANDIDATE", "reason": "%s_found_title_not_compared" % kind,
            "notes": ["識別子は検索結果にあるが、題名を照合できなかった(応答の項目名が未確認、または題名が違う)。画面で確認する"]}


def judge_ndl(xml_text, ndl_id, claimed_title):
    t = html.unescape(html.unescape(xml_text))
    m = re.search(r"<numberOfRecords>(\d+)</numberOfRecords>", t)
    n = int(m.group(1)) if m else None
    titles = []
    for x in re.findall(r"<dc:title[^>]*>(.*?)</dc:title>", t, re.S):
        v = re.search(r"<rdf:value>(.*?)</rdf:value>", x, re.S)
        titles.append(re.sub(r"<[^>]+>", "", v.group(1) if v else x).strip())
    id_found = bool(ndl_id) and ndl_id in t
    if not id_found:
        return {"status": "CANDIDATE", "reason": "ndl_id_not_in_results", "hits": n,
                "notes": ["題名で検索した NDL サーチの結果に指定の ID が見つからない。NDL サーチの画面で確認する"]}
    if claimed_title and any(titles_match(claimed_title, x) for x in titles):
        return {"status": "IDENTITY_CONFIRMED", "reason": "ndl_found_title_matched", "hits": n,
                "meta": {"title": next(x for x in titles if titles_match(claimed_title, x))},
                "notes": ["撤回の状況: 未確認(NDL は対象外)", "DC-NDL の dc:title(rdf:value)を読んだ(recordSchema=dcndl の形は開発時に観察)"]}
    return {"status": "CANDIDATE", "reason": "ndl_found_title_not_compared", "hits": n,
            "notes": ["ID は見つかったが題名を照合できなかった。画面で確認する"]}


# ---------------------------------------------------------------- network
def check_ref(ref, net, appid=None):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"id": ref.get("id"), "checked_at": now, "steps": [], "notes": []}
    doi = normalize_doi(ref.get("doi"))
    try:
        if doi:
            if not valid_doi_syntax(doi):
                return dict(out, status="NOT_FOUND", reason="invalid_doi_syntax", source="syntax")
            code, body = net.get("https://doi.org/api/handles/" + q(doi).replace("%2F", "/"))
            try:
                rc = json.loads(body.decode("utf-8", "replace")).get("responseCode")
            except ValueError:
                rc = None
            if rc == 100 or code == 404:
                return dict(out, status="NOT_FOUND", reason="doi_not_resolved", source="doi.org")
            if rc != 1:
                return dict(out, status=None, reason="handle_api_unexpected(http=%s,responseCode=%s)" % (code, rc))
            out["steps"].append("handle_resolved")
            mt = ("?mailto=" + q(net.mailto)) if net.mailto else ""
            code, body = net.get("https://api.crossref.org/works/" + q(doi).replace("%2F", "/") + mt)
            if code == 200:
                item = json.loads(body.decode("utf-8", "replace")).get("message") or {}
                out.update(judge(ref, item, "crossref"))
                out["source"] = "crossref"
                return out
            code, body = net.get("https://api.datacite.org/dois/" + q(doi).replace("%2F", "/"))
            if code == 200:
                data = json.loads(body.decode("utf-8", "replace")).get("data") or {}
                if isinstance(data, list):
                    data = data[0] if data else {}
                out.update(judge(ref, datacite_item(data.get("attributes") or {}), "datacite"))
                out["source"] = "datacite"
                return out
            return dict(out, status="CANDIDATE", reason="handle_ok_not_in_crossref_or_datacite", source="doi.org",
                        notes=["DOI は存在するが Crossref にも DataCite にもない(JaLC 等の可能性。JaLC API は調査で未確認)。"
                               "メタデータの照合と撤回の確認は未実施。撤回の状況は『未確認』で、『撤回されていない』ではない"])
        if ref.get("ncid"):
            ncid = ref["ncid"].strip().upper()
            if not NCID_RE.match(ncid):
                return dict(out, status="NOT_FOUND", reason="invalid_ncid_syntax", source="syntax")
            if not ref.get("title"):
                return dict(out, status="CANDIDATE", reason="ncid_needs_title", notes=["NCID の確認には題名が要る(題名で検索して NCID を探す)"])
            url = "https://ci.nii.ac.jp/books/opensearch/search?q=%s&format=json&count=50" % q(ref["title"])
            if appid:
                url += "&appid=" + q(appid)
            code, body = net.get(url)
            if code != 200:
                return dict(out, status=None, reason="cinii_books_http_%s" % code, url=redact(url))
            res = judge_cinii(json.loads(body.decode("utf-8", "replace")), ncid, "ncid", ref.get("title"))
            return dict(out, source="cinii-books", **res)
        if ref.get("crid"):
            if not appid:
                return dict(out, status="CANDIDATE", reason="cinii_appid_not_configured",
                            notes=["CiNii Research は appid が必須(NII の登録)。Plugin の設定 cinii_appid に入れる。画面での確認は可能"])
            if not ref.get("title"):
                return dict(out, status="CANDIDATE", reason="crid_needs_title")
            url = "https://cir.nii.ac.jp/opensearch/all?q=%s&format=json&count=50&appid=%s" % (q(ref["title"]), q(appid))
            code, body = net.get(url)
            if code != 200:
                return dict(out, status=None, reason="cinii_research_http_%s" % code, url=redact(url))
            res = judge_cinii(json.loads(body.decode("utf-8", "replace")), ref["crid"].strip(), "crid", ref.get("title"))
            return dict(out, source="cinii-research", **res)
        if ref.get("ndl_id"):
            if not ref.get("title"):
                return dict(out, status="CANDIDATE", reason="ndl_needs_title")
            query = 'title="%s"' % ref["title"].replace('"', " ")
            au = split_authors(ref.get("authors", ""))
            if au:
                query += ' AND creator="%s"' % author_key(au[0])[0]
            url = ("https://ndlsearch.ndl.go.jp/api/sru?operation=searchRetrieve&maximumRecords=50&recordSchema=dcndl&query="
                   + q(query))
            code, body = net.get_ndl(url)
            if code != 200:
                return dict(out, status=None, reason="ndl_http_%s" % code)
            res = judge_ndl(body.decode("utf-8", "replace"), ref["ndl_id"].strip(), ref.get("title"))
            res.pop("hits", None)
            return dict(out, source="ndl-sru", **res)
    except Exception as e:  # network failure: no status is written
        return dict(out, status=None, reason="network_error: %s" % type(e).__name__)
    isbn = clean_isbn(ref.get("isbn"))
    if isbn:
        if not isbn13_valid(isbn):
            if re.fullmatch(r"\d{9}[\dX]", isbn):
                return dict(out, status="CANDIDATE", reason="isbn10_not_validated", source="syntax",
                            notes=["ISBN-10 の検査算法は一次資料で未確認のため未実装。ISBN-13 を調べて入力するか、OPAC で確認"])
            return dict(out, status="NOT_FOUND", reason="invalid_isbn", source="syntax")
        return dict(out, status="CANDIDATE", reason="isbn13_checksum_ok_existence_not_checked", source="syntax",
                    notes=["チェックディジットは正しいが実在は未確認。NCID(CiNii Books)か NDL の ID を調べて register に入れると機械で確認できる"])
    return dict(out, status="CANDIDATE", reason="no_identifier", source="none",
                notes=["識別子(DOI・NCID・CRID・NDL ID・ISBN)がない。OPAC・CiNii・NDL サーチで探して記入する"])


def apply_results(rows, results):
    by_id = {r["id"]: r for r in results}
    for row in rows:
        res = by_id.get(row["id"])
        if not res or res.get("status") is None:
            continue
        if res["status"] == FORBIDDEN_WRITE or res["status"] not in MACHINE_STATUSES:
            raise ValueError("機械が書ける状態ではない: %r" % res["status"])
        row["machine_status"] = res["status"]
        row["machine_checked_at"] = res["checked_at"]
        row["machine_source"] = res.get("source", "")
        note = res.get("reason", "")
        d = res.get("details") or {}
        if d.get("mismatch_fields"):
            note += " mismatch=" + ",".join(d["mismatch_fields"])
        if d.get("retraction"):
            note += " retraction=" + json.dumps(d["retraction"], ensure_ascii=False)
        if d.get("retraction_notice_for"):
            note += " notice_for=" + json.dumps(d["retraction_notice_for"], ensure_ascii=False)
        if res.get("notes"):
            note += " | " + " / ".join(res["notes"])
        row["machine_note"] = note.strip()
    return rows


def log_entry(res):
    """What goes to sources/verification-log.jsonl: statuses and reasons, no raw API payload."""
    d = res.get("details") or {}
    keep = {k: d[k] for k in ("registry", "mismatch_fields", "retraction", "retraction_notice_for", "found_year") if k in d}
    if d.get("registry") in ("crossref", "datacite"):
        keep["found_title"] = d.get("found_title")
    return {"id": res.get("id"), "checked_at": res.get("checked_at"), "status": res.get("status"),
            "reason": res.get("reason"), "source": res.get("source"), "notes": res.get("notes"), "details": keep}
