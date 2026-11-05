"""Which signer keys are trusted (the trust root of every human state).

GitHub / CI (`rk check --ci --base-ref origin/<base>`):
  the root is the signer(s) in the FIRST version of .ryukoku/signers.json on the base branch (the commit that
  `./rk setup` makes from the student's terminal). Every later signer - on the base branch or added in the PR -
  is trusted only if an already trusted signer endorsed it (a signature made with that person's passphrase);
  otherwise it is an error and its records fail as "unknown signer key" (so a signer pushed to
  main by a script is not trusted). The working tree's signers are never roots.
Folder mode (no Git, or a local check):
  the per-user trust copy ~/.ryukoku-writing/trust/<project_id>.json, written only by `./rk setup` / `./rk trust`
  in the student's terminal, compared with .ryukoku/signers.json. A signer in the project that is neither in
  the trust copy nor endorsed by a trusted signer is an error ("未承認の署名者の追加"). `rk check` and the
  HANDOFF file print the number of signers, their fingerprints and registration dates every time, so an
  advisor can compare them with the fingerprint noted at the first meeting.
Limits: a program with the student's own permissions can write the trust copy too. The hooks deny writes to
it, the change detection (msguard) watches it, and the GitHub mode does not depend on it.
"""
import json
import os
import subprocess

from . import sign
from .common import atomic_write, load_config, now_iso, project_id, tr, trust_path

TRUST_FIELDS = ("key", "pub", "name", "role", "added", "root")


def git(proj, *args):
    from .common import run_git
    r = run_git(proj, list(args), timeout=30)
    return r.stdout if (r is not None and r.returncode == 0) else None


def read_trust_copy(proj):
    p = trust_path(proj)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return {s["key"]: s for s in data.get("signers", []) if isinstance(s, dict) and s.get("key")}


