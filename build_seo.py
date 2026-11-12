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

# 球队可能同时出现在国内联赛、洲际赛与杯赛中。索引分组与 memberOf 只应取
# 国内联赛，否则会出现「国王杯 134 支」「LASK 属于欧冠」这类错误分类。
DOMESTIC_LEAGUES = {
    "英超", "西甲", "意甲", "德甲", "法甲", "英冠", "巴西甲", "荷甲", "葡超",
    "土超", "比甲", "奥甲", "希腊超", "苏超", "挪超", "丹超", "瑞超", "俄超",
    "乌超", "波甲", "捷甲", "瑞士超", "巴甲", "阿甲", "美职联", "日职联",
}
EURO_OR_CUP = {
    "欧冠", "欧联杯", "欧协联", "欧冠资格赛", "欧联杯资格赛", "欧协联资格赛",
    "足总杯", "英联杯", "国王杯", "意大利杯", "德国杯", "法国杯", "巴西杯",
    "世俱杯", "解放者杯", "南美杯", "超级杯",
}


def main_league(t, recent):
    """给出球队「主联赛」：优先国内联赛，其次近期比赛里最常见的联赛。"""
    cands = [l for l in (t.get("currentLeagues") or []) if l]
    cands += [l for l in (t.get("leagues") or []) if l and l not in cands]
    for l in cands:
        if l in DOMESTIC_LEAGUES:
            return l
    cnt = Counter(m.get("league") for m in recent
                  if (m.get("league") or "") in DOMESTIC_LEAGUES)
    if cnt:
        return cnt.most_common(1)[0][0]
    cnt = Counter(m.get("league") for m in recent if m.get("league"))
    if cnt:
        return cnt.most_common(1)[0][0]
    for l in cands:
        if l not in EURO_OR_CUP:
            return l
    return cands[0] if cands else ""


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
    try:
        rosters = json.load(open(os.path.join(ROOT, "data", "rosters.json"), encoding="utf-8")).get("teams") or {}
    except (OSError, ValueError):
        rosters = {}
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

    team_paths = {}
    for tid, t in teams.items():
        ms = by_team.get(tid) or []
        if not ms:
            continue
        ms.sort(key=lambda m: m.get("date") or "", reverse=True)
        recent = ms[:10]
        name_cn = t.get("cn") or t.get("name") or tid
        name_en = t.get("name") or ""
        league = main_league(t, recent)
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

        title = f"{name_cn} · 近期战绩与技术统计"
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
<p class="sub">{esc(league)}　近 {len(recent)} 场</p>
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
        team_paths[tid] = path
        pages.append((canonical, fmt_date(recent[0].get("date"))))

    # ---- 比赛静态页：未来赛程 + 近 30 天赛果 ----
    match_dir = os.path.join(OUT, "matches")
    os.makedirs(match_dir, exist_ok=True)
    now_iso = now.isoformat()
    cutoff = (now - timedelta(days=30)).isoformat()
    match_pages = []

    def team_link(tid):
        t = teams.get(str(tid)) or {}
        nm = esc(t.get("cn") or t.get("name") or tid)
        path = team_paths.get(str(tid))
        return f'<a href="../teams/{path}">{nm}</a>' if path else nm

    def pct(v):
        return "—" if v is None else f"{v * 100:.0f}%"

    def render_match(m, is_fixture):
        home, away = m.get("home"), m.get("away")
        ht = teams.get(str(home)) or {}
        at = teams.get(str(away)) or {}
        hname = esc(ht.get("cn") or ht.get("name") or home)
        aname = esc(at.get("cn") or at.get("name") or away)
        done = m.get("hs") is not None and m.get("as") is not None
        score = f'{m["hs"]}–{m["as"]}' if done else "VS"
        pred = m.get("pred") or {}
        pre = m.get("pre") or {}
        cards = []
        if done:
            cards.append(f'<div class="card"><div class="k">比分</div><div class="v">{score}</div></div>')
        if pred:
            cards.append(f'<div class="card"><div class="k">模型 主/平/客</div><div class="v">{pct(pred.get("ph"))} / {pct(pred.get("pd"))} / {pct(pred.get("pa"))}</div></div>')
            cards.append(f'<div class="card"><div class="k">预期进球</div><div class="v">{pred.get("xgH")}–{pred.get("xgA")}</div></div>')
        elif pre:
            cards.append(f'<div class="card"><div class="k">赛前模型 主/平/客</div><div class="v">{pct(pre.get("ph"))} / {pct(pre.get("pd"))} / {pct(pre.get("pa"))}</div></div>')
            cards.append(f'<div class="card"><div class="k">赛前预期进球</div><div class="v">{pre.get("xh")}–{pre.get("xa")}</div></div>')
        body = f"<h1>{hname} vs {aname}</h1>"
        body += (f'<p class="sub">{esc(m.get("league"))} · {fmt_date(m.get("date"))} · '
                 f'{esc(m.get("venue") or "")} {"· 已结束" if done else "· 赛前"}</p>')
        if cards:
            body += '<div class="cards">' + "".join(cards) + "</div>"
        # 模型市场
        if pred:
            rows = []
            if pred.get("lines"):
                for k in sorted(pred["lines"], key=lambda x: float(x))[:5]:
                    rows.append(f'<tr><td>大 {k} 球</td><td>{pct(pred["lines"][k])}</td>'
                                f'<td>小 {k} 球</td><td>{pct(1 - pred["lines"][k])}</td></tr>')
            if pred.get("btts") is not None:
                rows.append(f'<tr><td>双方进球</td><td>{pct(pred["btts"])}</td><td></td><td></td></tr>')
            if pred.get("corners"):
                c = pred["corners"]
                rows.append(f'<tr><td>期望角球</td><td>{c.get("exp")}</td>'
                            f'<td>大 9.5</td><td>{pct((c.get("over") or {}).get("9.5"))}</td></tr>')
            if rows:
                body += ("<h2>模型预测</h2><table><thead><tr><th>市场</th><th>概率</th>"
                         "<th>市场</th><th>概率</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
        # 盘口
        odds = m.get("odds") if is_fixture else None
        if odds:
            ml = odds.get("ml") or {}
            ah = odds.get("ah") or {}
            ou = odds.get("ou") or {}
            orows = []
            if ml:
                orows.append(f'<tr><td>欧赔 主/平/客</td><td>{ml.get("h")} / {ml.get("d")} / {ml.get("a")}</td></tr>')
            if ah:
                orows.append(f'<tr><td>亚盘 让球</td><td>{ah.get("line")} · 主 {ah.get("h")} / 客 {ah.get("a")}</td></tr>')
            if ou:
                orows.append(f'<tr><td>大小球</td><td>{ou.get("line")} · 大 {ou.get("over")} / 小 {ou.get("under")}</td></tr>')
            if orows:
                body += ("<h2>赛前盘口</h2><table><thead><tr><th>市场</th><th>赔率</th></tr></thead>"
                         "<tbody>" + "".join(orows) + "</tbody></table>")
        # 事件
        evs = m.get("ev") or []
        if evs:
            icons = {"g": "⚽", "og": "⚽", "p": "⚽", "y": "🟨", "r": "🟥", "pm": "⛔"}
            er = "".join(f'<tr><td>{esc(e[0])}</td><td>{icons.get(e[1], "•")}</td><td>{esc(e[3])}</td>'
                         f'<td>{hname if e[2] == 0 else aname}</td></tr>' for e in evs)
            body += ("<h2>比赛事件</h2><table><thead><tr><th>时间</th><th></th><th>球员</th><th>球队</th>"
                     "</tr></thead><tbody>" + er + "</tbody></table>")
        # 阵容（来自 data/rosters.json）
        squad_blocks = ""
        for tid, nm in ((home, hname), (away, aname)):
            pl = rosters.get(str(tid)) or []
            if not pl:
                continue
            rows_pl = "".join(
                f'<tr><td>{esc(p.get("j") or "")}</td><td>{esc(p.get("n") or p.get("e") or "")}</td>'
                f'<td>{esc(p.get("pos") or "")}</td><td>{esc(p.get("age") or "—")}</td>'
                f'<td>{esc(p.get("nat") or "")}</td>'
                f'<td>{esc(p.get("app") if p.get("app") is not None else "—")}</td>'
                f'<td>{esc(p.get("g") or 0)}</td><td>{esc(p.get("a") or 0)}</td></tr>'
                for p in pl[:18])
            squad_blocks += (f'<h3>{nm} 阵容</h3><table><thead><tr><th>号</th><th>球员</th><th>位置</th>'
                             f'<th>年龄</th><th>国籍</th><th>出场</th><th>进球</th><th>助攻</th></tr></thead>'
                             f'<tbody>{rows_pl}</tbody></table>')
        if squad_blocks:
            body += "<h2>双方阵容</h2>" + squad_blocks
        body += ('<h2>相关页面</h2><div class="chips">'
                 f'<a class="chip" href="../teams/{team_paths.get(str(home), "")}">{hname} 球队页</a>'
                 f'<a class="chip" href="../teams/{team_paths.get(str(away), "")}">{aname} 球队页</a>'
                 f'<a class="chip" href="/football-data-desk/#/match/{esc(m.get("id"))}">在数据台查看</a>'
                 '<a class="chip" href="index.html">全部比赛</a></div>')
        body += (f'<div class="foot">数据来源 ESPN 公开接口，最后更新 '
                 f'{now.strftime("%Y-%m-%d %H:%M")}（北京时间）。预测不代表确定结果。</div>')
        ld = json.dumps({
            "@context": "https://schema.org", "@type": "SportsEvent",
            "name": f"{ht.get('cn') or ht.get('name')} vs {at.get('cn') or at.get('name')}",
            "startDate": m.get("date"),
            "eventStatus": "https://schema.org/EventScheduled",
            "location": {"@type": "Place", "name": m.get("venue") or ""},
            "competitor": [{"@type": "SportsTeam", "name": ht.get("cn") or ht.get("name")},
                           {"@type": "SportsTeam", "name": at.get("cn") or at.get("name")}],
        }, ensure_ascii=False)
        body += f'\n<script type="application/ld+json">{ld}</script>'
        return body

    for m in fixtures:
        if m.get("hide") or m.get("date") is None:
            continue
        path = f'{m.get("id")}.html'
        title = f'{((teams.get(str(m.get("home"))) or {}).get("cn") or "主队")} vs ' \
                f'{((teams.get(str(m.get("away"))) or {}).get("cn") or "客队")} · {m.get("league")} 赛前'
        desc = f'{m.get("league")} {fmt_date(m.get("date"))} 赛前分析：模型概率、盘口与双方近期数据。'
        canonical = f'{SITE}/matches/{path}'
        body = render_match(m, True)
        with open(os.path.join(match_dir, path), "w", encoding="utf-8") as fh:
            fh.write(page(title, desc, body, canonical))
        match_pages.append((canonical, fmt_date(m.get("date"))))

    for m in matches:
        if m.get("hide") or (m.get("date") or "") < cutoff:
            continue
        path = f'{m.get("id")}.html'
        hcn = (teams.get(str(m.get("home"))) or {}).get("cn") or "主队"
        acn = (teams.get(str(m.get("away"))) or {}).get("cn") or "客队"
        title = f'{hcn} {m.get("hs")}–{m.get("as")} {acn} · {m.get("league")} 战报'
        desc = f'{m.get("league")} {fmt_date(m.get("date"))} {hcn} {m.get("hs")}–{m.get("as")} {acn}，含技术统计、模型预测与比赛事件。'
        canonical = f'{SITE}/matches/{path}'
        body = render_match(m, False)
        with open(os.path.join(match_dir, path), "w", encoding="utf-8") as fh:
            fh.write(page(title, desc, body, canonical))
        match_pages.append((canonical, fmt_date(m.get("date"))))

    # 比赛索引页
    if match_pages:
        up = [m for m in fixtures if not m.get("hide") and m.get("date")]
        rec = sorted([m for m in matches if not m.get("hide") and (m.get("date") or "") >= cutoff],
                     key=lambda x: x.get("date") or "", reverse=True)[:60]
        def link(m):
            hcn = (teams.get(str(m.get("home"))) or {}).get("cn") or "主队"
            acn = (teams.get(str(m.get("away"))) or {}).get("cn") or "客队"
            return (f'<a class="chip" href="{m.get("id")}.html">{esc(hcn)} vs {esc(acn)}'
                    f'（{fmt_date(m.get("date"))}）</a>')
        ib = ('<h1>比赛索引</h1><p class="sub">未来赛程与近 30 天赛果的静态页，含模型预测、盘口与比赛事件。</p>'
              '<h2>未来赛程</h2><div class="chips">' + "".join(link(m) for m in up[:120]) + '</div>'
              '<h2>近期赛果</h2><div class="chips">' + "".join(link(m) for m in rec) + '</div>'
              '<div class="foot">比分每 30 分钟自动更新。</div>')
        with open(os.path.join(match_dir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(page(f"{BRAND} · 比赛索引", f"{BRAND}比赛索引：赛程、比分、模型预测与盘口。",
                          ib, f"{SITE}/matches/index.html"))
        pages.append((f"{SITE}/matches/index.html", now.strftime("%Y-%m-%d")))
    for u, d in match_pages:
        pages.append((u, d))
    print(f"已生成 {len(match_pages)} 个比赛静态页")

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
<div class="foot">比分每 30 分钟自动更新。技术统计与比分来自 ESPN 公开接口。</div>"""
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
