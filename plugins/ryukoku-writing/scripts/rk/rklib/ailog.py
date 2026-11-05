"""The AI-use log .ryukoku/ai-use-log.jsonl: written only by the hooks, chained by hashes, committed to Git.

Every line carries "prev" = SHA-256 of the previous line (the first line: "GENESIS"). Deleting or rewriting a
line breaks the chain; truncating the file and rebuilding a consistent chain is caught locally by the head
remembered outside the project (state_dir/log-head.json) and in CI by requiring the file to extend the base
branch's version. The log holds facts only: dates, the model name, prompt *categories* (never prompt text),
tool names and areas, and the change detections of msguard (so a detection reaches CI and cannot be cleared
inside the project). Appends take a lock.
"""
import json
import os

from .common import FileLock, RkError, now_iso, sha256_bytes, state_dir, today, tr

LOG_REL = os.path.join(".ryukoku", "ai-use-log.jsonl")
GENESIS = "GENESIS"


def path(proj):
    return os.path.join(proj, LOG_REL)


def line_hash(line):
    return sha256_bytes(line.rstrip("\r\n").encode("utf-8"))


def _last_line(p):
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            back = min(size, 65536)
            f.seek(size - back)
            chunk = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    lines = [x for x in chunk.split("\n") if x.strip()]
    return lines[-1] if lines else None


def _head_path(proj):
    return os.path.join(state_dir(proj), "log-head.json")


def append(proj, obj):
    p = path(proj)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    obj = dict(obj)
    obj.setdefault("date", today())
    obj.setdefault("ts", now_iso())
    with FileLock(p + ".lock"):
        last = _last_line(p)
        obj["prev"] = line_hash(last) if last else GENESIS
        line = json.dumps(obj, ensure_ascii=False, sort_keys=True)
        with open(p, "a", encoding="utf-8", newline="") as f:
            f.write(line + "\n")
        try:
            n = sum(1 for x in open(p, encoding="utf-8") if x.strip())
            with open(_head_path(proj), "w", encoding="utf-8") as f:
                json.dump({"lines": n, "head": line_hash(line)}, f)
        except OSError:
            pass
        if obj.get("type") == "detection":
            _witness(proj, {"id": obj.get("id"), "line": line_hash(line), "ts": obj.get("ts")})
    return obj


def witness_paths(proj):
    """Where the hooks also note every detection, outside the project (so a detection removed from the log and a
    rebuilt chain are still caught): the per-user state
    folder and, when the hook knows it, the plugin's data folder of Claude Code (${CLAUDE_PLUGIN_DATA})."""
    out = [os.path.join(state_dir(proj), "detections-witness.jsonl")]
    d = os.environ.get("CLAUDE_PLUGIN_DATA")
    if d:
        out.append(os.path.join(d, "witness", "%s-detections.jsonl" % os.path.basename(state_dir(proj))))
    return out


def _witness(proj, rec):
    for p in witness_paths(proj):
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass


def missing_witnessed(proj, rows=None):
    """Detection ids noted on this computer that are not in the AI-use log (a detection was removed)."""
    rows = read(proj) if rows is None else rows
    ids = {o.get("id") for _l, _r, o in rows if o and o.get("type") == "detection"}
    miss = []
    for p in witness_paths(proj):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    try:
                        w = json.loads(line)
                    except ValueError:
                        continue
                    if w.get("id") and w["id"] not in ids and w["id"] not in miss:
                        miss.append(w["id"])
        except OSError:
            continue
    return miss


def read(proj):
    p = path(proj)
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            if line.strip():
                try:
                    out.append((ln, line.rstrip("\r\n"), json.loads(line)))
                except ValueError:
                    out.append((ln, line.rstrip("\r\n"), None))
    return out


def verify(proj, local=True, lang="ja"):
    """(entries, problems). Problems: unreadable lines, broken chain, and (local) a rewritten or truncated log."""
    rows = read(proj)
    probs = []
    prev = GENESIS
    for ln, raw, obj in rows:
        if obj is None:
            probs.append(tr(lang, "AI 利用記録 %d 行目が JSON でない(改変の可能性)", "AI-use log line %d is not JSON (possibly altered)") % ln)
        elif obj.get("prev") != prev:
            probs.append(tr(lang, "AI 利用記録の連鎖が %d 行目で切れている(行の削除・書き換えの可能性。記録はフックだけが追記する)",
                            "the AI-use log chain breaks at line %d (lines deleted or rewritten; only the hooks append to it)") % ln)
        prev = line_hash(raw)
    if local:
        try:
            with open(_head_path(proj), encoding="utf-8") as f:
                head = json.load(f)
        except (OSError, ValueError):
            head = None
        if head and head.get("lines"):
            n = int(head["lines"])
            if len(rows) < n or line_hash(rows[n - 1][1]) != head.get("head"):
                probs.append(tr(lang, "AI 利用記録が、この PC で最後に記録した内容(%d 行)の続きになっていない。切り詰め・作り直しの可能性",
                                "the AI-use log does not continue what this computer last recorded (%d lines): truncated or rebuilt?") % n)
        miss = missing_witnessed(proj, rows)
        if miss:
            probs.append(tr(lang, "この PC で記録した変更の検知 %d 件(%s)が AI 利用記録に無い。検知の行が消された可能性",
                            "%d change detections noted on this computer (%s) are missing from the AI-use log: removed?")
                         % (len(miss), ", ".join(miss[:3])))
    return [o for _l, _r, o in rows if o is not None], probs


def detections(entries):
    return [e for e in entries if e.get("type") == "detection"]


def base_prefix_problem(proj, base_text, rel):
    cur = ""
    p = os.path.join(proj, rel)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            cur = f.read()
    if not cur.startswith(base_text):
        return "%s が基準ブランチの内容の追記になっていない(過去の記録が消された・書き換えられた)" % rel.replace(os.sep, "/")
    return None


def safe_append(proj, obj):
    try:
        return append(proj, obj)
    except (OSError, RkError):
        return None
