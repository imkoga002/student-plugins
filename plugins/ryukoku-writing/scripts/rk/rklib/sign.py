"""Human records: every "a person confirmed this" state, and the two of them that need the passphrase.

Two kinds of record live side by side in .ryukoku/signoffs.jsonl:
- Signed records (the passphrase): only the declarations whose forgery would let unchecked material count as
  checked - VERIFIED for a source or a claim ("I read the original") and the final pre-submission confirmation
  ("the content and the AI-use disclosure are correct"). NEEDS_SIGNATURE lists them.
- Light confirmations (a button on the evidence notebook, or a key at the terminal): every other decision (claim
  cards, resolved comments, approved style rules, proposals, section reading, course policy, opt-out, daily
  summaries, decisions on detected changes). They carry no signature: "sig" is empty and the id is the hash of
  the record. They are protected the way the rest of .ryukoku/ is: the hooks deny AI writes there, the tool-window
  detection reports an unsigned record that appears during an AI tool call, and CI requires the file to extend the
  base branch. A record that claims one of the signed decisions without a valid signature is an error.

- A signer is a person with a passphrase (合言葉). The Ed25519 secret is derived from it with PBKDF2-HMAC-SHA256
  and a per-signer salt, so no private key file exists anywhere. Only the public key, the salt and the
  iteration count are stored, in .ryukoku/signers.json.
- A record binds (kind, subject, decision, content digest, detail, role, key, time, method, note) and carries an
  Ed25519 signature over those fields. Records are appended to .ryukoku/signoffs.jsonl.
- `rk check` accepts a human state only when such a record verifies against a *trusted* signer (trust.py):
  the base branch's signers.json in CI, the per-user trust copy in folder mode. Writing VERIFIED into a CSV by
  any route leaves it unsigned, and the check fails.
- The secret is derived when a batch of decisions is signed and dropped right after; nothing keeps a session
  able to sign, and there is no bulk accept: each item must be shown before it can be chosen.
- The signed payload also covers `detail`; signers can be endorsed by an existing signer (the only way to add one
  without the terminal trust step); the terminal helpers ask only at a real terminal (/dev/tty), a speed bump.
"""
import getpass
import json
import re
import os
import sys

from . import ed25519 as ED
from .common import FileLock, RkError, canonical, now_iso, read_jsonl, sha256_bytes

MIN_PASSPHRASE = 10
DEFAULT_ITER = 600000
MIN_ITER = 100000
ROLES = ("student", "advisor", "peer")
SIGNERS_REL = os.path.join(".ryukoku", "signers.json")
SIGNOFFS_REL = os.path.join(".ryukoku", "signoffs.jsonl")
SIGNED_FIELDS = ("v", "kind", "subject", "decision", "digest", "detail", "role", "key", "signer", "ts", "method", "note")
NEEDS_SIGNATURE = {("source", "VERIFIED"), ("claim", "VERIFIED"), ("presubmit", "ready")}
LIGHT_METHODS = ("tty", "notebook")


def needs_signature(kind, decision):
    """True for the decisions that need the passphrase (VERIFIED and the final pre-submission confirmation)."""
    return (kind, decision) in NEEDS_SIGNATURE


class SignError(RkError):
    pass


# ------------------------------------------------------------------------------------------------ keys
def weak_reason(p):
    """A short reason when the passphrase is easy to guess offline (the public key and salt are in the project, so
    a guess can be checked without the plugin). Not a strength meter: a simple floor."""
    import unicodedata
    q = unicodedata.normalize("NFKC", p or "")
    if len(q) < MIN_PASSPHRASE:
        return "%d 文字以上にする / use at least %d characters" % (MIN_PASSPHRASE, MIN_PASSPHRASE)
    if len(set(q)) < 6:
        return "同じ文字の繰り返しが多い / too few different characters"
    if q.isdigit():
        return "数字だけにしない / not digits only"
    low = q.lower().replace(" ", "")
    for w in ("password", "passphrase", "qwerty", "123456", "abcdef", "ryukoku", "aikotoba", "letmein"):
        if w in low and len(low) - len(w) < 6:
            return "よく使われる語が中心になっている / built around a common word"
    words = [w for w in re.split(r"[\s\-_.,、。]+", q) if w]
    if len(words) < 3 and len(q) < 16:
        return "3 語以上をつなぐか、16 文字以上にする(例: 関係のない 3〜4 語) / use 3+ unrelated words or 16+ characters"
    return ""


