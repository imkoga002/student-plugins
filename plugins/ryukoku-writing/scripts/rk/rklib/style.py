"""Style specification: proposed rules, human approval, lint, mechanical fix proposals.

Files
  proposals/style-rules.yml  rules extracted by the AI (or copied from the defaults). status: proposed.
                             The AI may write here (it is a proposal, like proposals/*.diff).
  .ryukoku/style.yml         approved rules only. Written when the student signs an approval (screen or
                             `./rk style`); the AI cannot write .ryukoku/ at all (hooks).
A rule in style.yml is applied only when a valid signed `rule` record (trusted signer, decision approved,
digest = the rule's fields) backs it; otherwise it is reported and not applied.
The parser reads a limited YAML (no PyYAML).

Rule fields: id, kind, value, lang (ja|en|any), source (資料名・URL), page (頁・節), quote (該当箇所の要約),
confidence (high|medium|low), status, note, approved_record.
Machine-checked kinds: punctuation, forbidden_word, ending_style, number_width, max_chars, min_chars.
Recorded-only kinds (checked by the student/reviewer): heading_numbering, caption_position, citation_style,
note_style, paper, font, other.
"""
import os
import re
import unicodedata

from .common import RkError, subject_hash

CHECKED = ("punctuation", "forbidden_word", "ending_style", "number_width", "max_chars", "min_chars")
RECORDED = ("heading_numbering", "caption_position", "citation_style", "note_style", "paper", "font", "other")
FIELDS = ("id", "kind", "value", "lang", "source", "page", "quote", "confidence", "status", "note", "approved_record")


