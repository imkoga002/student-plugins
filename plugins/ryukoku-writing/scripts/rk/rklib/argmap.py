#!/usr/bin/env python3
"""argmap.py - render a student's own argument (Toulmin) as Mermaid and list missing links as QUESTIONS. The Mermaid
front matter pins theme/look/layout, because Mermaid 12 changed the flowchart defaults (Mermaid, Flowchart syntax,
"Default theme, look and layout (v12.0.0+)", https://mermaid.js.org/syntax/flowchart.html).

Input JSON (written by the student, or extracted from the student's text with verbatim quotes):
{
  "title": "...",
  "arguments": [
    {"id": "A1", "claim": {"text": "...", "quote": "..."},
     "data": [{"id": "D1", "text": "...", "quote": "..."}],
     "warrant": {"text": "...", "quote": "..."} | null,
     "backing": {"text": "...", "quote": "..."} | null,
     "qualifier": {"text": "...", "quote": "..."} | null,
     "rebuttal": {"text": "...", "quote": "..."} | null}
  ]
}
"quote" must be a verbatim span of the student's manuscript (checked with --manuscript), so that the
extractor cannot invent content. This tool never generates a warrant, claim or sentence: a missing
element is drawn as a dashed "(未記載)" node plus a fixed question naming the criterion.
Terms: 根拠 = data, 論拠 = warrant (fixed).
Standard library only.
"""
import argparse, json, re, sys

STRONG = re.compile(r"必ず|すべて|全て|明らかに|証明|絶対|常に|間違いなく|always|all |never|proves?|clearly|undoubtedly", re.I)

QUESTIONS = {
    "G1": ("根拠(data)が示されていない", "この主張を支えるデータや文献は、本文のどこにありますか? それだけでこの強さの結論に足りますか?"),
    "W1": ("論拠(warrant)が書かれていない [W1 論理の飛躍]", "根拠から主張へ進むには、どんな一般的な前提が必要ですか? それは本文に書かれていますか?"),
    "W2": ("論拠の裏づけ(backing)がない [W2]", "その前提は、どの理論・先行研究に支えられていますか? この文脈にも当てはまりますか?"),
    "C2": ("限定(qualifier)がなく、強い語がある [C2]", "この結論は、どの範囲・どの程度の確からしさで言えますか? 例外となる条件はありますか?"),
    "R1": ("反論・対抗仮説(rebuttal)が書かれていない [R1]", "この説明に対する最も強い対抗仮説は何ですか? それを退ける根拠は本文にありますか?"),
}

def esc(s):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    s = s.replace('"', "'").replace("<", "‹").replace(">", "›").replace("[", "(").replace("]", ")")
    return s if len(s) <= 60 else s[:57] + "..."

def present(x):
    return isinstance(x, dict) and str(x.get("text", "")).strip() != ""

def check_quotes(doc, manuscript):
    bad = []
    norm = re.sub(r"\s+", "", manuscript)
    for a in doc.get("arguments", []):
        items = [("claim", a.get("claim"))] + [("data", d) for d in a.get("data", [])]
        for k in ("warrant", "backing", "qualifier", "rebuttal"):
            items.append((k, a.get(k)))
        for kind, it in items:
            if present(it):
                q = str(it.get("quote", "")).strip()
                if not q:
                    bad.append((a.get("id"), kind, "quote が空(学生の原文からの引用が必要)"))
                elif re.sub(r"\s+", "", q) not in norm:
                    bad.append((a.get("id"), kind, "quote が原稿に見つからない(言い換え・創作の疑い): " + q[:40]))
    return bad

def analyse(doc):
    gaps = []
    for a in doc.get("arguments", []):
        aid = a.get("id", "A?")
        c = a.get("claim")
        if not present(c):
            gaps.append((aid, "C1", "主張が特定できない [C1]", "この段落で読者に受け入れてほしい一文はどれですか?"))
            continue
        data = [d for d in a.get("data", []) if present(d)]
        if not data: gaps.append((aid,) + ("G1",) + QUESTIONS["G1"])
        if not present(a.get("warrant")): gaps.append((aid,) + ("W1",) + QUESTIONS["W1"])
        elif not present(a.get("backing")): gaps.append((aid,) + ("W2",) + QUESTIONS["W2"])
        if not present(a.get("qualifier")) and STRONG.search(c.get("text", "") + " " + c.get("quote", "")):
            gaps.append((aid,) + ("C2",) + QUESTIONS["C2"])
        if not present(a.get("rebuttal")): gaps.append((aid,) + ("R1",) + QUESTIONS["R1"])
    return gaps

