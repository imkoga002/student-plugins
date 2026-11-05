"""Annotation store review/annotations.json (W3C Web Annotation style).

  * "resolved" is set only by the signing code (rklib/decide.py) after the student signed a `comment` record
    with their passphrase; `rk check` fails for a resolved comment without a current signed record
  * AI replies: kind question|howto|note only; a 'question' must end with a question mark; replacement-text
    keys are refused - the AI never supplies rewritten prose
  * comments by people (student/advisor) are created only through the human channels: the evidence notebook
    screen and the terminal import of Word comments; the AI's CLI can only create "agent" comments
  * every comment records the channel it came through (notebook = typed on the
    screen, not signed; tty = imported in the terminal with a signature; agent-cli = the AI's tool), and every
    create / reply / resolve / reopen is appended to review/annotations-log.jsonl. Nothing deletes a comment, so
    a comment in the log that is missing from annotations.json makes `rk check` fail (it was removed by hand or by
    a script); the hooks treat the log as append-only and CI requires it to extend the base branch's version
"""
import json
import os
import re
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from review.anchor import locate, make_selectors, split_selectors  # noqa: E402

CONTEXT_URL = "http://www.w3.org/ns/anno.jsonld"
MAX_COMMENT = 4000
REWRITE_PAT = re.compile(r"(書き換え案|修正案|改善案|こう書く|次のように書|rewrite|replacement|suggested[_ ]text|revised|言い換え案)", re.I)


def load_taxonomy():
    with open(os.path.join(HERE, "taxonomy.json"), encoding="utf-8") as f:
        return json.load(f)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StoreError(ValueError):
    pass


