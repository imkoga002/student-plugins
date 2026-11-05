"""msguard - what changed while an AI tool call was running (per-window snapshots, watched places, before-copies of
protected files, AI-written files).

Two outcomes, by place:
  manuscript/**   a change is the AI's writing: it is recorded as provenance, paragraph by paragraph
                  (.ryukoku/provenance.jsonl, provenance.py), not raised as an alarm. Whether the AI may write at all
                  is decided before the call by the course AI policy (pre-guard.sh); the record is what makes the
                  disclosure factual and lets the verification compare AI text with the student's claim cards.
  everything else that is watched (below): a change is a detection, as in v1, because these are the records and
                  tools that keep the provenance, the signatures and the checks honest.

The PreToolUse hook calls `pre` before every tool call that may run (every tool; the hooks' matcher is "*") and
the PostToolUse hook calls `post` after it. Anything that changed in between happened inside the AI's tool
window, whatever the command looked like (obfuscated Bash, a script file, a subprocess). This is what backs the
pattern-matching guard.

Watched
  manuscript/**                       content (shadow copies keep the state at the start of the window) -> provenance
  tools/**, thinking/**, disclosure/**, .github/**, .githooks/**, rk, rk.cmd, rk.ps1
  .ryukoku/config.yml, signers.json, style.yml, research/questions.md
  .claude/settings.json, .claude/settings.local.json (project) and ~/.claude/settings.json, settings.local.json
  ~/.ryukoku-writing/plugin-root (where ./rk finds the plugin) and the per-user trust copy of the signers
  sources/references.json             the author and year of works already listed (new works may be added)
  append-only: .ryukoku/signoffs.jsonl (only signed records that verify under a trusted signer; a light
               confirmation has no signature, so one that appears during an AI tool call is reported),
               .ryukoku/ai-use-log.jsonl, .ryukoku/provenance.jsonl, research/search-log.jsonl,
               review/annotations-log.jsonl
Each window keeps its own snapshot (state/<project>/windows/<tool_use_id>.json) and compares against it, so code
that rewrites the shared baseline during the call does not hide its change. A window opened for a call that
asks the student first is "pending": it is dropped at the next tool call when no PostToolUse came (the student
declined), so the student's own edits after a declined call are not reported as AI changes.
Every detection is appended to the hash-chained AI-use log (committed) and to a witness list outside the project:
`rk check` fails locally and in CI until the student signs a decision (kept as AI involvement / it was my own edit
/ reverted), and locally when a detection on the witness list is missing from the log (so deleting the line and
rebuilding the chain does not hide it).
A change that a valid signed record explains (a hunk the student accepted, a revert, an approved style rule, the
disclosure line the notebook appends when signing) is not reported. Changes between tool calls (the student's own
editor) are absorbed at `pre` when no window is open.

After a call, the files that changed during it (in the project, and the paths the command named) are added to the
list of AI-written files (execgate): the PreToolUse hook asks the student before the AI runs any of them.

Limits (README "保証しないこと"): code that runs with the student's rights can rewrite every record on this
computer; a detached process that writes after the call returned looks like the student's own edit.
"""
import json
import os
import re
import shlex
import shutil
import time

from . import ailog, execgate, provenance, sign, style, subjects, trust
from .common import (load_config, manuscript_files, register_project, rel, sha256_bytes, sha256_file, state_dir,
                     state_home, trust_path)

MAX_FILE = 20 * 1024 * 1024
WINDOW_STALE = 12 * 60
TREES = ("tools", "thinking", "disclosure", ".github", ".githooks", "pandoc")
FILES = (".ryukoku/config.yml", ".ryukoku/signers.json", ".ryukoku/style.yml", "research/questions.md",
         "rk", "rk.cmd", "rk.ps1", ".claude/settings.json", ".claude/settings.local.json")
APPEND_ONLY = ("research/search-log.jsonl", "review/annotations-log.jsonl", ".ryukoku/provenance.jsonl")
SKIP_SCAN = {".git", "node_modules", "__pycache__", ".venv", "venv", ".rk-base"}


def _sha_or_empty(p):
    try:
        if os.path.getsize(p) > MAX_FILE:
            return "big:%d" % os.path.getsize(p)
        return sha256_file(p)
    except OSError:
        return ""


