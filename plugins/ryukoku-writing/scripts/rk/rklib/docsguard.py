"""docsguard - the Claude Docs guard of ryukoku-writing 3.0.

The student writes in one Claude Docs document per project. Its tabs have fixed roles (ROLES). This module is
called by the hooks (scripts/hooks/docs-guard.sh -> hookcore.py docs pre|post) for every Claude Docs tool call
and for the browser and screen tools.

PreToolUse (`pre`): decide allow or deny for a Claude Docs call on the registered document.
  - the AI never decides a suggestion (accept or reject); it may withdraw its own
  - the questions and thinking tab is closed to the AI
  - the claim card and settings tabs take suggestions only
  - the manuscript tab follows the course AI policy: allowed -> plain edits; limited and unknown -> suggestions
    only; prohibited (or a settings file that cannot be trusted) -> nothing
  - the AI does not delete or edit comments, resolve threads, rewind a tab, or create, delete or rename tabs;
    a member or an op this module does not know is denied on the registered document (fail closed)
  - browser and screen tools may not open claude.ai (a click there is recorded as the person's own)

PostToolUse (`post`): record what the Docs server answered, never what the AI says.
  - a project read whose tab names are the seven roles registers the document (.ryukoku/docs.json), once
  - a write to the manuscript tab is recorded as provenance (.ryukoku/docs-provenance.jsonl): the hashes of the
    paragraphs the AI wrote or suggested, its edit session and the revision
  - a comment listing (query) yields the student's decisions (.ryukoku/decisions.jsonl): only comments whose
    actor is the person the AI acts for, typed in the page (actor.self true, actor.via "frame"). The AI's own
    comments carry via "mcp" and never count. Observed on 2026-11-25 (SELF-ASSESSMENT.md).

The decisions are rebuilt from the server: before `check` and the export, the skills list the comments of every
tab, and this module records what the listing shows. The local files are a cache the AI cannot write (the
PreToolUse hook denies writes to .ryukoku/); they are not proof on their own.
"""
import json
import os
import re
import unicodedata

from .common import append_jsonl, atomic_write, course_policy, config_problems, now_iso, note_written, sha256_bytes

DOCS_REL = ".ryukoku/docs.json"
DECISIONS_REL = ".ryukoku/decisions.jsonl"
PROV_REL = ".ryukoku/docs-provenance.jsonl"
CACHE_REL = ".ryukoku/docs-threads.json"

# role -> the tab names that mean it (Japanese, English)
ROLES = {
    "manuscript": ("原稿", "Manuscript"),
    "claims": ("主張カード", "Claim cards"),
    "sources": ("文献台帳", "Sources"),
    "thinking": ("問いと思考の記録", "Questions and thinking"),
    "verification": ("検証", "Verification"),
    "settings": ("設定", "Settings"),
    "disclosure": ("開示と提出前", "Disclosure and submission"),
}
SUGGEST_ONLY = ("claims", "settings")
CLOSED = ("thinking",)
READ_ONLY_TOOLS = ("read", "query", "export", "guide")
POLICY_WORDS = {"許可": "allowed", "限定": "limited", "不明": "unknown", "禁止": "prohibited",
                "allowed": "allowed", "limited": "limited", "unknown": "unknown", "prohibited": "prohibited"}
# a comment the AI writes that looks like a decision is denied. Only an aid: a decision counts only when the
# server says the person typed it in the page (via "frame"), whatever the words.
DECISION_WORDS = re.compile(r"(確認|VERIFIED|verified|confirm|提出|科目の条件|ai_policy)", re.I)
CLAIM_RE = re.compile(r"\b(C\d{3,4})\b")
SOURCE_RE = re.compile(r"\b(S\d{3,4})\b")
PAGE_RE = re.compile(r"(?:p\.|pp\.|頁|ページ)\s*[0-9０-９ivxlcIVXLC][^\s、。,]*")


def _nfkc(s):
    return unicodedata.normalize("NFKC", s or "")


