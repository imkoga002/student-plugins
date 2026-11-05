#!/usr/bin/env python3
"""datacheck.py - 研究データの保存と検証。標準ライブラリのみ・ネットワーク不使用。

  add     ファイルを data/raw/ に取り込み、sha256 を manifest に、出所を provenance.jsonl に記録
  verify  manifest と実ファイルの一致、provenance の必須項目、datapackage.json の hash、raw の変更を検査
  numbers data/numeric-claims.csv の数値が processed の CSV の該当セルと一致するか、本文に現れるかを検査
  package data/datapackage.json(Frictionless v2)を manifest から再生成

API の生応答を raw に入れる場合は、提供者の規約(例: J-STAGE は機械可読形式で24時間以上の保存を禁止)を
確認し、規約上許される場合に限る。迷うときは raw に入れず、人間が確認した書誌項目だけを記録する。
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import shutil
import sys

REQUIRED_PROV = ("path", "source_url", "retrieved_at", "provider", "license", "method")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(path):
    """'<hex>  <相対パス>' 形式(sha256sum -c と互換)。"""
    entries = {}
    if not os.path.exists(path):
        return entries
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                raise ValueError("manifest %d 行目が '<64桁hex>  <path>' 形式でない" % ln)
            entries[parts[1]] = parts[0]
    return entries


def write_manifest(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        for p in sorted(entries):
            f.write("%s  %s\n" % (entries[p], p))


def read_jsonl(path):
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        raise ValueError("%s %d 行目が JSON でない" % (path, ln))
    return out


def verify(root):
    """問題の一覧を返す(空なら合格)。root はデータフォルダ(data/)。"""
    problems = []
    base = os.path.dirname(os.path.abspath(root))  # manifest のパスはプロジェクトルートからの相対
    mpath = os.path.join(root, "manifest-sha256.txt")
    try:
        manifest = read_manifest(mpath)
    except ValueError as e:
        return [str(e)]
    for rel, digest in manifest.items():
        full = os.path.join(base, rel)
        if not os.path.exists(full):
            problems.append("manifest にあるファイルが無い: " + rel)
        elif sha256_file(full) != digest:
            problems.append("ハッシュ不一致(raw が変更された可能性): " + rel)
    raw_dir = os.path.join(root, "raw")
    if os.path.isdir(raw_dir):
        for dp, _, fns in os.walk(raw_dir):
            for fn in fns:
                if fn.startswith("."):
                    continue
                rel = os.path.relpath(os.path.join(dp, fn), base).replace(os.sep, "/")
                if rel not in manifest:
                    problems.append("raw にあるが manifest に無い: " + rel)
    try:
        prov = read_jsonl(os.path.join(root, "provenance.jsonl"))
    except ValueError as e:
        return problems + [str(e)]
    prov_paths = set()
    for i, rec in enumerate(prov, 1):
        if rec.get("kind") == "processing":
            for k in ("output", "script", "inputs", "run_at"):
                if not rec.get(k):
                    problems.append("provenance %d(加工): '%s' が空" % (i, k))
            continue
        prov_paths.add(rec.get("path"))
        for k in REQUIRED_PROV:
            if not str(rec.get(k, "")).strip():
                problems.append("provenance %d(%s): 必須項目 '%s' が空" % (i, rec.get("path"), k))
    for rel in manifest:
        if rel.startswith("data/raw/") and rel not in prov_paths:
            problems.append("出所(provenance)が無い raw ファイル: " + rel)
    dp = os.path.join(root, "datapackage.json")
    if os.path.exists(dp):
        try:
            pkg = json.load(open(dp, encoding="utf-8"))
        except ValueError:
            return problems + ["datapackage.json が JSON として不正"]
        for res in pkg.get("resources", []):
            h = res.get("hash", "")
            p = res.get("path", "")
            if h.startswith("sha256:") and p in manifest and h[7:] != manifest[p]:
                problems.append("datapackage の hash が manifest と不一致: " + p)
            if not h:
                problems.append("datapackage の resource に hash が無い: " + p)
    return problems


def check_numbers(root, manuscript=None):
    """numeric-claims.csv: claim_id,text_value,file,column,key_column,key,note"""
    problems = []
    base = os.path.dirname(os.path.abspath(root))
    path = os.path.join(root, "numeric-claims.csv")
    if not os.path.exists(path):
        return ["numeric-claims.csv が無い"]
    text = open(manuscript, encoding="utf-8").read() if manuscript else None
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cid = r.get("claim_id")
            data = os.path.join(base, r.get("file", ""))
            if not os.path.exists(data):
                problems.append("%s: データファイルが無い: %s" % (cid, r.get("file")))
                continue
            with open(data, newline="", encoding="utf-8") as g:
                rows = [x for x in csv.DictReader(g) if x.get(r["key_column"]) == r["key"]]
            if len(rows) != 1:
                problems.append("%s: キー %s=%s の行が %d 件(1件であるべき)" % (cid, r["key_column"], r["key"], len(rows)))
                continue
            cell = (rows[0].get(r["column"]) or "").strip()
            want = (r["text_value"] or "").replace(",", "").strip()
            try:
                same = abs(float(cell.replace(",", "")) - float(want)) < 1e-9
            except ValueError:
                same = cell == want
            if not same:
                problems.append("%s: 本文の値 %s とデータの値 %s が一致しない" % (cid, r["text_value"], cell))
            if text is not None and r["text_value"] not in text:
                problems.append("%s: 本文に '%s' が見つからない" % (cid, r["text_value"]))
    return problems


def add(root, src, source_url, provider, license_, method, note=""):
    raw_dir = os.path.join(root, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    dest = os.path.join(raw_dir, os.path.basename(src))
    if os.path.exists(dest):
        raise FileExistsError("raw は上書きしない: " + dest)
    shutil.copy2(src, dest)
    os.chmod(dest, 0o444)
    base = os.path.dirname(os.path.abspath(root))
    rel = os.path.relpath(dest, base).replace(os.sep, "/")
    mpath = os.path.join(root, "manifest-sha256.txt")
    m = read_manifest(mpath)
    m[rel] = sha256_file(dest)
    write_manifest(mpath, m)
    rec = {"kind": "raw", "path": rel, "source_url": source_url, "retrieved_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "provider": provider, "license": license_, "method": method, "sha256": m[rel], "note": note}
    with open(os.path.join(root, "provenance.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def package(root, name="project-data"):
    base = os.path.dirname(os.path.abspath(root))
    m = read_manifest(os.path.join(root, "manifest-sha256.txt"))
    prov = {r.get("path"): r for r in read_jsonl(os.path.join(root, "provenance.jsonl")) if r.get("kind") != "processing"}
    res = []
    for rel in sorted(m):
        p = prov.get(rel, {})
        res.append({"name": os.path.splitext(os.path.basename(rel))[0].lower().replace(" ", "-").replace("_", "-"),
                    "path": rel, "hash": "sha256:" + m[rel],
                    "bytes": os.path.getsize(os.path.join(base, rel)) if os.path.exists(os.path.join(base, rel)) else None,
                    "sources": [{"title": p.get("provider", ""), "path": p.get("source_url", "")}],
                    "licenses": [{"name": p.get("license", "")}]})
    pkg = {"$schema": "https://datapackage.org/profiles/2.0/datapackage.json", "name": name, "resources": res}
    json.dump(pkg, open(os.path.join(root, "datapackage.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return pkg


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--root", default="data")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("file"); a.add_argument("--url", required=True); a.add_argument("--provider", required=True)
    a.add_argument("--license", required=True); a.add_argument("--method", required=True); a.add_argument("--note", default="")
    sub.add_parser("verify")
    n = sub.add_parser("numbers"); n.add_argument("--manuscript")
    sub.add_parser("package")
    args = p.parse_args(argv)
    if args.cmd == "add":
        print(json.dumps(add(args.root, args.file, args.url, args.provider, args.license, args.method, args.note), ensure_ascii=False))
        return 0
    if args.cmd == "package":
        package(args.root); print("datapackage.json を再生成した"); return 0
    probs = verify(args.root) if args.cmd == "verify" else check_numbers(args.root, args.manuscript)
    for x in probs:
        print("NG", x)
    print("%s: %d 件の問題" % (args.cmd, len(probs)))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