def mermaid(doc, gaps):
    L = ["```mermaid", "---", "config:", "  theme: default", "  look: classic", "  layout: dagre", "---", "flowchart LR"]
    gapset = {(g[0], g[1]) for g in gaps}
    for a in doc.get("arguments", []):
        i = re.sub(r"\W", "", a.get("id", "A")) or "A"
        c = a.get("claim")
        L.append(f'  subgraph {i}["{esc(a.get("id"))}"]')
        L.append("    direction LR")
        L.append(f'    {i}C(["主張 claim: {esc(c.get("text")) if present(c) else "(未記載)"}"])')
        ds = [d for d in a.get("data", []) if present(d)]
        if ds:
            for n, d in enumerate(ds):
                L.append(f'    {i}D{n}["根拠 data: {esc(d["text"])}"]')
                L.append(f"    {i}D{n} --> {i}W")
        else:
            L.append(f'    {i}D0["根拠 data: (未記載)"]:::missing')
            L.append(f"    {i}D0 -.-> {i}W")
        w = a.get("warrant")
        L.append(f'    {i}W["論拠 warrant: {esc(w["text"])}"]' if present(w) else f'    {i}W["論拠 warrant: (未記載)"]:::missing')
        L.append(f"    {i}W --> {i}C")
        b = a.get("backing")
        if present(b): L.append(f'    {i}B["裏づけ backing: {esc(b["text"])}"] --> {i}W')
        elif present(w): L.append(f'    {i}B["裏づけ backing: (未記載)"]:::missing -.-> {i}W')
        q = a.get("qualifier")
        if present(q): L.append(f'    {i}Q["限定 qualifier: {esc(q["text"])}"] --> {i}C')
        elif (a.get("id"), "C2") in gapset: L.append(f'    {i}Q["限定 qualifier: (未記載)"]:::missing -.-> {i}C')
        r = a.get("rebuttal")
        L.append(f'    {i}R["反論 rebuttal: {esc(r["text"])}"] --> {i}C' if present(r) else f'    {i}R["反論 rebuttal: (未記載)"]:::missing -.-> {i}C')
        L.append("  end")
    L.append("  classDef missing stroke-dasharray: 5 5,stroke:#c0392b,color:#c0392b;")
    L.append("```")
    return "\n".join(L)

def render(doc, gaps, bad):
    out = [f"# 論証図: {doc.get('title','(無題)')}", "",
           "この図は学生自身の文から取り出した構造である。点線の赤は『本文に書かれていない』要素で、補うのは学生。", "",
           mermaid(doc, gaps), "", "## 欠けている接続と問い(答えは学生が書く)", ""]
    if not gaps: out.append("- 検出された欠けはない(内容の妥当性は別に査読する)")
    for aid, code, crit, q in gaps:
        out.append(f"- {aid} / {code} / 観点: {crit}\n  - 問い: {q}")
    if bad:
        out += ["", "## 引用の不一致(抽出の誤りの疑い)", ""]
        out += [f"- {a} / {k}: {m}" for a, k, m in bad]
    return "\n".join(out) + "\n"

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("input", help="argument JSON")
    ap.add_argument("--manuscript", help="check that every quote is verbatim in this file")
    ap.add_argument("--out", help="write markdown here (default: stdout)")
    ap.add_argument("--json", action="store_true", help="print gaps as JSON")
    a = ap.parse_args(argv)
    try:
        doc = json.load(open(a.input, encoding="utf-8"))
    except Exception as e:
        print(f"argmap: cannot read {a.input}: {e}", file=sys.stderr); return 1
    bad = []
    if a.manuscript:
        bad = check_quotes(doc, open(a.manuscript, encoding="utf-8").read())
    gaps = analyse(doc)
    if a.json:
        print(json.dumps({"gaps": [dict(arg=g[0], code=g[1], criterion=g[2], question=g[3]) for g in gaps],
                          "quote_mismatch": bad}, ensure_ascii=False, indent=2)); return 0
    md = render(doc, gaps, bad)
    if a.out: open(a.out, "w", encoding="utf-8").write(md)
    else: sys.stdout.write(md)
    return 0

if __name__ == "__main__":
    sys.exit(main())