def derive_secret(passphrase, salt_hex, iterations):
    import hashlib
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations), 32)


def key_id(pub_hex):
    return sha256_bytes(bytes.fromhex(pub_hex))[:16]


def fingerprint(kid):
    k = (kid or "").upper()
    return "-".join(k[i:i + 4] for i in range(0, 16, 4))


def load_signers_text(text):
    try:
        data = json.loads(text) if text and text.strip() else {"v": 1, "signers": []}
    except ValueError:
        raise SignError("signers.json が JSON として読めない / signers.json is not valid JSON")
    out = {}
    for s in data.get("signers", []) if isinstance(data, dict) else []:
        if isinstance(s, dict) and s.get("key"):
            out[s["key"]] = s
    return out


def load_signers(proj):
    p = os.path.join(proj, SIGNERS_REL)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return load_signers_text(f.read())


def render_signers(signers, project_id=""):
    data = {"v": 1, "project_id": project_id,
            "note": "公開鍵だけ。合言葉と秘密鍵はどこにも保存しない。署名者を足すのは人間が端末で行う(./rk setup)。"
                    " / Public keys only; no passphrase or private key is stored anywhere.",
            "signers": sorted(signers.values(), key=lambda s: (s.get("added", ""), s.get("key", "")))}
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def save_signers(proj, signers, project_id=""):
    from .common import atomic_write
    atomic_write(os.path.join(proj, SIGNERS_REL), render_signers(signers, project_id))


def reg_payload(s):
    return canonical({k: s.get(k) for k in ("key", "name", "role", "pub", "kdf", "added")}).encode("utf-8")


def endorse_payload(s, endorser_key):
    return canonical({"endorse": reg_payload(s).decode("utf-8"), "by": endorser_key}).encode("utf-8")


def self_sig_ok(s):
    try:
        return ED.verify(bytes.fromhex(s["pub"]), reg_payload(s), bytes.fromhex(s.get("self_sig") or ""))
    except (KeyError, ValueError, TypeError):
        return False


def revoke_payload(old_key, successor):
    return canonical({"revoke": old_key, "successor": successor or ""}).encode("utf-8")


def revoke(signers, old_key, old_secret, successor_key=""):
    """Mark OLD_KEY revoked. With the old secret, the revocation names the successor key and is signed by the old
    key (the only endorsement a revoked key keeps)."""
    from .common import now_iso
    s = signers[old_key]
    s["status"] = "revoked"
    s["revoked_at"] = now_iso()
    s["successor"] = successor_key or ""
    s["revoke_sig"] = ED.sign(old_secret, revoke_payload(old_key, successor_key)).hex() if old_secret is not None else ""
    return s


def successor_ok(endorser, key):
    """A revoked key's endorsement counts only for the successor named in its own signed revocation."""
    if endorser.get("successor") != key or not endorser.get("revoke_sig"):
        return False
    try:
        return ED.verify(bytes.fromhex(endorser["pub"]), revoke_payload(endorser["key"], key), bytes.fromhex(endorser["revoke_sig"]))
    except (KeyError, ValueError, TypeError):
        return False


def endorsement_ok(s, trusted, revoked=None):
    """S is endorsed by a trusted signer. An endorsement by a revoked key is invalid whatever its time (the time is
    written by the signer), except for the successor named in that key's own signed revocation. REVOKED: extra
    {key: signer} whose revocation is known from another copy of signers.json (the base branch)."""
    e = trusted.get(s.get("endorsed_by") or "")
    if not e:
        return False
    rev = (revoked or {}).get(e["key"]) or (e if e.get("status") == "revoked" else None)
    if rev is not None and not successor_ok(rev, s.get("key")):
        return False
    try:
        return ED.verify(bytes.fromhex(e["pub"]), endorse_payload(s, e["key"]), bytes.fromhex(s.get("endorse_sig") or ""))
    except (KeyError, ValueError, TypeError):
        return False


