#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成可被搜索引擎索引的球队静态页与站点地图。

主站是 hash 路由的单页应用，爬虫只能看到空壳；本脚本读取 data/matches.json，
为每支有数据的球队生成一个静态 HTML（近期战绩、逐场技术统计、下一场），
并输出 sitemap。输出目录 seo/，由 CI 复制进 dist/。

纯标准库，无第三方依赖。
"""
import html
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "matches.json")
OUT = os.path.join(ROOT, "seo")
SITE = "https://hehonghu1987.github.io/football-data-desk"
BRAND = "绿茵数据台"

ORDER = ("shots", "sot", "corners", "offsides", "yellow", "red",
         "fouls", "possession", "blocked", "saves")
SHOT, SOT, CORNER = 0, 1, 2


def esc(v):
    return html.escape(str(v if v is not None else ""))


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "team"


def fmt_date(iso):
    try:
        d = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        return d.strftime("%Y-%m-%d")
    except Exception:
        return iso or ""


CSS = """
:root{--bg:#F2F5EF;--surface:#fff;--ink:#12211A;--ink2:#33463C;--muted:#5E7065;
--line:#D3DDD5;--accent:#0E7A49;--win:#0E7A49;--draw:#A97A1F;--loss:#B24A38}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.75 'Noto Sans SC',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:960px;margin:0 auto;padding:0 20px 64px}
header{border-bottom:1px solid var(--line);background:var(--surface);margin-bottom:28px}
.bar{max-width:960px;margin:0 auto;padding:14px 20px;display:flex;align-items:center;gap:10px}
.logo{width:28px;height:28px;border-radius:8px;background:var(--accent);display:inline-flex;
align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:14px}
.brand{font-weight:700}
.brand small{display:block;font-size:10px;letter-spacing:.08em;color:var(--muted);font-weight:500}
h1{font-size:26px;margin:0 0 6px}
h2{font-size:15px;margin:32px 0 10px;color:var(--ink2)}
.sub{color:var(--muted);font-size:13px;margin:0 0 22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:0 0 8px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.card .k{font-size:11px;color:var(--muted)}
.card .v{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);
border-radius:12px;overflow:hidden;font-size:13px}
th{font-size:11px;color:var(--muted);font-weight:500;text-align:right;padding:9px 10px;
border-bottom:1px solid var(--line);white-space:nowrap}
th:nth-child(-n+4),td:nth-child(-n+4){text-align:left}
td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;
font-variant-numeric:tabular-nums;white-space:nowrap}
tr:last-child td{border-bottom:0}
.w{color:var(--win);font-weight:700}.d{color:var(--draw);font-weight:700}.l{color:var(--loss);font-weight:700}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{border:1px solid var(--line);border-radius:999px;padding:3px 11px;font-size:12.5px;background:var(--surface)}
.foot{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);
font-size:12px;color:var(--muted);line-height:1.9}
@media(max-width:640px){
  .wrap{padding:0 14px 48px} h1{font-size:21px}
  table{font-size:12px} th,td{padding:7px 7px}
  .hide-s{display:none}
}
"""


def page(title, desc, body, canonical):
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(canonical)}">
<meta name="theme-color" content="#0E7A49">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{BRAND}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:image" content="{SITE}/og-image.png">
<link rel="icon" href="/football-data-desk/og-icon.png">
<style>{CSS}</style>
</head>
<body>
<header><div class="bar">
  <a href="/football-data-desk/" style="display:flex;align-items:center;gap:10px;color:inherit">
    <span class="logo">绿</span>
    <span class="brand">{BRAND}<small>MATCH DATA DESK</small></span>
  </a>
</div></header>
<div class="wrap">
{body}
</div>
</body>
</html>
"""


def outcome(m, tid):
    home = str(m["home"]) == tid
    mine, theirs = (m["hs"], m["as"]) if home else (m["as"], m["hs"])
    if mine > theirs:
        return "w", "胜"
    if mine == theirs:
        return "d", "平"
    return "l", "负"