def manuscript_map(proj):
    return {rel(proj, p): _sha_or_empty(p) for p in manuscript_files(proj)}


def external_files(proj):
    """Watched files outside the project: {key: absolute path}."""
    home = os.path.expanduser("~")
    return {"~/.claude/settings.json": os.path.join(home, ".claude", "settings.json"),
            "~/.claude/settings.local.json": os.path.join(home, ".claude", "settings.local.json"),
            "~/.ryukoku-writing/plugin-root": os.path.join(state_home(), "plugin-root"),
            "trust-copy": trust_path(proj)}


def _abs(proj, key):
    ext = external_files(proj)
    return ext.get(key) or os.path.join(proj, key)


def watched(proj):
    """{key: sha} of every watched file (trees expanded per file)."""
    out = {}
    for t in TREES:
        base = os.path.join(proj, t)
        if os.path.isdir(base):
            for dp, dns, fns in os.walk(base):
                dns[:] = sorted(d for d in dns if d != "__pycache__")
                for fn in sorted(fns):
                    if fn.endswith(".pyc") or (t == "disclosure" and fn.startswith("statement") and fn.endswith(".md")):
                        continue  # the disclosure statement draft is the AI's to draft (the student confirms it)
                    full = os.path.join(dp, fn)
                    out[rel(proj, full)] = _sha_or_empty(full)
    for f in FILES:
        out[f] = _sha_or_empty(os.path.join(proj, f))
    for k, p in external_files(proj).items():
        out[k] = _sha_or_empty(p)
    return out


def refs_map(proj):
    """{id: [family names, year]} of sources/references.json (what the citation proposals are checked against)."""
    from .proposals import _refs
    return {k: [list(v[0]), v[1]] for k, v in _refs(proj).items()}


