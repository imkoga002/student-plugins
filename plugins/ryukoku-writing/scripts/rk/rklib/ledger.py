"""Source register and claim ledger. Machine columns and human columns are separate.

sources/register.csv  one row per source (identifier, claimed metadata, machine result, human result)
sources/claims.csv    one row per claim: claim / source / locator (page etc.) / status

Machine columns (AI tools write them): machine_status, machine_checked_at, machine_source, machine_note
  values: IDENTITY_CONFIRMED / NOT_FOUND / METADATA_MISMATCH / RETRACTED / CANDIDATE
Human columns (written only when the student signs; rklib/decide.py): human_status, human_by, human_on,
human_note, human_record
  register human_status: VERIFIED / REJECTED (the student checked the item itself)
  claims   human_status: VERIFIED / CONTRADICTED / NOT_FOUND (empty = CANDIDATE)
A human_status counts only when a signed record in .ryukoku/signoffs.jsonl, by a trusted signer, covers the row's
current key fields (subjects.py). Edit the claim, locator or identifiers afterwards and the signature no longer
matches: `rk check` asks for a new signature.
"""
import csv
import os
import re

from .common import RkError, subject_hash

REGISTER = ["id", "citekey", "doi", "isbn", "ncid", "crid", "ndl_id", "url", "title", "authors", "year",
            "container", "language", "medium", "machine_status", "machine_checked_at", "machine_source",
            "machine_note", "human_status", "human_by", "human_on", "human_note", "human_record"]
CLAIMS = ["claim_id", "claim", "source_id", "locator", "used_in", "machine_status", "machine_note",
          "human_status", "human_by", "human_on", "human_note", "human_record"]
MACHINE_STATUSES = ("IDENTITY_CONFIRMED", "NOT_FOUND", "METADATA_MISMATCH", "RETRACTED", "CANDIDATE")
SOURCE_KEYS = ("id", "doi", "isbn", "ncid", "crid", "ndl_id", "url", "title", "authors", "year")
CLAIM_KEYS = ("claim_id", "claim", "source_id", "locator")


def paths(proj):
    return os.path.join(proj, "sources", "register.csv"), os.path.join(proj, "sources", "claims.csv")


def read(path, fields):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in fields:
            r.setdefault(k, "")
            if r[k] is None:
                r[k] = ""
    return rows


def write(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    os.replace(tmp, path)
    _note(path)


def _note(path):
    """Note the content the plugin's code wrote (msguard: a change during an AI tool call to a ledger file is
    explained only by such a content)."""
    from .common import note_written_file
    proj = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    note_written_file(proj, os.path.relpath(os.path.abspath(path), proj).replace(os.sep, "/"))


IDENTITY_REL = os.path.join("sources", "identity.json")


def read_identity(proj):
    """{row id: {"digest", "checked_at", "source", "meta"}}: what the machine identity check recorded from the registry
    for rows it confirmed (refcheck). Written only by `rk.py refcheck check`; the AI's tools cannot write the file."""
    import json
    try:
        with open(os.path.join(proj, IDENTITY_REL), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def record_identity(proj, rows, results):
    import json
    cur = read_identity(proj)
    by = {r.get("id"): r for r in rows}
    changed = False
    for res in results:
        rid = res.get("id")
        if res.get("status") is None or rid not in by:
            continue
        if res.get("status") == "IDENTITY_CONFIRMED":
            cur[rid] = {"digest": source_subject(by[rid]), "checked_at": res.get("checked_at", ""),
                        "source": res.get("source", ""), "meta": res.get("meta") or {}}
        else:
            cur.pop(rid, None)
        changed = True
    if changed:
        p = os.path.join(proj, IDENTITY_REL)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, p)
        _note(p)


def source_subject(row):
    return subject_hash({k: (row.get(k) or "").strip() for k in SOURCE_KEYS})


def claim_subject(row):
    return subject_hash({k: (row.get(k) or "").strip() for k in CLAIM_KEYS})


def _next(rows, key, prefix):
    n = 0
    for r in rows:
        m = re.match(r"^%s(\d+)$" % prefix, r.get(key, ""))
        if m:
            n = max(n, int(m.group(1)))
    return "%s%03d" % (prefix, n + 1)


def add_source(proj, **kw):
    reg, _ = paths(proj)
    rows = read(reg, REGISTER)
    if not any(kw.get(k) for k in ("doi", "isbn", "ncid", "crid", "ndl_id", "url", "title")):
        raise RkError("識別子(DOI・ISBN・NCID・CRID・NDL ID・URL)か題名が要る")
    row = {k: "" for k in REGISTER}
    for k, v in kw.items():
        if k in REGISTER and not k.startswith("human_") and not k.startswith("machine_"):
            row[k] = (v or "").strip()
    row["id"] = row["id"] or _next(rows, "id", "S")
    taken = {x for r in rows for x in ((r.get("id") or "").strip(), (r.get("citekey") or "").strip()) if x}
    if row["id"] in taken:
        raise RkError("id %s は既にある(台帳の id か citekey) / id %s is already taken" % (row["id"], row["id"]))
    if row.get("citekey") and row["citekey"] in taken:
        raise RkError("citekey %s は既にある(台帳の id か citekey)。一つのキーは一つの文献だけを指す / citekey %s is already taken"
                      % (row["citekey"], row["citekey"]))
    row["machine_status"] = "CANDIDATE"
    row["machine_note"] = "未検査(rk.py refcheck check で確認する)"
    rows.append(row)
    write(reg, rows, REGISTER)
    return row


def add_claim(proj, claim, source_id, locator="", used_in=""):
    reg, cl = paths(proj)
    if not claim.strip():
        raise RkError("主張(claim)が空")
    srcs = {r["id"] for r in read(reg, REGISTER)}
    if source_id and source_id not in srcs:
        raise RkError("source_id %s が register.csv にない(先に ledger add-source)" % source_id)
    rows = read(cl, CLAIMS)
    row = {k: "" for k in CLAIMS}
    row.update({"claim_id": _next(rows, "claim_id", "C"), "claim": claim.strip(), "source_id": source_id,
                "locator": locator.strip(), "used_in": used_in.strip(), "machine_status": "CANDIDATE"})
    rows.append(row)
    write(cl, rows, CLAIMS)
    return row


def duplicate_keys(rows):
    """Keys (id or citekey) that name more than one ledger row."""
    seen, dup = {}, set()
    for r in rows:
        for k in {(r.get("id") or "").strip(), (r.get("citekey") or "").strip()} - {""}:
            if k in seen and seen[k] is not r:
                dup.add(k)
            seen.setdefault(k, r)
    return sorted(dup)