def tool_kind(tool_name):
    """'docs', 'browser' or '' for a tool name, and the Docs tool's short name."""
    t = tool_name or ""
    m = re.match(r"^mcp__(?:[A-Za-z0-9_-]*?_)?Claude_Docs__([A-Za-z_]+)$", t)
    if m:
        return "docs", m.group(1)
    if re.match(r"^mcp__(claude-in-chrome|[A-Za-z0-9_-]*Claude_Browser|[A-Za-z0-9_-]*computer[-_]?use)__", t, re.I) or t in ("computer",):
        return "browser", t
    return "", ""


# --------------------------------------------------------------------------- the registered document
def load(proj):
    try:
        with open(os.path.join(proj, DOCS_REL), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("doc") else None
    except (OSError, ValueError):
        return None


def _role_of_name(name):
    n = _nfkc(name).strip().lower()
    for role, names in ROLES.items():
        if n in (_nfkc(x).lower() for x in names):
            return role
    return None


def role_of(reg, ident):
    """The role whose tab file or tab body has this id, or None."""
    if not reg or not ident:
        return None
    for role, t in (reg.get("tabs") or {}).items():
        if ident in (t.get("file"), t.get("body")):
            return role
    return None


def _touches(reg, ti):
    """Whether a Docs call's input names the registered document (its id, or the id of one of its tabs)."""
    if not reg:
        return False
    ids = {reg["doc"]}
    for t in (reg.get("tabs") or {}).values():
        ids.update(x for x in (t.get("file"), t.get("body")) if x)
    found = []

    def walk(n, depth=0):
        if depth > 40:
            return
        if isinstance(n, dict):
            for k, v in n.items():
                if isinstance(v, str) and k in ("id", "slug") and v in ids:
                    found.append(v)
                walk(v, depth + 1)
        elif isinstance(n, list):
            for v in n:
                walk(v, depth + 1)
    walk(ti)
    return bool(found)


# --------------------------------------------------------------------------- PreToolUse
def _deny(ja, en):
    return ("deny", ja, en)


def _acts(short, ti):
    """The calls a Docs tool input makes, each {verb, object, ref, payload}."""
    ti = ti if isinstance(ti, dict) else {}
    if short == "batch":
        out = []
        for m in ti.get("batch") or []:
            if not isinstance(m, dict):
                out.append({"verb": "?"})
                continue
            out.append({"verb": m.get("verb"), "object": m.get("object") or (m.get("ref") or {}).get("object"),
                        "ref": m.get("ref") or {}, "payload": m.get("payload")})
        return out
    if short == "update":
        return [{"verb": "update", "object": (ti.get("ref") or {}).get("object"), "ref": ti.get("ref") or {}, "payload": ti.get("payload")}]
    if short in ("create", "delete"):
        obj = ti.get("object") or (ti.get("ref") or {}).get("object")
        return [{"verb": short, "object": obj, "ref": ti.get("ref") or {}, "payload": ti.get("payload")}]
    return [{"verb": "?", "object": short}]


def _parent_of(payload):
    if not isinstance(payload, dict):
        return {}
    v = payload.get("value") if isinstance(payload.get("value"), dict) else payload
    p = v.get("parent") if isinstance(v, dict) else None
    return p if isinstance(p, dict) else {}


def _check_prose(reg, proj, role, payload):
    """An edit of a tab's text (engine prose)."""
    payload = payload if isinstance(payload, dict) else {}
    ops = payload.get("ops") if isinstance(payload.get("ops"), list) else []
    suggest = payload.get("suggest")
    suggesting = suggest is True or (isinstance(suggest, str) and suggest.startswith("sg_"))
    decides = [o for o in ops if isinstance(o, dict) and o.get("op") == "decide"]
    for o in decides:
        if o.get("verdict") != "withdraw":
            return _deny("提案の採否(✓・✕)は学生が画面で決める。AI は自分の提案を取り下げる(withdraw)ことだけができる。",
                         "The student accepts or rejects suggestions on the page. The AI may only withdraw its own.")
    if decides and len(decides) == len(ops):
        return None
    if any(isinstance(o, dict) and o.get("op") == "restore" for o in ops):
        return _deny("タブを前の版に巻き戻す操作は AI にはさせない(学生の書いた文が消えうる)。戻したい語は普通の挿入で戻す。",
                     "The AI does not rewind a tab (the student's words could go). Re-insert the words instead.")
    if role is None:
        return _deny("登録した文書の、役割の分からない場所への書き込みは止める(fail closed)。タブの本文を ref にして書く。",
                     "A write to an unknown place in the registered document is denied (fail closed).")
    if role in CLOSED:
        return _deny("「問いと思考の記録」は学生だけが書く(研究の問いと考えの過程は学生のもの。ガイドラインⅢ-1)。AI は書かない。問いの立て方はチャットで一緒に考える。",
                     "The questions and thinking tab is the student's alone. Discuss the question in the chat instead.")
    if role in SUGGEST_ONLY and not suggesting:
        return _deny("「主張カード」と「設定」のタブには、AI は提案(suggest: true)としてだけ書く。学生が ✓ で入れ、確定は学生のコメントで行う。",
                     "The claim card and settings tabs take suggestions only (suggest: true).")
    if role == "manuscript":
        pol = course_policy(proj)
        if pol == "unreadable":
            prob = (config_problems(proj) or ["?"])[0]
            return _deny("科目の AI 利用条件(.ryukoku/config.yml)を信用できないので、原稿には書かない: %s" % prob,
                         "The course AI policy cannot be trusted, so the AI does not write the manuscript: %s" % prob)
        if pol == "prohibited":
            return _deny("この科目は AI による原稿の執筆を禁止している(ai_policy: prohibited)。提案も出さない。検証はコメントでできる。",
                         "This course prohibits AI writing of the manuscript (ai_policy: prohibited). Comments for verification are fine.")
        if pol in ("limited", "unknown") and not suggesting:
            return _deny("科目の条件が %s なので、原稿には提案(suggest: true)としてだけ書く。学生が一つずつ見て ✓ で入れる。" % pol,
                         "The course policy is %s: write the manuscript as suggestions only (suggest: true)." % pol)
    return None


def _check_act(reg, proj, act):
    verb, obj = act.get("verb"), act.get("object")
    ref, payload = act.get("ref") or {}, act.get("payload")
    if obj == "utterance":
        if verb != "create":
            return _deny("コメントの削除・書き換えは AI にはさせない(学生の判断の記録になる)。",
                         "The AI does not delete or edit comments (they are the student's decisions).")
        v = payload.get("value") if isinstance(payload, dict) else None
        if isinstance(v, dict) and v.get("kind") in ("resolve",):
            return _deny("スレッドを閉じるのは学生。AI は閉じない。", "The student resolves threads, not the AI.")
        body = v.get("body") if isinstance(v, dict) else None
        if isinstance(body, str) and DECISION_WORDS.search(_nfkc(body)) and _decision_from_text(body, None):
            return _deny("判断のように読めるコメント(「確認」「VERIFIED」「提出」「科目の条件」など)は AI は書かない。判断は学生が画面でコメントする。",
                         "The AI does not write comments that read like a decision; the student comments on the page.")
        return None
    if obj == "node":
        if verb == "create":
            parent = _parent_of(payload)
            role = role_of(reg, parent.get("id")) if parent else None
            if parent.get("object") == "file" and role is None:
                return _deny("登録した文書に新しいタブを足すことはしない(タブの形は固定)。",
                             "The AI does not add tabs to the registered document.")
            return _check_prose(reg, proj, role, {"ops": [{"op": "insert"}]}) if role else _deny(
                "登録した文書の、役割の分からない場所への作成は止める(fail closed)。", "Unknown place in the registered document (fail closed).")
        if verb == "update":
            return _check_prose(reg, proj, role_of(reg, ref.get("id")), payload)
        return _deny("登録した文書の本文の削除・置き換えはしない。", "The AI does not delete a tab body in the registered document.")
    if obj == "blob" and verb == "create":
        return None
    if obj in ("project", "file"):
        return _deny("登録した文書の名前・タブ(作成・削除・改名・並べ替え)は変えない。", "The AI does not change the registered document's name or tabs.")
    return _deny("この操作(%s %s)は登録した文書では許していない(fail closed)。" % (verb, obj),
                 "This operation (%s %s) is not allowed on the registered document (fail closed)." % (verb, obj))


def pre(proj, tool_name, ti):
    """(decision, reason_ja, reason_en) or None to let the call through."""
    kind, short = tool_kind(tool_name)
    if kind == "browser":
        text = json.dumps(ti, ensure_ascii=False)
        if re.search(r"claude\.ai|claude\.com/artifact", text, re.I):
            return _deny("ブラウザや画面の操作の道具で claude.ai を開いたり操作したりしない。そこでの操作は学生の操作として記録される。",
                         "Browser and screen tools must not open or operate claude.ai: what they do there is recorded as the student's.")
        return None
    if kind != "docs" or short in READ_ONLY_TOOLS:
        return None
    reg = load(proj)
    if not _touches(reg, ti):
        return None
    for act in _acts(short, ti):
        r = _check_act(reg, proj, act)
        if r:
            return r
    return None


# --------------------------------------------------------------------------- PostToolUse
def response_json(resp):
    """The JSON object at the start of a Docs tool's answer (a list of text blocks, a dict, or a string)."""
    texts = []
    if isinstance(resp, list):
        texts = [b.get("text", "") for b in resp if isinstance(b, dict) and isinstance(b.get("text"), str)]
    elif isinstance(resp, dict):
        if isinstance(resp.get("content"), list):
            return response_json(resp["content"])
        return resp
    elif isinstance(resp, str):
        texts = [resp]
    for t in texts:
        t = t.lstrip()
        if not t.startswith("{"):
            continue
        try:
            obj, _end = json.JSONDecoder().raw_decode(t)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _write_file_noted(proj, relp, text):
    from .common import _written_path
    try:
        q = _written_path(proj, relp + ".files")
        os.makedirs(os.path.dirname(q), exist_ok=True)
        with open(q, "a", encoding="utf-8") as f:
            f.write(sha256_bytes(text.encode("utf-8")) + "\n")
    except OSError:
        pass
    atomic_write(os.path.join(proj, relp), text)


def _append_noted(proj, relp, rec):
    line = json.dumps(rec, ensure_ascii=False)
    note_written(proj, relp, [line])
    append_jsonl(os.path.join(proj, relp), rec)


def register(proj, resp):
    """Register the document from a project read, when the tab names are exactly the seven roles. Once only."""
    if load(proj):
        return None
    if not isinstance(resp, dict) or not isinstance(resp.get("files"), list):
        return None
    value = resp.get("value") or {}
    slug = ((value.get("artifact") or {}).get("slug")) or ""
    tabnames = value.get("tabs") or {}
    tabs = {}
    for f in resp["files"]:
        if not isinstance(f, dict):
            continue
        name = (tabnames.get(f.get("id")) or {}).get("name") or f.get("name")
        role = _role_of_name(name)
        if role is None or role in tabs:
            return None
        tabs[role] = {"file": f.get("id"), "body": (f.get("content") or {}).get("id"), "name": name}
    if set(tabs) != set(ROLES) or not slug:
        return None
    rec = {"doc": slug, "title": value.get("name", ""), "url": (resp.get("frame") or {}).get("url", ""),
           "tabs": tabs, "registered_at": now_iso()}
    _write_file_noted(proj, DOCS_REL, json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
    return rec


def _texts(node, out, key="", depth=0):
    """Text the AI put into the document: string leaves under content, markdown or text keys of sources."""
    if depth > 40:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and k in ("content", "markdown", "text") and v.strip():
                out.append(v)
            else:
                _texts(v, out, k, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _texts(v, out, key, depth + 1)


def paragraph_hashes(text):
    """The hashes of the paragraphs of TEXT, as the provenance check compares them (NFKC, spaces folded)."""
    out = []
    for para in re.split(r"\n\s*\n", text or ""):
        p = re.sub(r"\s+", " ", _nfkc(para)).strip()
        p = re.sub(r"^#+\s*", "", p)
        if p:
            out.append(sha256_bytes(p.encode("utf-8")))
    return out


def _record_write(proj, reg, short, ti, resp, tuid):
    if short not in ("update", "batch", "create"):
        return
    acts = _acts(short, ti)
    for i, act in enumerate(acts):
        role = role_of(reg, (act.get("ref") or {}).get("id")) or role_of(reg, _parent_of(act.get("payload")).get("id"))
        if role != "manuscript":
            continue
        payload = act.get("payload") if isinstance(act.get("payload"), dict) else {}
        ops = payload.get("ops") if isinstance(payload.get("ops"), list) else []
        texts = []
        for o in ops:
            if isinstance(o, dict) and o.get("op") in ("insert", "replace"):
                _texts({"s": o.get("source"), "w": o.get("with")}, texts)
        if not texts:
            continue
        ack = resp or {}
        if short == "batch" and isinstance(ack.get("acks"), list) and i < len(ack["acks"]):
            ack = ack["acks"][i] or {}
        sug = payload.get("suggest")
        rec = {"at": now_iso(), "tool_use_id": tuid, "tab": "manuscript", "rev": ack.get("rev"),
               "session": ack.get("session") or (resp or {}).get("session"), "suggest": bool(sug),
               "suggestId": ack.get("suggestId") or (sug if isinstance(sug, str) else None),
               "ops": [o.get("op") for o in ops if isinstance(o, dict)],
               "paragraphs": [h for t in texts for h in paragraph_hashes(t)]}
        _append_noted(proj, PROV_REL, rec)


def _decision_from_text(body, role):
    """What a comment says, as a decision, or None. ROLE None: any role (used to spot AI comments that read like one)."""
    b = _nfkc(body).strip()
    if role in (None, "settings"):
        m = re.search(r"(?:科目の条件|ai_policy)\s*[:：]\s*(\S+)", b, re.I)
        if m and POLICY_WORDS.get(m.group(1).strip("。. ").lower()):
            src = re.search(r"根拠\s*[:：]\s*(.+)", b)
            return {"kind": "policy", "value": POLICY_WORDS[m.group(1).strip("。. ").lower()],
                    "source": src.group(1).strip()[:200] if src else ""}
        if re.search(r"(オプトアウト|opt-?out)\s*[:：]?\s*(済|した|done|yes)", b, re.I):
            return {"kind": "optout", "value": "done"}
    if role in (None, "claims"):
        m = CLAIM_RE.search(b)
        if m and re.search(r"(確認|confirm)", b, re.I) and not re.search(r"(未確認|確認しない|not confirm)", b, re.I):
            return {"kind": "claim", "id": m.group(1)}
    if role in (None, "sources"):
        m = SOURCE_RE.search(b)
        pg = PAGE_RE.search(b)
        if m and re.search(r"(VERIFIED|原典で確認|原典を読んで確認)", b, re.I):
            if not pg:
                return {"kind": "verified_incomplete", "id": m.group(1), "why": "頁が無い / no page"}
            return {"kind": "verified", "id": m.group(1), "locator": pg.group(0)}
    if role in (None, "disclosure"):
        if re.search(r"(提出を確認|submission confirmed)", b, re.I):
            return {"kind": "signoff"}
    return None


def _set_config(proj, values):
    """Set top-level scalars of .ryukoku/config.yml in one atomic write, noting the new content first (the general
    PostToolUse hook may compare the file at the same moment; a content the plugin's code wrote is no detection)."""
    path = os.path.join(proj, ".ryukoku", "config.yml")
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines(True)
    for key, value in values.items():
        pat = re.compile(r"^%s\s*:" % re.escape(key))
        rendered = "%s: %s\n" % (key, value)
        for i, line in enumerate(lines):
            if pat.match(line):
                m = re.search(r"\s+#.*$", line.rstrip("\n"))
                keep = m.group(0) if (m and not re.match(r"^%s\s*:\s*[\"']" % re.escape(key), line)) else ""
                lines[i] = rendered.rstrip("\n") + keep + "\n"
                break
        else:
            lines.append(rendered)
    _write_file_noted(proj, ".ryukoku/config.yml", "".join(lines))


def _threads(proj):
    try:
        with open(os.path.join(proj, CACHE_REL), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def recorded_comment_ids(proj):
    out = set()
    try:
        with open(os.path.join(proj, DECISIONS_REL), encoding="utf-8") as f:
            for ln in f:
                try:
                    out.add(json.loads(ln).get("comment"))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def _record_comments(proj, reg, ti, resp, tuid):
    rows = resp.get("rows") if isinstance(resp, dict) else None
    if not isinstance(rows, list):
        return []
    under = ((ti or {}).get("payload") or {}).get("under") or {}
    threads = _threads(proj)
    base_role = role_of(reg, under.get("id")) or threads.get(under.get("id"))
    seen = recorded_comment_ids(proj)
    out = []
    for r in rows:
        if not isinstance(r, dict) or r.get("verb") != "create":
            continue
        v = (r.get("payload") or {}).get("value") or {}
        parent = v.get("parent") or {}
        role = role_of(reg, parent.get("id")) or threads.get(parent.get("id")) or base_role
        if r.get("id") and role:
            threads[r["id"]] = role
        a = r.get("actor") or {}
        if not (a.get("self") is True and a.get("via") == "frame"):
            continue  # only the person the AI acts for, typing in the page
        if r.get("id") in seen or not isinstance(v.get("body"), str) or not role:
            continue
        d = _decision_from_text(v["body"], role)
        if not d:
            continue
        rec = dict(d, at=now_iso(), comment=r.get("id"), comment_at=r.get("at"), seq=r.get("seq"), role=role,
                   principal=a.get("principal"), body_sha256=sha256_bytes(v["body"].encode("utf-8")), tool_use_id=tuid)
        _append_noted(proj, DECISIONS_REL, rec)
        seen.add(r.get("id"))
        out.append(rec)
        if d["kind"] == "policy":
            _set_config(proj, {"ai_policy": d["value"], "ai_policy_source": json.dumps(d.get("source") or "", ensure_ascii=False)})
    _write_file_noted(proj, CACHE_REL, json.dumps(threads, ensure_ascii=False) + "\n")
    return out


def post(proj, tool_name, ti, resp_raw, tuid=""):
    """Record what the server answered. Returns a short note for the AI (or '')."""
    kind, short = tool_kind(tool_name)
    if kind != "docs":
        return ""
    resp = response_json(resp_raw)
    if resp is None or resp.get("verdict") == "deny":
        return ""
    reg = load(proj)
    notes = []
    if short == "read" and isinstance(ti, dict) and (ti.get("ref") or {}).get("object") == "project":
        r = register(proj, resp)
        if r:
            notes.append("ryukoku-writing: この文書をプロジェクトの文書として登録した(%s)。/ Registered this document as the project document." % r.get("title", ""))
        return "\n".join(notes)
    if not reg or not _touches(reg, ti):
        return ""
    if short == "query":
        recs = _record_comments(proj, reg, ti, resp, tuid)
        for d in recs:
            if d["kind"] == "verified_incomplete":
                notes.append("ryukoku-writing: %s の VERIFIED のコメントに頁が無いので数えない。学生に、確かめた頁を書いたコメントを頼む。" % d["id"])
            else:
                notes.append("ryukoku-writing: 学生の判断を記録した: %s %s" % (d["kind"], d.get("id") or d.get("value") or ""))
    else:
        _record_write(proj, reg, short, ti, resp, tuid)
    return "\n".join(notes)


def decisions(proj):
    """The recorded decisions, latest per (kind, id)."""
    out = {}
    try:
        with open(os.path.join(proj, DECISIONS_REL), encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                out[(r.get("kind"), r.get("id") or "")] = r
    except OSError:
        pass
    return out