def new_signer(name, role, passphrase, iterations=DEFAULT_ITER, salt_hex=None):
    if role not in ROLES:
        raise SignError("role は %s のどれか" % ", ".join(ROLES))
    if len(passphrase) < MIN_PASSPHRASE:
        raise SignError("合言葉は %d 文字以上にする / the passphrase needs at least %d characters" % (MIN_PASSPHRASE, MIN_PASSPHRASE))
    if int(iterations) < MIN_ITER:
        raise SignError("iterations too low")
    salt_hex = salt_hex or os.urandom(16).hex()
    secret = derive_secret(passphrase, salt_hex, iterations)
    pub = ED.public_key(secret).hex()
    s = {"key": key_id(pub), "name": name or role, "role": role, "pub": pub,
         "kdf": {"alg": "pbkdf2-hmac-sha256", "salt": salt_hex, "iter": int(iterations)},
         "added": now_iso(), "status": "active"}
    s["self_sig"] = ED.sign(secret, reg_payload(s)).hex()
    return s, secret


def register(proj, name, role, passphrase, iterations=DEFAULT_ITER, endorser=None, endorser_secret=None, project_id=""):
    """Add a signer to .ryukoku/signers.json. Without an endorsement by an existing trusted signer the new key is
    trusted only after the human trust step (folder mode: ./rk setup writes the per-user trust copy; GitHub: the
    key must reach the base branch). The library never writes the trust copy itself (trust.py does, from the
    terminal), so a script calling register() alone produces an untrusted signer."""
    signers = load_signers(proj)
    s, secret = new_signer(name, role, passphrase, iterations)
    if s["key"] in signers:
        raise SignError("この合言葉の鍵は登録済み: " + fingerprint(s["key"]))
    if endorser is not None and endorser_secret is not None:
        s["endorsed_by"] = endorser["key"]
        s["endorse_sig"] = ED.sign(endorser_secret, endorse_payload(s, endorser["key"])).hex()
    signers[s["key"]] = s
    save_signers(proj, signers, project_id)
    return s, secret


def unlock(signers, passphrase, only=None):
    """Return (signer, secret) for the active signer whose public key the passphrase reproduces."""
    cands = [s for s in signers.values() if s.get("status", "active") == "active" and (only is None or s["key"] in only)]
    seen = set()
    for s in cands:
        kdf = s.get("kdf") or {}
        k = (kdf.get("salt"), kdf.get("iter"))
        if k in seen and len(cands) > 4:
            continue
        seen.add(k)
        try:
            secret = derive_secret(passphrase, kdf["salt"], kdf["iter"])
        except (KeyError, ValueError, TypeError):
            continue
        if ED.public_key(secret).hex() == s.get("pub"):
            return s, secret
    raise SignError("合言葉が登録済みのどの署名者とも一致しない(何も署名していない) / the passphrase matches no registered signer (nothing signed)")


# ------------------------------------------------------------------------------------------------ records
def payload(rec):
    return canonical({k: rec.get(k) for k in SIGNED_FIELDS}).encode("utf-8")


def make_record(signer, secret, kind, subject, decision, digest, detail=None, method="tty", note=""):
    rec = {"v": 1, "kind": kind, "subject": subject, "decision": decision, "digest": digest,
           "detail": detail or {}, "role": signer.get("role", "student"), "key": signer["key"],
           "signer": signer.get("name", ""), "ts": now_iso(), "method": method, "note": (note or "")[:1000]}
    sig = ED.sign(secret, payload(rec))
    rec["sig"] = sig.hex()
    rec["id"] = "SO-" + sha256_bytes(sig)[:16]
    return rec


def make_confirmation(kind, subject, decision, digest, detail=None, method="tty", note="", name="student", role="student"):
    """A light confirmation (no passphrase): the record is bound to the content digest like a signed one, but its
    integrity rests on the hooks, the tool-window detection and CI, not on a signature."""
    if needs_signature(kind, decision):
        raise SignError("%s %s には合言葉の署名が要る / %s %s needs the passphrase signature" % (kind, decision, kind, decision))
    rec = {"v": 2, "kind": kind, "subject": subject, "decision": decision, "digest": digest, "detail": detail or {},
           "role": role, "key": "", "signer": name or "student", "ts": now_iso(), "method": method, "note": (note or "")[:1000]}
    rec["sig"] = ""
    rec["id"] = "CF-" + sha256_bytes(payload(rec))[:16]
    return rec


def is_light(rec):
    return not rec.get("sig")