def write_trust_copy(proj, signers, roots=None):
    """Called only from the human terminal steps (setup, trust). ROOTS: the keys the person confirmed directly
    (the first registration, or fingerprints compared in ./rk trust); other signers must be endorsed."""
    roots = set(roots if roots is not None else [k for k, s in signers.items() if s.get("root")])
    data = {"v": 2, "project_id": project_id(proj), "project_path": os.path.realpath(proj), "updated": now_iso(),
            "signers": [dict({k: s.get(k) for k in TRUST_FIELDS}, root=s["key"] in roots)
                        for s in sorted(signers.values(), key=lambda x: x.get("added", ""))]}
    atomic_write(trust_path(proj), json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _close_over_endorsements(trusted, candidates, revoked=None):
    """Add every candidate endorsed by an already trusted key. An endorsement by a revoked key counts only for the
    successor its signed revocation names; REVOKED adds revocations known from another copy (the base)."""
    rev = dict(revoked or {})
    for k, s in candidates.items():
        if s.get("status") == "revoked":
            rev.setdefault(k, s)
    changed = True
    while changed:
        changed = False
        for k, s in candidates.items():
            if k not in trusted and sign.self_sig_ok(s) and sign.endorsement_ok(s, trusted, rev):
                trusted[k] = s
                changed = True
    return trusted


def describe(signers, lang="ja"):
    if not signers:
        return tr(lang, "署名者なし", "no signers")
    return tr(lang, "署名者 %d 名: %s", "%d signer(s): %s") % (len(signers), "; ".join(
        "%s %s(%s, %s %s%s)" % (sign.fingerprint(s["key"]), s.get("name", ""), s.get("role", ""), tr(lang, "登録", "added"), (s.get("added") or "")[:10],
                                tr(lang, "、%s が承認", ", endorsed by %s") % sign.fingerprint(s["endorsed_by"]) if s.get("endorsed_by") else "")
        for s in sorted(signers.values(), key=lambda x: x.get("added", ""))))


def local_trusted(proj, lang="ja"):
    """(trusted signers, problems, notes) for folder mode / local checks."""
    head = sign.load_signers(proj)
    probs, notes = [], []
    tc = read_trust_copy(proj)
    if tc is None:
        if head:
            probs.append(tr(lang, "この PC に信頼の起点(%s)がない。別の PC で作業しているなら、自分の端末で ./rk trust を実行し、"
                            "表示される指紋を最初に控えた指紋と照らしてから登録する。照らせない署名者は信頼しない",
                            "No trust record on this computer (%s). If you work on another computer, run ./rk trust in your terminal and compare "
                            "the fingerprints with the ones you noted; signers you cannot match are not trusted") % trust_path(proj))
        return {}, probs, notes
    trusted = {}
    legacy = not any("root" in t for t in tc.values())  # trust copies written before v2: every entry is a root
    for k, t in tc.items():
        s = head.get(k)
        if s is None:
            probs.append(tr(lang, "信頼の起点にある署名者 %s が .ryukoku/signers.json から消えている", "trusted signer %s is missing from .ryukoku/signers.json") % sign.fingerprint(k))
            continue
        if s.get("pub") != t.get("pub") or not sign.self_sig_ok(s):
            probs.append(tr(lang, "署名者 %s の公開鍵が信頼の起点と違う(書き換えの可能性)", "signer %s: the public key differs from the trust record (possibly rewritten)") % sign.fingerprint(k))
            continue
        if legacy or t.get("root"):
            trusted[k] = s
    _close_over_endorsements(trusted, head)
    for k, s in head.items():
        if k not in trusted:
            probs.append(tr(lang, "未承認の署名者の追加: %s(%s、登録 %s)。既存の署名者の承認(endorse)も信頼の起点への登録もない。"
                            "本人の操作なら端末で ./rk trust、心当たりがなければ消して原因を調べる",
                            "unapproved signer added: %s (%s, added %s); neither endorsed by a trusted signer nor in the trust record. "
                            "If you added it, run ./rk trust in your terminal; otherwise remove it and investigate")
                         % (sign.fingerprint(k), s.get("name", ""), (s.get("added") or "")[:10]))
    notes.append(describe(trusted, lang))
    return trusted, probs, notes


def ci_trusted(proj, base_ref, lang="ja"):
    """(trusted signers, problems, notes) for CI: the base branch is the trust root.
    1. the base branch's history must have exactly ONE root commit (a merge of an unrelated history - for example
       an orphan commit dated in the past - is an error);
    2. the root signers are those of the first version of .ryukoku/signers.json on the first-parent chain from that
       root, plus new roots recorded in .ryukoku/root-changes.jsonl on the base branch (a forgotten passphrase;
       printed at the top so the advisor compares the fingerprint);
    3. every other key, on the base branch or added in the PR (also through a merge), must be endorsed through that
       chain; an endorsement by a revoked key counts only for its signed successor."""
    probs, notes = [], []
    roots_c = (git(proj, "rev-list", "--max-parents=0", base_ref) or "").split()
    if len(roots_c) != 1:
        probs.append(tr(lang, "基準ブランチ %s の履歴に根の commit が %d 個ある(関係のない履歴が合流した)。信頼の起点を決められないので、"
                        "どの署名も信頼しない。心当たりがなければ指導教員と確かめる",
                        "The base branch %s has %d root commits (an unrelated history was merged in); the trust root cannot be "
                        "determined, so no signature is trusted. Check with your advisor") % (base_ref, len(roots_c)))
        return {}, probs, notes
    txt = git(proj, "show", "%s:.ryukoku/signers.json" % base_ref)
    if txt is None:
        probs.append(tr(lang, "基準ブランチ %s に .ryukoku/signers.json がない。作業ツリーの署名者は信頼しない(初回の PR でも)。"
                        "./rk setup で main に署名者を commit してから PR を作る",
                        "The base branch %s has no .ryukoku/signers.json. Signers in the working tree are not trusted (not even on the first PR); "
                        "commit the signers on main with ./rk setup before opening a PR") % base_ref)
        return {}, probs, notes
    base = sign.load_signers_text(txt)
    head = sign.load_signers(proj)
    roots = _first_signers(proj, base_ref) or set()
    changes = _root_changes(proj, base_ref, base)
    if len(roots) > 1:
        # the first signers.json must hold exactly one signer (./rk setup registers one). More than one means the
        # history was rewritten so an extra key rides in as a root: trust nothing as a root.
        probs.append(tr(lang, "!! 信頼の起点の署名者が %d 人いる(最初の signers.json には 1 人のはず)。履歴が書き換えられた可能性があるので、"
                        "どれも起点として信頼しない。指紋 %s を指導教員と確かめる",
                        "!! the trust root has %d signers (the first signers.json should hold one); the history may have been "
                        "rewritten, so none is trusted as a root. Check the fingerprints %s with your advisor")
                     % (len(roots), ", ".join(sign.fingerprint(k) for k in sorted(roots))))
        roots = set()
    trusted = {}
    for k in sorted(roots | set(changes)):
        s = base.get(k)
        if s and sign.self_sig_ok(s):
            trusted[k] = s
    notes.append(tr(lang, "【信頼の起点】main の最初の signers.json: %s。指導教員は、初回の面談で控えた指紋と照らす",
                    "[trust root] first signers.json on main: %s. The advisor compares it with the fingerprint noted at the first meeting")
                 % (", ".join(sign.fingerprint(k) for k in sorted(roots)) or "-"))
    for k, c in changes.items():
        notes.append(tr(lang, "【信頼の起点】!! 起点が変わった(%s、理由 %s): 新しい指紋 %s。指導教員は学生と会って指紋を照らす",
                        "[trust root] !! the root changed (%s, reason %s): new fingerprint %s. The advisor checks it with the student in person")
                     % ((c.get("at") or "")[:10], c.get("reason"), sign.fingerprint(k)))
    for k, s in base.items():
        h = head.get(k)
        if h is None or h.get("pub") != s.get("pub"):
            probs.append(tr(lang, "基準ブランチの署名者 %s が、この変更で消えたか書き換えられた", "base-branch signer %s was removed or rewritten in this change") % sign.fingerprint(k))
    base_revoked = {k: s for k, s in base.items() if s.get("status") == "revoked"}
    _close_over_endorsements(trusted, base, base_revoked)
    for k, s in base.items():
        if k not in trusted:
            probs.append(tr(lang, "基準ブランチの署名者 %s(%s、登録 %s)は、最初の署名者からの承認(endorse)でつながっていない。その鍵の署名は信頼しない"
                            "(スクリプトが main に足した可能性。心当たりがなければ指導教員と確かめる)",
                            "base-branch signer %s (%s, added %s) is not endorsed through the first signer; its signatures are not trusted "
                            "(a script may have added it to main)") % (sign.fingerprint(k), s.get("name", ""), (s.get("added") or "")[:10]))
    before = set(trusted)
    _close_over_endorsements(trusted, head, base_revoked)
    added = sorted(set(head) - set(base))
    for k in added:
        if k in trusted and k not in before:
            notes.append(tr(lang, "この変更で追加された署名者 %s は、既存の署名者 %s が承認している", "signer %s added in this change is endorsed by %s")
                         % (sign.fingerprint(k), sign.fingerprint(head[k].get("endorsed_by"))))
        else:
            probs.append(tr(lang, "この変更で追加された署名者 %s は承認されていない。その鍵の署名は信頼しない(unknown signer key)",
                            "signer %s added in this change is not endorsed; its signatures are not trusted (unknown signer key)") % sign.fingerprint(k))
    notes.append(describe(trusted, lang))
    return trusted, probs, notes


def _root_changes(proj, base_ref, base):
    """{new root key: record} from .ryukoku/root-changes.jsonl on the base branch (each signed by the new key)."""
    out = {}
    txt = git(proj, "show", "%s:.ryukoku/root-changes.jsonl" % base_ref) or ""
    for line in txt.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        k = r.get("new_key")
        s = base.get(k or "")
        if k and s and sign.self_sig_ok(s) and s.get("pub") == r.get("pub"):
            out[k] = r
    return out


def _first_signers(proj, base_ref):
    """Keys of the first version of .ryukoku/signers.json on the first-parent chain of BASE_REF, walking from its
    single root (commit dates are not used: they can be set to anything)."""
    chain = (git(proj, "rev-list", "--first-parent", "--reverse", base_ref) or "").split()
    for c in chain:
        txt = git(proj, "show", "%s:.ryukoku/signers.json" % c)
        if txt:
            return set(sign.load_signers_text(txt))
    return None


def trusted_signers(proj, ci=False, base_ref=None, lang="ja"):
    if ci and base_ref:
        return ci_trusted(proj, base_ref, lang)
    return local_trusted(proj, lang)


def git_mode(proj):
    m = (load_config(proj).get("git_mode") or "auto").strip()
    if m == "auto":
        return "git" if os.path.isdir(os.path.join(proj, ".git")) else "nogit"
    return m