def _len(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _sync_shadow(proj, st, cur, old, sub):
    shadow = os.path.join(st, sub)
    for r, h in cur.items():
        dst = os.path.join(shadow, r.replace("~/", "_home_/"))
        if old.get(r) != h or not os.path.exists(dst):
            try:
                if h:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(_abs(proj, r) if sub == "pshadow" else os.path.join(proj, r), dst)
                elif os.path.exists(dst):
                    os.remove(dst)
            except OSError:
                pass
    for r in old:
        if r not in cur:
            try:
                os.remove(os.path.join(shadow, r.replace("~/", "_home_/")))
            except OSError:
                pass


def _prefix_hash(p, n):
    try:
        with open(p, "rb") as f:
            return sha256_bytes(f.read(n))
    except OSError:
        return ""


def _append_state(proj):
    out = {}
    for r in (sign.SIGNOFFS_REL, ailog.LOG_REL) + APPEND_ONLY:
        p = os.path.join(proj, r)
        n = _len(p)
        out[r.replace(os.sep, "/")] = [n, _prefix_hash(p, n)]
    return out


def snapshot(proj, st, old=None):
    cur = manuscript_map(proj)
    _sync_shadow(proj, st, cur, (old or {}).get("manuscript", {}), "shadow")
    w = watched(proj)
    _sync_shadow(proj, st, w, (old or {}).get("watched", {}), "pshadow")
    return {"manuscript": cur, "watched": w, "append": _append_state(proj), "refs": refs_map(proj), "at": time.time()}


def _baseline(proj, st, old=None):
    base = snapshot(proj, st, old)
    _save(os.path.join(st, "baseline.json"), base)
    try:
        provenance.ensure_known(proj)  # first sight of a manuscript file: the text to compare the next edits with
    except OSError:
        pass
    return base


def _wdir(st, tuid):
    return _wpath(st, tuid)[:-5] + ".files"


def _copy_window_files(proj, st, tuid):
    """The manuscript as it was when this window opened (provenance diffs against it, even if code inside the call
    rebuilds the shared baseline and its shadow copies)."""
    d = _wdir(st, tuid)
    shutil.rmtree(d, ignore_errors=True)
    for p in manuscript_files(proj):
        try:
            if os.path.getsize(p) > MAX_FILE:
                continue
            dst = os.path.join(d, rel(proj, p))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(p, dst)
        except OSError:
            pass


def _windows(st):
    w = _load(os.path.join(st, "open.json"), {})
    now = time.time()
    out = {}
    for k, v in w.items():
        v = v if isinstance(v, dict) else {"t": float(v), "ask": False}
        if now - float(v.get("t", 0)) < WINDOW_STALE:
            out[k] = v
    return out


def _wpath(st, tuid):
    return os.path.join(st, "windows", re.sub(r"[^A-Za-z0-9_-]", "_", tuid or "anon")[:80] + ".json")


def _witness_dir():
    d = os.environ.get("CLAUDE_PLUGIN_DATA")
    return os.path.join(d, "witness") if d else None


def pre(proj, tool_use_id="", mode="run"):
    """Open a window. MODE 'ask': the student is asked first; the window only counts if PostToolUse comes."""
    register_project(proj)
    st = state_dir(proj)
    w = _windows(st)
    for k in [k for k, v in w.items() if v.get("ask")]:
        w.pop(k)  # a call that asked and got no PostToolUse was declined
        shutil.rmtree(_wdir(st, k), ignore_errors=True)
        try:
            os.remove(_wpath(st, k))
        except OSError:
            pass
    old = _load(os.path.join(st, "baseline.json"), None)
    if not w or old is None or "append" not in old:
        if not w:
            try:
                provenance.sync_student(proj)  # what changed since the last call is the student's (estimated)
            except OSError:
                pass
        base = _baseline(proj, st, old)
    else:
        base = old
    tuid = tool_use_id or "anon"
    w[tuid] = {"t": time.time(), "ask": mode == "ask"}
    _save(os.path.join(st, "open.json"), w)
    _save(_wpath(st, tuid), dict(base, stat=stat_map(proj)))
    _copy_window_files(proj, st, tuid)
    wd = _witness_dir()
    if wd:
        try:
            _save(os.path.join(wd, "window-" + os.path.basename(_wpath(st, tuid))), {"sha": sha256_file(_wpath(st, tuid))})
        except OSError:
            pass
    return {"ok": True}


def _new_records(proj, ref):
    """Signed records appended since REF, split into (valid under trusted signers, other)."""
    p = os.path.join(proj, sign.SIGNOFFS_REL)
    n0, h0 = (ref.get("append") or {}).get(sign.SIGNOFFS_REL.replace(os.sep, "/"), [0, ""])
    n0 = int(n0 or 0)
    if _len(p) < n0 or _prefix_hash(p, n0) != (h0 or _prefix_hash(p, 0)):
        return None, None  # not an append
    with open(p, "rb") as f:
        f.seek(n0)
        tail = f.read().decode("utf-8", "replace")
    trusted, _probs, _notes = trust.local_trusted(proj)
    good, bad = [], []
    for line in tail.splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            bad.append(line)
            continue
        ok, _why = sign.verify_record(r, trusted)
        if ok and sign.is_light(r):
            ok = False  # an unsigned confirmation is made by the student's screen or terminal, never inside an AI call
        (good if ok else bad).append(r)
    return good, bad


def _explained_manuscript(r_after, path, good):
    for rec in good or []:
        d = rec.get("detail") or {}
        if d.get("target") == path and d.get("after_sha256") == r_after:
            return True
    return False


def _explained_watched(proj, st, key, good):
    if not good:
        return False
    if key == ".ryukoku/style.yml":
        idx = {}
        for r in good:
            idx.setdefault((r["kind"], r["subject"]), []).append(r)
        _t, rules = style.load(style.approved_path(proj))
        return all(any(x.get("digest") == style.rule_subject(rr) and x.get("decision") == "approved"
                       for x in idx.get(("rule", rr.get("id", "")), [])) for rr in rules) and bool(rules)
    if key == ".ryukoku/config.yml":
        dg = subjects.config_subject(proj).digest
        return any(r["kind"] in ("config", "optout") and (r["kind"] == "optout" or r.get("digest") == dg) for r in good)
    if key.startswith("disclosure/"):
        # the notebook / ./rk apply append one line per accepted hunk while signing: an append is explained
        old = os.path.join(st, "pshadow", key)
        try:
            with open(old, "rb") as f:
                before = f.read()
            with open(os.path.join(proj, key), "rb") as f:
                now = f.read()
        except OSError:
            return False
        return now.startswith(before) and any(r.get("kind") == "hunk" for r in good)
    return False


def _already_logged(proj, since, path, after):
    for e in ailog.detections([o for _l, _r, o in ailog.read(proj) if o]):
        if e.get("path") == path and e.get("after_sha256") == after and e.get("at", 0) >= since - 1:
            return True
    return False


def post(proj, tool="", summary="", tool_use_id="", command="", file_path=""):
    st = state_dir(proj)
    out = {"entries": [], "manuscript_changed": [], "other_changed": []}
    tuid = tool_use_id or "anon"
    w = _windows(st)
    w.pop(tuid, None)
    _save(os.path.join(st, "open.json"), w)
    wp = _wpath(st, tuid)
    ref = _load(wp, None)
    base = _load(os.path.join(st, "baseline.json"), None)
    other = []
    if ref is not None:
        wd = _witness_dir()
        if wd:
            wit = _load(os.path.join(wd, "window-" + os.path.basename(wp)), None)
            if wit and wit.get("sha") != sha256_file(wp):
                other.append("検知の記録(ツール実行の前の写し)が実行中に書き換えられた / the detection snapshot was rewritten")
            try:
                os.remove(os.path.join(wd, "window-" + os.path.basename(wp)))
            except OSError:
                pass
        try:
            os.remove(wp)
        except OSError:
            pass
    else:
        ref = base
    if ref is None or "append" not in ref:  # no snapshot, or one from an older version: start over
        _baseline(proj, st)
        return out
    _record_ai_files(proj, tool, float(ref.get("at") or time.time()), command, file_path, ref.get("stat"))
    good, bad = _new_records(proj, ref)
    cur = manuscript_map(proj)
    old = ref.get("manuscript", {})
    changed = [r for r in sorted(set(old) | set(cur)) if old.get(r) != cur.get(r)]
    changed = [r for r in changed if not (r in cur and _explained_manuscript(cur[r], r, good))]
    changed = [r for r in changed if not _already_logged(proj, float(ref.get("at") or 0), r, cur.get(r) or None)]
    wcur = watched(proj)
    wold = ref.get("watched", {})
    parts = [k for k in sorted(set(wold) | set(wcur)) if wold.get(k) != wcur.get(k)]
    parts = [k for k in parts if not _explained_watched(proj, st, k, good)]
    other += parts
    if good is None:
        other.append(".ryukoku/signoffs.jsonl(追記でない変更)")
    elif bad:
        other.append(".ryukoku/signoffs.jsonl(AI のツール実行中に、署名のない確認か検証できない記録 %d 件の追加)" % len(bad))
    for r in (ailog.LOG_REL,) + APPEND_ONLY:
        key = r.replace(os.sep, "/")
        n0, h0 = (ref.get("append") or {}).get(key, [0, ""])
        p = os.path.join(proj, r)
        if _len(p) < int(n0 or 0) or (n0 and _prefix_hash(p, int(n0)) != h0):
            other.append("%s(追記でない変更: 行の削除・書き換え)" % key)
    oref, nref = ref.get("refs") or {}, refs_map(proj)
    moved = sorted(k for k in oref if k not in nref or nref[k] != oref[k])
    if moved:
        other.append("sources/references.json(既存の文献の著者・年の変更・削除: %s)" % ", ".join(moved[:5]))
    stamp = time.strftime("%Y%m%dT%H%M%S")
    shadow = os.path.join(st, "shadow")
    n = 0
    out["provenance"] = []
    wfiles = _wdir(st, tuid)
    for r in changed:
        src = os.path.join(wfiles, r)
        if not os.path.exists(src):
            src = os.path.join(shadow, r)
        before = _read(src) if (os.path.exists(src) and old.get(r)) else ""
        after = _read(os.path.join(proj, r)) if cur.get(r) else ""
        if before is None or after is None:
            continue
        if provenance.known_text(proj, r) == after:
            continue  # already recorded (an accepted proposal records itself)
        try:
            ents = provenance.record_ai(proj, r, before, after, tool)
        except OSError:
            continue
        out["provenance"].append({"file": r, "wrote": sum(1 for e in ents if e["actor"] == "ai" and e["kind"] == "ai_wrote" and e["block"] == "paragraph"),
                                  "edited": sum(1 for e in ents if e["actor"] == "ai" and e["kind"] == "ai_edited" and e["block"] == "paragraph"),
                                  "deleted": sum(1 for e in ents if e["actor"] == "ai" and e["kind"] == "ai_deleted" and e["block"] == "paragraph"),
                                  "student_estimated": sum(1 for e in ents if e["actor"] == "student")})
    if other:
        n += 1
        uid = "U-%s-%02d-%s" % (stamp, n, sha256_bytes(os.urandom(8))[:6])
        files = []
        for k in parts:
            src = os.path.join(st, "pshadow", k.replace("~/", "_home_/"))
            if os.path.isfile(src) and wold.get(k):
                dst = os.path.join(st, "before", uid, "p", k.replace("~/", "_home_/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    shutil.copy2(src, dst)
                except OSError:
                    continue
            files.append(k)
        ailog.append(proj, {"type": "detection", "id": uid, "what": "protected", "parts": other, "files": files,
                            "tool": tool, "summary": (summary or "")[:200], "at": time.time()})
        out["entries"].append(uid)
    out["manuscript_changed"], out["other_changed"] = changed, other
    shutil.rmtree(wfiles, ignore_errors=True)
    _baseline(proj, st, base or ref)
    return out


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def stat_map(proj):
    """{relative path: [inode, size, mtime_ns, ctime_ns]} of the project's files. The change time (ctime) cannot be
    set back by touch -d, and mv, cp and tar make a new inode or ctime, so a file written in the window is found
    even when its modification time was made old."""
    out, n = {}, 0
    for dp, dns, fns in os.walk(proj):
        dns[:] = [d for d in dns if d not in SKIP_SCAN]
        for fn in fns:
            n += 1
            if n > 20000:
                return out
            p = os.path.join(dp, fn)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            out[os.path.relpath(p, proj)] = [st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
    return out


def _record_ai_files(proj, tool, since, command, file_path, before=None):
    """Files the AI wrote or changed in this call -> execgate's list, by path and content hash."""
    found = []
    if file_path:
        found.append(file_path if os.path.isabs(file_path) else os.path.join(proj, file_path))
    if command:  # files outside the project that the command names: changed (ctime) during the call
        try:
            words = shlex.split(command, comments=True)
        except ValueError:
            words = command.split()
        for wd in words:
            for cand in re.split(r"[=:]", wd):
                if not cand or cand.startswith("-"):
                    continue
                p = os.path.expanduser(cand)
                p = p if os.path.isabs(p) else os.path.join(proj, p)
                try:
                    if os.path.isfile(p) and os.stat(p).st_ctime >= since - 1:
                        found.append(p)
                    elif os.path.isdir(p) and os.stat(p).st_ctime >= since - 1:
                        for dp, _dns, fns in os.walk(p):
                            found += [os.path.join(dp, f) for f in fns[:200]]
                except OSError:
                    pass
    if before is not None:
        for r, v in stat_map(proj).items():
            if before.get(r) != v:
                found.append(os.path.join(proj, r))
    if found:
        execgate.add_ai_files(found, tool)


def before_copy_path(proj, det):
    """Path of the saved pre-change copy for a manuscript detection (None when this computer lacks it)."""
    p = os.path.join(state_dir(proj), "before", det.get("id", ""), det.get("path") or "")
    return p if det.get("path") and os.path.isfile(p) else None


def protected_diffs(proj, det):
    """[(key, before_text or None, current_text or None)] for a protected detection (shown to the student before they decide)."""
    out = []
    for k in det.get("files") or []:
        b = os.path.join(state_dir(proj), "before", det.get("id", ""), "p", k.replace("~/", "_home_/"))
        cur = _abs(proj, k)

        def rd(p):
            try:
                with open(p, encoding="utf-8") as f:
                    return f.read()
            except (OSError, UnicodeDecodeError):
                return None
        out.append((k, rd(b) if os.path.isfile(b) else None, rd(cur) if os.path.isfile(cur) else None))
    return out


def pending(proj, idx):
    """Detections in the AI-use log without a signed decision (IDX: sign.valid_index under trusted signers)."""
    out = []
    for s in subjects.changes(proj):
        if not sign.current(idx, "change", s.sid, s.digest):
            out.append(s)
    return out


def active(proj):
    return os.path.isfile(os.path.join(proj, ".ryukoku", "config.yml")) and bool(load_config(proj))