def _unq(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\") if v[0] == '"' else inner
    return re.sub(r"\s+#.*$", "", v)


def parse_style(text):
    top, rules, cur, in_rules = {}, [], None, False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = re.match(r"^(\s*)-\s+([A-Za-z_]+)\s*:\s*(.*)$", raw)
        if in_rules and m:
            cur = {m.group(2): _unq(m.group(3))}
            rules.append(cur)
            continue
        m = re.match(r"^(\s*)([A-Za-z_]+)\s*:\s*(.*)$", raw)
        if not m:
            continue
        indent, k, v = len(m.group(1)), m.group(2), _unq(m.group(3))
        if indent == 0:
            if k == "rules":
                in_rules = True
                if v.strip() in ("[]",):
                    pass
            else:
                top[k] = v
        elif cur is not None:
            cur[k] = v
    return top, rules


def load(path):
    if not os.path.exists(path):
        return {}, []
    with open(path, encoding="utf-8") as f:
        return parse_style(f.read())


def rule_subject(rule):
    return subject_hash({k: rule.get(k, "") for k in FIELDS if k not in ("status", "approved_record")})


def _q(v):
    return '"%s"' % str(v).replace("\\", "\\\\").replace('"', '\\"')


def render_rule(rule):
    out = ["  - id: %s" % _q(rule["id"])]
    for k in FIELDS[1:]:
        if rule.get(k) not in (None, ""):
            out.append("    %s: %s" % (k, _q(rule[k])))
    return "\n".join(out) + "\n"


def validate_proposed(rules):
    probs = []
    seen = set()
    for r in rules:
        rid = r.get("id", "?")
        if rid in seen:
            probs.append("%s: id が重複" % rid)
        seen.add(rid)
        if r.get("kind") not in CHECKED + RECORDED:
            probs.append("%s: kind が不明 (%s)" % (rid, r.get("kind")))
        if not r.get("source", "").strip():
            probs.append("%s: source(根拠の資料名・URL)が空。根拠のない規則は提案しない" % rid)
        if r.get("confidence") not in ("high", "medium", "low"):
            probs.append("%s: confidence は high|medium|low" % rid)
        if r.get("status", "proposed") != "proposed":
            probs.append("%s: 提案ファイルの status は proposed だけ(承認は学生が証拠ノートか ./rk style で行う)" % rid)
        if r.get("kind") == "punctuation" and len(r.get("value", "")) != 2:
            probs.append("%s: punctuation の value は2文字(読点と句点。例: 、。 / ，。 / ，．)" % rid)
    return probs


PROPOSED_REL = os.path.join("proposals", "style-rules.yml")
APPROVED_REL = os.path.join(".ryukoku", "style.yml")


def proposed_path(proj):
    return os.path.join(proj, PROPOSED_REL)


def approved_path(proj):
    return os.path.join(proj, APPROVED_REL)


def approved_rules(proj, idx, lang, fb="ja"):
    """Rules from style.yml backed by a valid signed approval; returns (rules, problems). IDX: sign.valid_index."""
    from . import sign
    _top, rules = load(approved_path(proj))
    ok, probs = [], []
    for r in rules:
        if not sign.current(idx, "rule", r.get("id", ""), rule_subject(r), ("approved",)):
            probs.append(("style rule %s: no approval recorded by the student, or changed after approval (not applied)" if fb == "en" else
                          "記法規則 %s: 学生の承認の記録がない、または承認の後に内容が変わった(適用しない)") % r.get("id"))
            continue
        if r.get("lang", "any") not in ("any", "", lang):
            continue
        ok.append(r)
    return ok, probs


def _text_lines(text):
    """Yield (line_no, line) for prose lines (skip code fences, front matter, headings, tables, quotes)."""
    in_code = in_fm = in_cm = False
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if in_cm:
            if "-->" in s:
                in_cm = False
            continue
        if s.startswith("<!--") and "-->" not in s:
            in_cm = True
            continue
        if n == 1 and s == "---":
            in_fm = True
            continue
        if in_fm:
            if s in ("---", "..."):
                in_fm = False
            continue
        if s.startswith("```") or s.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code or s.startswith(("#", "|", ">", "<!--", "$$")) or not s:
            continue
        yield n, line


def body_chars(text):
    n = 0
    for _, line in _text_lines(text):
        n += len(re.sub(r"\s", "", line))
    return n


def lint(text, rules, path="manuscript"):
    findings = []
    for rule in rules:
        kind, val = rule.get("kind"), rule.get("value", "")
        if kind == "max_chars" or kind == "min_chars":
            continue
        for n, line in _text_lines(text):
            if kind == "punctuation" and len(val) == 2:
                for chars, label, want in (("、，,", "読点", val[0]), ("。．", "句点", val[1])):
                    wrong = [c for c in chars if c != want and c in line and not (c == "," and re.search(r"\d,\d", line))]
                    wrong = [c for c in wrong if c != ","]
                    if wrong:
                        findings.append((path, n, rule["id"], "%sは「%s」の規則だが「%s」がある" % (label, want, wrong[0])))
            elif kind == "forbidden_word" and val and val in line:
                findings.append((path, n, rule["id"], "使わない表現「%s」(%s)" % (val, rule.get("note") or rule.get("source", ""))))
            elif kind == "ending_style" and val == "である" and re.search(r"(です|ます)[。．]", line):
                findings.append((path, n, rule["id"], "である調の規則だが「です・ます」で終わる文がある"))
            elif kind == "ending_style" and val in ("です・ます", "ですます") and re.search(r"(である|だ)[。．]", line):
                findings.append((path, n, rule["id"], "です・ます調の規則だが「である・だ」で終わる文がある"))
            elif kind == "number_width" and val == "half" and re.search(r"[０-９]", line):
                findings.append((path, n, rule["id"], "数字は半角の規則だが全角数字がある"))
            elif kind == "number_width" and val == "full" and re.search(r"(?<![A-Za-z0-9.])[0-9]+(?![A-Za-z0-9.])", line):
                findings.append((path, n, rule["id"], "数字は全角の規則だが半角数字がある"))
    return findings


def length_report(texts, rules):
    total = sum(body_chars(t) for t in texts)
    out = []
    for rule in rules:
        if rule.get("kind") in ("max_chars", "min_chars"):
            try:
                lim = int(re.sub(r"[^\d]", "", rule.get("value", "")))
            except ValueError:
                continue
            bad = total > lim if rule["kind"] == "max_chars" else total < lim
            out.append((rule["id"], rule["kind"], lim, total, bad))
    return total, out


# ---------------------------------------------------------------- mechanical fixes (become proposals)
def fix_text(text, rules):
    """Return (new_text, rule_ids_used). Only punctuation and number width, only on prose lines."""
    lines = text.split("\n")
    prose = {n - 1 for n, _ in _text_lines(text)}
    used = set()
    for rule in rules:
        kind, val = rule.get("kind"), rule.get("value", "")
        for i in sorted(prose):
            ln = lines[i]
            new = ln
            if kind == "punctuation" and len(val) == 2:
                # never a point or a separator between digits (10．5 is a number, not a sentence end)
                new = re.sub(r"(?<![0-9０-９])[、，](?![0-9０-９])|(?<=[0-9０-９])[、，](?![0-9０-９])|(?<![0-9０-９])[、，](?=[0-9０-９])",
                             lambda m: val[0], new)
                new = re.sub(r"(?<![0-9０-９])[。．](?![0-9０-９])|(?<=[0-9０-９])[。．](?![0-9０-９])|(?<![0-9０-９])[。．](?=[0-9０-９])",
                             lambda m: val[1], new)
            elif kind == "number_width" and val == "half":
                new = re.sub(r"[０-９]", lambda m: unicodedata.normalize("NFKC", m.group(0)), new)
                new = re.sub(r"(?<=[0-9])[．，](?=[0-9])", lambda m: unicodedata.normalize("NFKC", m.group(0)), new)
            if new != ln:
                lines[i] = new
                used.add(rule["id"])
    return "\n".join(lines), sorted(used)


MERMAID_PIN = ["---", "config:", "  theme: default", "  look: classic", "  layout: dagre", "---"]


def pin_mermaid(text):
    """Insert the front-matter pin into ```mermaid blocks that lack it (Mermaid 12 changed the flowchart
    defaults: Mermaid, Flowchart syntax, "Default theme, look and layout (v12.0.0+)",
    https://mermaid.js.org/syntax/flowchart.html; pin theme, look and layout)."""
    lines = text.split("\n")
    out, i, changed = [], 0, 0
    while i < len(lines):
        ln = lines[i]
        out.append(ln)
        if re.match(r"^\s*```+\s*\{?\.?mermaid", ln.strip()):
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if nxt != "---":
                out += MERMAID_PIN
                changed += 1
        i += 1
    return "\n".join(out), changed


def rules_from_files(proj, lang, valid):
    rules, probs = approved_rules(proj, valid, lang)
    return rules, probs


def find_rule(rules, rid):
    for r in rules:
        if r.get("id") == rid:
            return r
    raise RkError("規則 %s がない" % rid)