def verify_record(rec, signers):
    """(ok, reason). SIGNERS must be the *trusted* set (trust.py). A light confirmation is accepted for every
    decision except the signed ones, when its id matches its content."""
    if is_light(rec):
        if needs_signature(rec.get("kind"), rec.get("decision")):
            return False, "この判断(%s %s)には合言葉の署名が要るのに、署名がない / needs a passphrase signature" % (rec.get("kind"), rec.get("decision"))
        if rec.get("method") not in LIGHT_METHODS:
            return False, "確認の経路 %r が不明 / unknown method" % rec.get("method")
        if rec.get("id") != "CF-" + sha256_bytes(payload(rec))[:16]:
            return False, "確認の記録の id が内容と合わない(書き換えの可能性) / record id does not match its content"
        return True, ""
    s = signers.get(rec.get("key"))
    if not s:
        return False, "unknown signer key %s(信頼された署名者でない)" % rec.get("key")
    if s.get("status") == "revoked" and (rec.get("ts") or "") >= (s.get("revoked_at") or ""):
        return False, "signer key revoked"
    try:
        ok = ED.verify(bytes.fromhex(s["pub"]), payload(rec), bytes.fromhex(rec.get("sig") or ""))
    except (ValueError, TypeError, KeyError):
        ok = False
    if ok and rec.get("id") != "SO-" + sha256_bytes(bytes.fromhex(rec["sig"]))[:16]:
        return False, "record id does not match the signature"
    return (True, "") if ok else (False, "bad signature(署名が合わない)")


def read_signoffs(proj):
    return read_jsonl(os.path.join(proj, SIGNOFFS_REL))


def append_signoffs(proj, recs):
    if not recs:
        return
    p = os.path.join(proj, SIGNOFFS_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with FileLock(p + ".lock"):
        with open(p, "a", encoding="utf-8", newline="") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def valid_index(proj, trusted):
    """{(kind, subject): [valid records, oldest first]} and a list of problems for records that do not verify."""
    idx, probs = {}, []
    try:
        recs = read_signoffs(proj)
    except RkError as e:
        return idx, [str(e)]
    for r in recs:
        ok, why = verify_record(r, trusted)
        if not ok:
            probs.append("署名記録 %s(%s %s)を検証できない: %s" % (r.get("id"), r.get("kind"), r.get("subject"), why))
            continue
        idx.setdefault((r["kind"], r["subject"]), []).append(r)
    return idx, probs


def latest(idx, kind, subject):
    lst = idx.get((kind, subject)) or []
    return lst[-1] if lst else None


def current(idx, kind, subject, digest, decisions=None):
    """The latest valid record for SUBJECT, if it was made for DIGEST (and, optionally, one of DECISIONS)."""
    r = latest(idx, kind, subject)
    if r and r.get("digest") == digest and (decisions is None or r.get("decision") in decisions):
        return r
    return None


# ------------------------------------------------------------------------------------------------ terminal
def tty_available():
    if os.name == "nt":
        return sys.stdin.isatty()
    try:
        fd = os.open("/dev/tty", os.O_RDWR | getattr(os, "O_NOCTTY", 0))
        os.close(fd)
        return True
    except OSError:
        return False


def require_tty(lang="ja"):
    if not tty_available():
        raise SignError(
            "このコマンドは人間が自分の端末(ターミナル)で実行するもの。AI のツール呼び出しや、入力をパイプで流し込む実行では動かない。"
            "ターミナルを開いて同じコマンドを打つこと。" if lang != "en" else
            "This command is for a person at their own terminal. It does not run from an AI tool call or with piped input."
            " Open a terminal and type the same command.")


def tty_print(msg=""):
    if os.name == "nt":
        print(msg, flush=True)
        return
    with open("/dev/tty", "w", encoding="utf-8", errors="replace") as t:
        t.write(msg + "\n")


def tty_input(prompt):
    if os.name == "nt":
        return input(prompt)
    with open("/dev/tty", "w", encoding="utf-8", errors="replace") as out:
        out.write(prompt)
        out.flush()
    with open("/dev/tty", "r", encoding="utf-8", errors="replace") as inp:
        return inp.readline().rstrip("\r\n")


def read_passphrase(prompt):
    require_tty()
    return getpass.getpass(prompt)


def tty_key(prompt, allowed):
    while True:
        k = tty_input(prompt).strip().lower()[:1]
        if k and k in allowed:
            return k
