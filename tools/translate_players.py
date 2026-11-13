#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 Wikidata 给未翻译球员补中文名（输出 player_cn_extra.json）。

数据来源：Wikidata SPARQL（免费）。只匹配「英文名完全相同 + 职业为足球运动员」的实体，
优先 zh-hans 标签，其次 zh 标签。已翻译的球员不会覆盖。
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "player_cn.json")
EXTRA = os.path.join(ROOT, "player_cn_extra.json")
ROSTERS = os.path.join(ROOT, "data", "rosters.json")
LINEUPS = os.path.join(ROOT, "data", "lineups.json")
UA = {"User-Agent": "footballdesk-translator/1.0 (github.com/hehonghu1987/football-data-desk)"}

SPARQL = """SELECT ?en ?zh WHERE {
  VALUES ?en { %s }
  ?p rdfs:label ?en ; wdt:P106 wd:Q937857 .
  ?p rdfs:label ?zh . FILTER(LANG(?zh) IN ("zh-hans", "zh"))
}"""


def _is_cn(t):
    return any(0x4E00 <= ord(ch) <= 0x9FFF for ch in (t or ""))


def load_names():
    """只翻译真正会显示在页面上的球员：参考阵容（预计首发/替补）里的英文名。"""
    names = set()
    try:
        lu = json.load(open(LINEUPS, encoding="utf-8"))["lineups"]
        for entry in lu.values():
            for pl in (entry.get("p") or []):
                en = (pl.get("en") or "").strip()
                n = pl.get("n") or ""
                if en and not _is_cn(n):
                    names.add(en)
    except (OSError, ValueError, KeyError):
        pass
    return names


def query(names):
    vals = " ".join('"%s"@en' % n.replace('"', "") for n in names)
    url = ("https://query.wikidata.org/sparql?format=json&query="
           + urllib.parse.quote(SPARQL % vals))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = {}
    for b in data.get("results", {}).get("bindings", []):
        en = b["en"]["value"]
        zh = b["zh"]["value"]
        if en and zh:
            out[en] = zh
    return out


def main():
    base = json.load(open(BASE, encoding="utf-8")) if os.path.exists(BASE) else {}
    extra = json.load(open(EXTRA, encoding="utf-8")) if os.path.exists(EXTRA) else {}
    known = set(base) | set(extra)
    names = sorted(n for n in load_names() if n and n not in known)
    print(f"待翻译 {len(names)} 人（已有 {len(known)} 人）")
    got = 0
    for i in range(0, len(names), 50):
        chunk = names[i:i + 50]
        for attempt in range(3):
            try:
                res = query(chunk)
                break
            except Exception as e:
                print(f"  批次 {i} 失败（{attempt + 1}/3）：{str(e)[:80]}")
                time.sleep(3 + attempt * 3)
                res = {}
        for en, zh in res.items():
            if en not in known:
                extra[en] = zh
                known.add(en)
                got += 1
        print(f"  {min(i + 50, len(names))}/{len(names)} 已补 {got} 人")
        time.sleep(1.0)
    with open(EXTRA, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(extra.items())), fh, ensure_ascii=False, indent=1)
    print(f"完成：新增 {got} 人，累计 extra {len(extra)} 人 → {EXTRA}")


if __name__ == "__main__":
    sys.exit(main())
