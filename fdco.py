#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多机构赛前盘口与指数（football-data.co.uk）

免费数据源，按赛季 CSV 提供：多家机构的欧赔、亚盘让球、大小球、收盘赔率、
xG 与半场比分。用于比赛复盘页的「赛前盘口 + 指数」以及历史回测。

CSV 的队名与 ESPN 不同（Man City / Wolves / Ath Bilbao…），这里用
「日期 + 比分 + 队名相似度」三重校验把两边对齐，并在校验通过后
自动学习队名映射，避免错配。
"""
import csv
import difflib
import io
import json
import os
import re
import time
import unicodedata
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "cache")
BASE = "https://football-data.co.uk/mmz4281/{season}/{div}.csv"
CACHE_TTL = 24 * 3600

# 我们数据里的联赛 -> football-data 的赛事代码
DIVS = {
    "英超": "E0", "英冠": "E1",
    "德甲": "D1", "意甲": "I1", "西甲": "SP1", "法甲": "F1",
    "荷甲": "N1", "葡超": "P1", "比甲": "B1", "土超": "T1",
    "希腊超": "G1", "苏超": "SC0",
}

# 少数固定别名（CSV -> 我们队名；归一化后比较）
ALIAS = {
    "man city": "manchester city",
    "man utd": "manchester united",
    "wolves": "wolverhampton wanderers",
    "nott'm forest": "nottingham forest",
    "nottm forest": "nottingham forest",
    "ath bilbao": "athletic club",
    "ath madrid": "atletico madrid",
    "sociedad": "real sociedad",
    "betis": "real betis",
    "la coruna": "deportivo",
    "ein frankfurt": "eintracht frankfurt",
    "fc koln": "fc cologne",
    "m'gladbach": "borussia monchengladbach",
    "dortmund": "borussia dortmund",
    "leverkuse": "bayer leverkusen",
    "paris sg": "paris saint-germain",
    "psg": "paris saint-germain",
    "inter": "inter milan",
    "verona": "hellas verona",
    "sp lisbon": "sporting cp",
    "sp braga": "sc braga",
    "st. gilloise": "union saint-gilloise",
    "den haag": "ado den haag",
    "groningen": "fc groningen",
    "utrecht": "fc utrecht",
    "twente": "fc twente",
    "heracles": "heracles almelo",
    "for sittard": "fortuna sittard",
    "hearts": "heart of midlothian",
    "ross county": "ross county",
    "athens kallithea": "kallithea",
    "aek": "aek athens",
    "istanbul bb": "istanbul basaksehir",
    "buyuksehyr": "istanbul basaksehir",
    "ad. demirspor": "adana demirspor",
    "karagumruk": "fatih karagumruk",
    "erzurumspor": "erzurum bb",
    "corum": "corum fk",
    "bodrumspor": "bodrum fk",
    "ankaragucu": "ankaragucu",
}

_STRIP = re.compile(r"[^a-z0-9 ]+")
_CLUBWORDS = {"fc", "afc", "cf", "sc", "ac", "as", "kaa", "kv", "kvc", "sk",
              "club", "the", "de", "kv", "fk", "if", "bk"}


def norm(name):
    s = unicodedata.normalize("NFKD", (name or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", " and ")
    s = _STRIP.sub(" ", s)
    toks = [t for t in s.split() if t not in _CLUBWORDS]
    s = " ".join(toks)
    return ALIAS.get(s, s)


def _fuzzy(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if ta and tb and (ta <= tb or tb <= ta):
        return 0.92
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _team_sim(csv_name, team):
    """CSV 队名和我们球队（name/short）的相似度，优先短名。"""
    if not team:
        return 0.0
    vals = [_fuzzy(csv_name, team.get("name") or ""),
            _fuzzy(csv_name, team.get("short") or "")]
    return max(vals)


def _cache_path(season, div):
    return os.path.join(CACHE_DIR, f"fdco_{season}_{div}.csv")


def _fetch(season, div):
    path = _cache_path(season, div)
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
            return path
    except OSError:
        pass
    url = BASE.format(season=season, div=div)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=40).read()
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(raw)
        return path
    except Exception:
        return path if os.path.exists(path) else None


def _num(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _odds3(row, pre):
    """读取一家机构的 1X2 赔率，兼容不同赛季的列名。"""
    keys = {
        "B365": ("B365H", "B365D", "B365A"),
        "BFD": ("BFDH", "BFDD", "BFDA"),
        "BW": ("BWH", "BWD", "BWA"),
        "BV": ("BVH", "BVD", "BVA"),
        "SKB": ("SKBH", "SKBD", "SKBA"),
        "Pinnacle": ("PPH", "PPD", "PPA"),
        "PS": ("PSH", "PSD", "PSA"),
        "Max": ("MaxH", "MaxD", "MaxA"),
        "Avg": ("AvgH", "AvgD", "AvgA"),
        "B365C": ("B365CH", "B365CD", "B365CA"),
        "AvgC": ("AvgCH", "AvgCD", "AvgCA"),
    }
    h, d, a = keys.get(pre, ([], [], []))
    vals = [_num(row.get(h)), _num(row.get(d)), _num(row.get(a))]
    if all(vals):
        return [round(v, 2) for v in vals]
    return None


def _devig(odds):
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv], s


def _indices(books):
    """返还率 / 离散度 / 凯利指数。

    - 共识概率与返还率只用真实机构（排除 Max/Avg 这类聚合列）
    - 返还率 = 1 / 平均超额（overround），正常在 0.90–0.98
    - 离散度 = 各机构同一结果概率的极差（百分点）
    - 凯利指数 = 可拿到的最高赔率 × 共识概率（>1 表示相对共识有溢价）
    """
    real = [b for b in books if b["p"] not in ("Max", "Avg")] or books
    probs, overrounds, all_odds = [], [], []
    for b in real:
        p, s = _devig(b["odds"])
        probs.append(p)
        overrounds.append(s)
        all_odds.append(b["odds"])
    n = len(probs)
    if not n:
        return None
    cons = [sum(p[i] for p in probs) / n for i in range(3)]
    payout = 1 / (sum(overrounds) / n)
    disp = []
    for i in range(3):
        xs = [p[i] for p in probs]
        disp.append(round((max(xs) - min(xs)) * 100, 2))
    best = [max(o[i] for o in all_odds) for i in range(3)]
    kelly = [round(best[i] * cons[i], 3) for i in range(3)]
    return {
        "n": n,
        "pay": round(payout, 3),
        "disp": disp,
        "kelly": kelly,
        "cons": [round(c, 4) for c in cons],
        "best": [round(x, 2) for x in best],
    }


def _compact_side(row, kind):
    if kind == "ah":
        line = _num(row.get("AHh"))
        h = _num(row.get("B365AHH")); a = _num(row.get("B365AHA"))
        if line is None or not h or not a:
            return None
        ah_avg = [_num(row.get("AvgAHH")), _num(row.get("AvgAHA"))]
        return {"line": line, "b365": [round(h, 2), round(a, 2)],
                "avg": [round(x, 2) for x in ah_avg] if all(ah_avg) else None}
    if kind == "ou":
        o = _num(row.get("B365>2.5")); u = _num(row.get("B365<2.5"))
        oa = _num(row.get("Avg>2.5")); ua = _num(row.get("Avg<2.5"))
        if not o or not u:
            return None
        return {"b365": [round(o, 2), round(u, 2)],
                "avg": [round(oa, 2), round(ua, 2)] if oa and ua else None}
    return None


def _closing_ou(row):
    o = _num(row.get("B365C>2.5")); u = _num(row.get("B365C<2.5"))
    oa = _num(row.get("AvgC>2.5")); ua = _num(row.get("AvgC<2.5"))
    if not o or not u:
        return None
    return {"b365": [round(o, 2), round(u, 2)],
            "avg": [round(oa, 2), round(ua, 2)] if oa and ua else None}


def _closing_ah(row):
    line = _num(row.get("AHCh"))
    h = _num(row.get("B365CAHH")); a = _num(row.get("B365CAHA"))
    if line is None or not h or not a:
        return None
    av = [_num(row.get("AvgCAHH")), _num(row.get("AvgCAHA"))]
    return {"line": line, "b365": [round(h, 2), round(a, 2)],
            "avg": [round(x, 2) for x in av] if all(av) else None}


def build(match_rows, teams, log=print):
    """把 football-data 的多机构盘口并入 match_rows（按比赛 id 建索引返回）。"""
    by_id = {}
    rows_cache = {}
    for season in ("2223", "2324", "2425", "2526", "2627"):
        for div in DIVS.values():
            p = _fetch(season, div)
            if not p:
                continue
            try:
                with open(p, encoding="utf-8-sig") as fh:
                    rows_cache[(season, div)] = list(csv.DictReader(fh))
            except Exception:
                continue
    if not rows_cache:
        log("  多机构盘口：CSV 不可用，跳过")
        return {}

    # 日期索引：div -> day -> rows
    idx = {}
    for (season, div), rows in rows_cache.items():
        for r in rows:
            try:
                dd, mm, yy = (r.get("Date") or "").split("/")
                day = f"{int(yy):04d}-{int(mm):02d}-{int(dd):02d}"
            except Exception:
                continue
            idx.setdefault((div, day), []).append(r)

    day_offsets = (-1, 0, 1)
    matched = 0
    learned = {}
    unmatched = {}
    for m in match_rows:
        div = DIVS.get(m.get("league"))
        if not div:
            continue
        d = (m.get("date") or "")[:10]
        if not d:
            continue
        cands = []
        for off in day_offsets:
            try:
                from datetime import date, timedelta
                y, mo, da = map(int, d.split("-"))
                dd = (date(y, mo, da) + timedelta(days=off)).isoformat()
            except Exception:
                continue
            cands.extend(idx.get((div, dd), []))
        if not cands:
            continue
        th = teams.get(str(m.get("home")))
        ta = teams.get(str(m.get("away")))
        hscore, ascore = m.get("hs"), m.get("as")
        best = None
        for r in cands:
            try:
                fh, fa = int(r.get("FTHG")), int(r.get("FTAG"))
            except (TypeError, ValueError):
                continue
            if hscore is not None and (fh != hscore or fa != ascore):
                continue
            sh = _team_sim(r.get("HomeTeam"), th)
            sa = _team_sim(r.get("AwayTeam"), ta)
            score = sh + sa
            if best is None or score > best[0]:
                best = (score, r, sh, sa)
        if not best:
            continue
        score, r, sh, sa = best
        if score < 1.2:  # 两边平均相似度太低，放弃
            key = (m.get("league"), r.get("HomeTeam"), r.get("AwayTeam"))
            unmatched[key] = unmatched.get(key, 0) + 1
            continue

        books = []
        for pre in ("B365", "Pinnacle", "PS", "BFD", "BW", "BV", "SKB", "Max", "Avg"):
            odds = _odds3(r, pre)
            if odds:
                name = {"PS": "Pinnacle"}.get(pre, pre)
                if name == "Pinnacle" and any(b["p"] == "Pinnacle" for b in books):
                    continue
                books.append({"p": name, "odds": odds})
        if not books:
            continue
        ix = _indices(books)
        show = {}
        for key in ("B365", "Pinnacle", "Avg", "Max"):
            for b in books:
                if b["p"] == key:
                    show[key] = b["odds"]
        rec = {
            "bo": show,
            "ix": {"n": ix["n"], "pay": ix["pay"], "disp": ix["disp"],
                   "kelly": ix["kelly"], "best": ix["best"],
                   "cons": [round(c, 3) for c in ix["cons"]]},
            "closing": {"b365": _odds3(r, "B365C"), "avg": _odds3(r, "AvgC")},
        }
        ah = _compact_side(r, "ah")
        if ah:
            rec["ah"] = ah
        ou = _compact_side(r, "ou")
        if ou:
            rec["ou"] = ou
        cou = _closing_ou(r)
        if cou:
            rec["closeOu"] = cou
        cah = _closing_ah(r)
        if cah:
            rec["closeAh"] = cah
        xg = [_num(r.get("HxG")), _num(r.get("AxG"))]
        if all(v is not None for v in xg):
            rec["xg"] = [round(xg[0], 2), round(xg[1], 2)]
        try:
            ht = [int(r.get("HTHG")), int(r.get("HTAG"))]
            rec["ht"] = ht
        except (TypeError, ValueError):
            pass
        by_id[str(m["id"])] = rec
        matched += 1
        learned[(r.get("HomeTeam"), str(m.get("home")))] = 1
        learned[(r.get("AwayTeam"), str(m.get("away")))] = 1

    log(f"  多机构盘口：匹配 {matched} 场，覆盖 {len(by_id)} 场")
    if unmatched:
        log("  ⚠ 未匹配队名样例：" + "、".join(f"{k[1]}" for k in list(unmatched)[:8]))
    return by_id