def main():
    if not os.path.exists(DATA):
        print("缺少 data/matches.json，跳过静态页生成")
        return 0
    payload = json.load(open(DATA, encoding="utf-8"))
    teams = {str(t["id"]): t for t in payload["teams"]}
    matches = payload["matches"]
    fixtures = payload.get("fixtures") or []

    by_team = {}
    for m in matches:
        if m.get("hs") is None:
            continue
        by_team.setdefault(str(m["home"]), []).append(m)
        by_team.setdefault(str(m["away"]), []).append(m)
    fx_by_team = {}
    for f in fixtures:
        fx_by_team.setdefault(str(f["home"]), []).append(f)
        fx_by_team.setdefault(str(f["away"]), []).append(f)

    teams_dir = os.path.join(OUT, "teams")
    os.makedirs(teams_dir, exist_ok=True)

    # 联赛分组，用于索引页
    by_league = {}
    pages = []
    now = datetime.now().astimezone()

    for tid, t in teams.items():
        ms = by_team.get(tid) or []
        if not ms:
            continue
        ms.sort(key=lambda m: m.get("date") or "", reverse=True)
        recent = ms[:10]
        name_cn = t.get("cn") or t.get("name") or tid
        name_en = t.get("name") or ""
        leagues = [l for l in (t.get("currentLeagues") or t.get("leagues") or []) if l]
        league = leagues[0] if leagues else (recent[0].get("league") if recent else "")
        by_league.setdefault(league or "其他", []).append((name_cn, tid, t))

        wins = draws = losses = 0
        gf = ga = 0
        shots = sots = corners = 0
        n_st = 0
        for m in recent:
            r, _ = outcome(m, tid)
            wins += r == "w"; draws += r == "d"; losses += r == "l"
            home = str(m["home"]) == tid
            gf += m["hs"] if home else m["as"]
            ga += m["as"] if home else m["hs"]
            st = m.get("st")
            if st:
                mine = st[0] if home else st[1]
                shots += mine[SHOT] or 0
                sots += mine[SOT] or 0
                corners += mine[CORNER] or 0
                n_st += 1
        form = "".join({"w": "W", "d": "D", "l": "L"}[outcome(m, tid)[0]] for m in recent)

        upcoming = sorted(fx_by_team.get(tid) or [], key=lambda f: f.get("date") or "")[:1]
        slug = f"{tid}-{slugify(name_en)}"
        path = f"{slug}.html"
        canonical = f"{SITE}/teams/{path}"

        title = f"{name_cn}{('（' + name_en + '）') if name_en and name_en != name_cn else ''} · 近期战绩与技术统计"
        desc = (f"{name_cn}近 {len(recent)} 场战绩 {wins}胜{draws}平{losses}负，"
                f"进 {gf} 球失 {ga} 球，场均射门 {(shots / n_st):.1f} 次、射正 {(sots / n_st):.1f} 次、"
                f"角球 {(corners / n_st):.1f} 个。含逐场比分与技术统计。") if n_st else \
               f"{name_cn}近 {len(recent)} 场战绩 {wins}胜{draws}平{losses}负，进 {gf} 球失 {ga} 球。"

        rows = []
        for m in recent:
            r, rcn = outcome(m, tid)
            home = str(m["home"]) == tid
            opp_id = str(m["away"]) if home else str(m["home"])
            opp = teams.get(opp_id) or {}
            opp_name = opp.get("cn") or opp.get("name") or opp_id
            opp_slug = f"{opp_id}-{slugify(opp.get('name'))}"
            opp_link = (f'<a href="{opp_slug}.html">{esc(opp_name)}</a>'
                        if opp.get("name") else esc(opp_name))
            st = m.get("st")
            mine = st[0] if (st and home) else (st[1] if st else None)
            cells = ""
            if mine:
                cells = (f"<td>{mine[SHOT] if mine[SHOT] is not None else '—'}</td>"
                         f"<td>{mine[SOT] if mine[SOT] is not None else '—'}</td>"
                         f"<td>{mine[CORNER] if mine[CORNER] is not None else '—'}</td>")
            else:
                cells = '<td>—</td><td>—</td><td>—</td>'
            rows.append(
                f'<tr><td>{fmt_date(m.get("date"))}</td>'
                f'<td class="hide-s">{esc(m.get("league"))}</td>'
                f'<td>{esc("主" if home else "客")}</td>'
                f'<td>{opp_link}</td>'
                f'<td class="{r}">{m["hs"]}–{m["as"]} {rcn}</td>'
                f'{cells}</tr>')

        next_html = ""
        if upcoming:
            f = upcoming[0]
            home = str(f["home"]) == tid
            opp_id = str(f["away"]) if home else str(f["home"])
            opp = teams.get(opp_id) or {}
            opp_name = opp.get("cn") or opp.get("name") or opp_id
            pred = f.get("pred") or {}
            extra = ""
            if pred.get("ph") is not None:
                extra = (f"　模型：主胜 {pred['ph'] * 100:.0f}% / 平 {pred['pd'] * 100:.0f}% / "
                         f"客胜 {pred['pa'] * 100:.0f}%，预期进球 {pred.get('xgH')}–{pred.get('xgA')}")
            next_html = (f'<h2>下一场</h2><p>{fmt_date(f.get("date"))} · {esc(f.get("league"))} · '
                         f'{"主场" if home else "客场"} 对阵 <b>{esc(opp_name)}</b>{esc(extra)}</p>')

        body = f"""<h1>{esc(name_cn)}</h1>
<p class="sub">{esc(name_en)}{(' · ' + esc(league)) if league else ''}　近 {len(recent)} 场</p>
<div class="cards">
  <div class="card"><div class="k">近 {len(recent)} 场战绩</div><div class="v">{wins}–{draws}–{losses}</div></div>
  <div class="card"><div class="k">进球 / 失球</div><div class="v">{gf} / {ga}</div></div>
  <div class="card"><div class="k">场均射门 / 射正</div><div class="v">{(shots / n_st) if n_st else 0:.1f} / {(sots / n_st) if n_st else 0:.1f}</div></div>
  <div class="card"><div class="k">场均角球</div><div class="v">{(corners / n_st) if n_st else 0:.1f}</div></div>
</div>
<h2>近期战绩</h2>
<p class="sub">走势：<b style="letter-spacing:.12em">{esc(form)}</b>（左新右旧）</p>
<table>
<thead><tr><th>日期</th><th class="hide-s">赛事</th><th>主客</th><th>对手</th><th>比分</th><th>射门</th><th>射正</th><th>角球</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
{next_html}
<h2>相关页面</h2>
<div class="chips">
  <a class="chip" href="/football-data-desk/#/team/{esc(tid)}">在数据台查看 {esc(name_cn)} 全部比赛</a>
  <a class="chip" href="index.html">全部球队索引</a>
  <a class="chip" href="/football-data-desk/#/">今日赛程与模型预测</a>
</div>
<div class="foot">
  数据来源 ESPN 公开接口，最后更新 {now.strftime('%Y-%m-%d %H:%M')}（北京时间）。<br>
  技术统计为每场单队数据；「—」表示该场暂无统计。模型预测基于近三个赛季攻防数据，不代表确定结果。
</div>"""

        ld = json.dumps({
            "@context": "https://schema.org", "@type": "SportsTeam",
            "name": name_cn, "alternateName": name_en,
            "sport": "Football", "url": canonical,
            "memberOf": {"@type": "SportsOrganization", "name": league} if league else None,
        }, ensure_ascii=False)
        body += f'\n<script type="application/ld+json">{ld}</script>'

        with open(os.path.join(teams_dir, path), "w", encoding="utf-8") as fh:
            fh.write(page(title, desc, body, canonical))
        pages.append((canonical, fmt_date(recent[0].get("date"))))

    # 索引页
    idx = []
    for lg in sorted(by_league, key=lambda x: (-len(by_league[x]), x)):
        items = sorted(by_league[lg], key=lambda x: x[0])
        links = "".join(
            f'<a class="chip" href="{tid}-{slugify(t.get("name"))}.html">{esc(cn)}</a>'
            for cn, tid, t in items)
        idx.append(f'<h2>{esc(lg)}（{len(items)} 支）</h2><div class="chips">{links}</div>')
    ibody = f"""<h1>球队索引</h1>
<p class="sub">共 {len(pages)} 支球队 · 点击查看近期战绩与逐场技术统计</p>
{''.join(idx)}
<div class="foot">数据每日自动更新。技术统计与比分来自 ESPN 公开接口。</div>"""
    with open(os.path.join(teams_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page(f"{BRAND} · 球队索引", f"{BRAND}收录 {len(pages)} 支球队的近期战绩、逐场技术统计与模型预测。",
                      ibody, f"{SITE}/teams/index.html"))

    today = now.strftime("%Y-%m-%d")
    urls = [f"{SITE}/", f"{SITE}/teams/index.html"] + [p[0] for p in pages]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        pr = "1.0" if u == f"{SITE}/" else ("0.8" if "index.html" in u else "0.6")
        sm.append(f"<url><loc>{u}</loc><lastmod>{today}</lastmod>"
                  f"<changefreq>daily</changefreq><priority>{pr}</priority></url>")
    sm.append("</urlset>")
    with open(os.path.join(OUT, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(sm))

    total = sum(os.path.getsize(os.path.join(teams_dir, f))
                for f in os.listdir(teams_dir))
    print(f"已生成 {len(pages)} 个球队静态页（{total / 1024 / 1024:.1f} MB）+ 索引页 + sitemap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