class Store:
    def __init__(self, proj):
        self.proj = proj
        self.path = os.path.join(proj, "review", "annotations.json")
        self.tax = load_taxonomy()
        self.codes = {c["code"] for c in self.tax["codes"]}
        self.humans = set(self.tax["human_actors"])
        self.lock = threading.RLock()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {"@context": CONTEXT_URL, "type": "AnnotationCollection", "items": []}
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise StoreError("annotations.json の形式が不正")
        return data

    def _save(self, data):
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, self.path)

    def _log(self, op, aid, **kw):
        rec = {"op": op, "id": aid, "at": now()}
        rec.update(kw)
        p = os.path.join(os.path.dirname(self.path), "annotations-log.jsonl")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

    def _find(self, data, aid):
        for a in data["items"]:
            if a["id"] == aid:
                return a
        raise KeyError(aid)

    def create(self, doc, text, start, end, code, comment, creator, severity="推奨", channel=None):
        if code not in self.codes:
            raise StoreError("未知のコード: %r" % code)
        if severity not in self.tax["severity"]:
            raise StoreError("重要度は 必須/推奨")
        comment = (comment or "").strip()
        if not comment or len(comment) > MAX_COMMENT:
            raise StoreError("コメントは 1〜%d 文字" % MAX_COMMENT)
        if creator in self.humans:
            if channel not in ("notebook", "tty"):
                raise PermissionError("人間のコメントは証拠ノートの画面か端末の取り込みで作る")
            if creator != "student" and channel != "tty":
                raise PermissionError("指導教員の名義のコメントは、端末の署名つきの取り込み(./rk import-docx)でだけ作る")
            confidence = "確定"
        elif creator == "agent":
            confidence = "要確認"  # a comment from the AI's tool is always 要確認 (unconfirmed)
            if REWRITE_PAT.search(comment):
                raise StoreError("AI のコメントに書き換えの文を入れない。基準と問いだけを書く")
        else:
            raise StoreError("creator は student / advisor / agent")
        sel = make_selectors(text, int(start), int(end))
        anno = {
            "@context": CONTEXT_URL, "id": "urn:uuid:" + str(uuid.uuid4()), "type": "Annotation",
            "motivation": "questioning", "created": now(),
            "creator": {"type": "Software" if creator == "agent" else "Person", "name": creator},
            "target": {"source": doc, "selector": sel},
            "body": [{"type": "TextualBody", "purpose": "classifying", "value": code},
                     {"type": "TextualBody", "purpose": "commenting", "value": comment, "format": "text/plain"}],
            "review": {"code": code, "severity": severity, "confidence": confidence, "status": "open",
                       "channel": "agent-cli" if creator == "agent" else channel,
                       "resolvedBy": None, "resolvedAt": None, "resolvedRecord": None,
                       "anchor": {"state": "exact", "start": int(start), "end": int(end), "score": 1.0},
                       "replies": []},
        }
        with self.lock:
            data = self.load()
            data["items"].append(anno)
            self._save(data)
            self._log("create", anno["id"], creator=creator, channel=anno["review"]["channel"], doc=doc)
        return anno

    def add_reply(self, aid, author, text, kind=None, channel=None):
        text = (text or "").strip()
        if not text or len(text) > MAX_COMMENT:
            raise StoreError("返信は 1〜%d 文字" % MAX_COMMENT)
        if author == "agent":
            if kind not in self.tax["agent_reply_kinds"]:
                raise StoreError("AI の返信の kind は question / howto / note")
            if kind == "question" and not text.rstrip().endswith(("?", "？")):
                raise StoreError("question は問いで終える(？)。答えや書き換えの文は書かない")
            if REWRITE_PAT.search(text):
                raise StoreError("AI の返信に書き換えの文を入れない。問いと確かめ方だけ")
        elif author in self.humans:
            if channel not in ("notebook", "tty"):
                raise PermissionError("人間の返信は証拠ノートの画面で書く")
            kind = "human"
        else:
            raise StoreError("author は student / advisor / agent")
        with self.lock:
            data = self.load()
            a = self._find(data, aid)
            r = {"author": author, "kind": kind, "text": text, "created": now(),
                 "channel": "agent-cli" if author == "agent" else channel}
            a["review"]["replies"].append(r)
            self._save(data)
            self._log("reply", aid, author=author, channel=r["channel"])
        return r

    def set_resolved(self, aid, actor, record_id):
        """Only called by rklib/decide.py after a signed `comment` record was made."""
        with self.lock:
            data = self.load()
            a = self._find(data, aid)
            a["review"].update(status="resolved", resolvedBy=actor, resolvedAt=now(), resolvedRecord=record_id)
            self._save(data)
            self._log("resolve", aid, record=record_id)
        return a

    def reopen(self, aid, actor, channel):
        if actor not in self.humans or channel not in ("notebook", "tty"):
            raise PermissionError("再オープンは人間が画面か端末で行う")
        with self.lock:
            data = self.load()
            a = self._find(data, aid)
            a["review"].update(status="open", resolvedBy=None, resolvedAt=None, resolvedRecord=None)
            self._save(data)
            self._log("reopen", aid, actor=actor, channel=channel)
        return a

    def reanchor(self, doc, text, persist=True):
        with self.lock:
            data = self.load()
            changed = False
            for a in data["items"]:
                if a["target"]["source"] != doc:
                    continue
                res = locate(text, a["target"]["selector"])
                anc = {"state": res["state"], "start": res["start"], "end": res["end"], "score": res["score"],
                       "ambiguous": res["ambiguous"]}
                if a["review"].get("anchor") != anc:
                    a["review"]["anchor"] = anc
                    changed = True
            if changed and persist:
                self._save(data)
            return [a for a in data["items"] if a["target"]["source"] == doc]


def log_problems(proj, lang="ja"):
    """Comments recorded in review/annotations-log.jsonl that are missing from annotations.json."""
    p = os.path.join(proj, "review", "annotations-log.jsonl")
    if not os.path.exists(p):
        return []
    created = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("op") == "create" and r.get("id"):
                created.append(r["id"])
    try:
        items = Store(proj).load()["items"]
    except (StoreError, ValueError, OSError):
        items = []
    have = {a.get("id") for a in items}
    gone = [c for c in created if c not in have]
    if not gone:
        return []
    if lang == "en":
        return ["%d comments recorded in review/annotations-log.jsonl are missing from review/annotations.json "
                "(comments are never deleted by the tools; restore them, e.g. with git, and check who removed them): %s"
                % (len(gone), ", ".join(g[-8:] for g in gone[:5]))]
    return ["review/annotations-log.jsonl に記録されたコメント %d 件が review/annotations.json に無い(道具はコメントを消さない。"
            "git などで戻し、誰が消したかを確かめる): %s" % (len(gone), ", ".join(g[-8:] for g in gone[:5]))]
