#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成每日简报：可直接发布的 HTML 页面 + Markdown 文本。

读取 data/matches.json 与 odds_snapshots/*.jsonl，产出
  daily/YYYY-MM-DD.html   带样式的简报页（也利于搜索引擎收录）
  daily/YYYY-MM-DD.md     纯文本版，方便复制到自媒体平台
  daily/index.html        历史简报索引
并把当日页面并入 seo/sitemap.xml。

纯标准库，无第三方依赖。
"""
import html
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "matches.json")
SNAP_DIR = os.path.join(ROOT, "odds_snapshots")
OUT = os.path.join(ROOT, "daily")
SEO_SITEMAP = os.path.join(ROOT, "seo", "sitemap.xml")
SITE = "https://hehonghu1987.github.io/football-data-desk"
BRAND = "绿茵数据台"
BJ = timezone(timedelta(hours=8))

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
.brand{font-weight:700}.brand small{display:block;font-size:10px;letter-spacing:.08em;color:var(--muted);font-weight:500}
h1{font-size:26px;margin:0 0 6px}
h2{font-size:16px;margin:34px 0 12px;color:var(--ink2);border-left:3px solid var(--accent);padding-left:10px}
.sub{color:var(--muted);font-size:13px;margin:0 0 20px}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);
border-radius:12px;overflow:hidden;font-size:13px;margin-bottom:8px}
th{font-size:11px;color:var(--muted);font-weight:500;text-align:right;padding:9px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th:nth-child(1),th:nth-child(2){text-align:left}
td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td:nth-child(1),td:nth-child(2){text-align:left}
tr:last-child td{border-bottom:0}
.vs{font-weight:600;color:var(--ink)}
.num{color:var(--muted)}
.pos{color:var(--win);font-weight:700}.neg{color:var(--loss);font-weight:700}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:10px}
.card .t{font-weight:600;margin-bottom:6px}
.card .m{font-size:12.5px;color:var(--muted);line-height:1.9}
.foot{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);font-size:12px;color:var(--muted);line-height:1.9}
@media(max-width:640px){.wrap{padding:0 14px 48px}h1{font-size:21px}table{font-size:12px}th,td{padding:7px 6px}.hide-s{display:none}}
"""


def esc(v):
    return html.escape("" if v is None else str(v))


def bj_time(iso, fmt="%H:%M"):
    try:
        d = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
        return d.astimezone(BJ).strftime(fmt)
    except Exception:
        return "—"


def load_snapshots():
    """eventId → [快照…]（按时间升序）"""
    out = defaultdict(list)
    if not os.path.isdir(SNAP_DIR):
        return out
    for name in sorted(os.listdir(SNAP_DIR)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(SNAP_DIR, name), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                eid = str(o.get("e") or "")
                if eid and o.get("h") and o.get("d") and o.get("a"):
                    out[eid].append(o)
    for lst in out.values():
        lst.sort(key=lambda x: x.get("t") or "")
    return out


def devig(h, d, a):
    try:
        inv = [1 / float(h), 1 / float(d), 1 / float(a)]
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    s = sum(inv)
    return [x / s for x in inv] if s else None


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


def main():
    if not os.path.exists(DATA):
        print("缺少 data/matches.json，跳过每日简报")
        return
    payload = json.load(open(DATA, encoding="utf-8"))
    teams = {str(t["id"]): t for t in payload["teams"]}
    fixtures = payload.get("fixtures") or []
    snaps = load_snapshots()
    now = datetime.now(BJ)

    def tname(tid):
        t = teams.get(str(tid)) or {}
        return t.get("cn") or t.get("name") or str(tid)

    # 目标日期：今天有比赛就今天，否则取下一个有比赛的日子
    by_day = defaultdict(list)
    for f in fixtures:
        try:
            d = datetime.fromisoformat((f.get("date") or "").replace("Z", "+00:00")).astimezone(BJ)
        except Exception:
            continue
        by_day[d.strftime("%Y-%m-%d")].append(f)
    if not by_day:
        print("没有可用的未来比赛，跳过每日简报")
        return
    today = now.strftime("%Y-%m-%d")
    target = today if today in by_day else min(
        (d for d in by_day if d >= today), default=min(by_day))
    day_fixtures = sorted(by_day[target], key=lambda f: f.get("date") or "")
    day_dt = datetime.strptime(target, "%Y-%m-%d")
    weekday = "一二三四五六日"[day_dt.weekday()]

    os.makedirs(OUT, exist_ok=True)

    # ---- 分组：按联赛 ----
    groups = defaultdict(list)
    for f in day_fixtures:
        groups[f.get("league") or "其他"].append(f)
    order = [lg["label"] for lg in payload.get("leagues", [])]
    league_keys = sorted(groups, key=lambda x: (order.index(x) if x in order else 999, x))

    rows_html, md_lines = [], []
    for lg in league_keys:
        rows_html.append(f'<h3 style="font-size:13px;color:var(--muted);margin:18px 0 8px">{esc(lg)}</h3><table>'
                         '<thead><tr><th>时间</th><th>对阵</th><th>主胜</th><th>平</th><th>客胜</th>'
                         '<th class="hide-s">预期进球</th><th class="hide-s">大2.5</th></tr></thead><tbody>')
        md_lines.append(f"### {lg}")
        for f in groups[lg]:
            pr = f.get("pred") or {}
            h, a = tname(f["home"]), tname(f["away"])
            ph = pr.get("ph"); pd = pr.get("pd"); pa = pr.get("pa")
            xg = f"{pr.get('xgH')}–{pr.get('xgA')}" if pr.get("xgH") is not None else "—"
            o25 = pr.get("lines", {}).get("2.5")
            prob_cells = (
                f"<td>{round(ph*100)}%</td><td>{round(pd*100)}%</td><td>{round(pa*100)}%</td>"
                if None not in (ph, pd, pa) else "<td>—</td><td>—</td><td>—</td>")
            rows_html.append(
                f'<tr><td>{bj_time(f.get("date"))}</td>'
                f'<td class="vs">{esc(h)} vs {esc(a)}</td>{prob_cells}'
                f'<td class="hide-s num">{esc(xg)}</td>'
                f'<td class="hide-s num">{round(o25*100)}%</td></tr>' if o25 is not None else
                f'<tr><td>{bj_time(f.get("date"))}</td>'
                f'<td class="vs">{esc(h)} vs {esc(a)}</td>{prob_cells}'
                f'<td class="hide-s num">{esc(xg)}</td><td class="hide-s num">—</td></tr>')
            if None not in (ph, pd, pa):
                md_lines.append(
                    f"- {bj_time(f.get('date'))} **{h} vs {a}**　主胜{round(ph*100)}% / 平{round(pd*100)}% / "
                    f"客胜{round(pa*100)}%　预期进球 {xg}")
            else:
                md_lines.append(f"- {bj_time(f.get('date'))} **{h} vs {a}**　暂无模型预测")
        rows_html.append("</tbody></table>")
        md_lines.append("")

    # ---- 模型与市场分歧 ----
    edges = []
    for f in day_fixtures:
        od = f.get("odds") or {}
        ml = od.get("ml") or {}
        pr = f.get("pred") or {}
        if not (ml.get("h") and ml.get("d") and ml.get("a")):
            continue
        if pr.get("ph") is None:
            continue
        mk = devig(ml["h"], ml["d"], ml["a"])
        if not mk:
            continue
        model = [pr["ph"], pr["pd"], pr["pa"]]
        diff = [model[i] - mk[i] for i in range(3)]
        k = max(range(3), key=lambda i: abs(diff[i]))
        edges.append((abs(diff[k]), tname(f["home"]), tname(f["away"]),
                      ["主胜", "平", "客胜"][k], model[k], mk[k], f.get("league")))
    edges.sort(reverse=True)
    edge_html = ""
    if edges:
        items = []
        md_edge = ["### 模型与市场分歧最大", ""]
        for d, h, a, label, mp, kp, lg in edges[:5]:
            cls = "pos" if mp > kp else "neg"
            items.append(
                f'<tr><td>{esc(h)} vs {esc(a)}</td><td class="hide-s num">{esc(lg)}</td>'
                f'<td>{esc(label)}</td><td class="num">{round(mp*100)}%</td>'
                f'<td class="num">{round(kp*100)}%</td>'
                f'<td class="{cls}">{round((mp-kp)*100,1):+}</td></tr>')
            md_edge.append(f"- {h} vs {a}（{lg}）{label}：模型 {round(mp*100)}% vs 市场 {round(kp*100)}%"
                           f"　{round((mp-kp)*100,1):+} 个百分点")
        edge_html = ('<h2>模型与市场分歧最大</h2><table><thead><tr><th>比赛</th>'
                     '<th class="hide-s">赛事</th><th>盘口</th><th>模型</th><th>市场</th>'
                     '<th>偏差 pts</th></tr></thead><tbody>' + "".join(items) + "</tbody></table>"
                     '<div class="sub">偏差 = 模型 − 市场。胜平负方向有真实信号（技能分 +6.3%），'
                     '但偏差不代表存在投注价值。</div>')
        md_lines.extend(md_edge + [""])

    # ---- 盘口异动 ----
    moves = []
    for f in day_fixtures:
        eid = str(f.get("id"))
        hist = snaps.get(eid) or []
        if len(hist) < 2:
            continue
        first, last = hist[0], hist[-1]
        p0 = devig(first["h"], first["d"], first["a"])
        p1 = devig(last["h"], last["d"], last["a"])
        if not p0 or not p1:
            continue
        diff = [p1[i] - p0[i] for i in range(3)]
        k = max(range(3), key=lambda i: abs(diff[i]))
        if abs(diff[k]) < 0.02:
            continue
        moves.append((abs(diff[k]), tname(f["home"]), tname(f["away"]),
                      ["主胜", "平", "客胜"][k], p0[k], p1[k],
                      (first.get("t") or "")[:16].replace("T", " "),
                      (last.get("t") or "")[:16].replace("T", " ")))
    moves.sort(reverse=True)
    move_html = ""
    if moves:
        items, md_mv = [], ["### 盘口异动（赛前赔率变化 ≥2 个百分点）", ""]
        for d, h, a, label, p0, p1, t0, t1 in moves[:5]:
            cls = "pos" if p1 > p0 else "neg"
            items.append(f'<tr><td>{esc(h)} vs {esc(a)}</td><td>{esc(label)}</td>'
                         f'<td class="num">{round(p0*100)}%</td><td class="num">{round(p1*100)}%</td>'
                         f'<td class="{cls}">{round((p1-p0)*100,1):+}</td>'
                         f'<td class="hide-s num">{esc(t0)} → {esc(t1)}</td></tr>')
            md_mv.append(f"- {h} vs {a}　{label} {round(p0*100)}% → {round(p1*100)}%"
                         f"（{round((p1-p0)*100,1):+} 个百分点）")
        move_html = ('<h2>盘口异动</h2><table><thead><tr><th>比赛</th><th>盘口</th><th>开盘</th>'
                     '<th>最新</th><th>变化</th><th class="hide-s">快照时间</th></tr></thead><tbody>'
                     + "".join(items) + "</tbody></table>"
                     '<div class="sub">来自本站赛前盘口快照，只统计至少 2 次采样的比赛。</div>')
        md_lines.extend(md_mv + [""])
    else:
        move_html = ('<h2>盘口异动</h2><div class="sub">今日比赛暂无足够的赛前盘口快照样本，'
                     '该板块随快照积累逐步可用。</div>')

    title = f"{target}（周{weekday}）足球简报 · {len(day_fixtures)} 场 · {BRAND}"
    desc = (f"{target} 共 {len(day_fixtures)} 场收录比赛，覆盖 "
            + "、".join(league_keys[:6]) + "。含模型胜平负概率、预期进球、"
            f"大小球与盘口异动。数据来自 ESPN，赔率 DraftKings。")
    body = f"""<h1>{target}（周{weekday}）赛事简报</h1>
<p class="sub">共 {len(day_fixtures)} 场 · {len(league_keys)} 项赛事 · 生成于 {now.strftime('%Y-%m-%d %H:%M')}（北京时间）</p>
<h2>今日赛程与模型预测</h2>
{''.join(rows_html)}
{edge_html}
{move_html}
<div class="sub" style="margin-top:14px">概率为纯数据模型输出（泊松 + Dixon-Coles 修正，基于近三个赛季攻防数据）；
大小球方向判别力有限，请以胜平负为主参考。预测不代表确定结果。</div>
<div class="foot">
  数据来源 ESPN 公开接口，赔率来自 DraftKings（经 ESPN）。<br>
  在 <a href="/football-data-desk/">绿茵数据台</a> 查看逐场技术统计、球队近况与校准曲线。<br>
  <a href="index.html">往期简报</a>
</div>"""

    out_html = os.path.join(OUT, f"{target}.html")
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(page(title, desc, body, f"{SITE}/daily/{target}.html"))

    md = [f"# {target}（周{weekday}）足球简报", "",
          f"共 {len(day_fixtures)} 场 · {len(league_keys)} 项赛事 · {BRAND}", ""] + md_lines
    md += ["", "---", "数据来源 ESPN，赔率 DraftKings。预测不代表确定结果，仅供参考。",
           f"完整数据：{SITE}/"]
    with open(os.path.join(OUT, f"{target}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    # ---- 索引页 ----
    days = sorted([f[:-5] for f in os.listdir(OUT) if f.endswith(".html") and f != "index.html"], reverse=True)
    links = "".join(f'<li><a href="{d}.html">{d}</a>　<a href="{d}.md" '
                    f'style="font-size:12px;color:var(--muted)">纯文本</a></li>' for d in days)
    ibody = (f"<h1>每日简报</h1><p class=\"sub\">共 {len(days)} 期</p>"
             f'<ul style="line-height:2.2">{links}</ul>'
             f'<div class="foot">每期含当日赛程、模型概率与盘口异动。'
             f'<a href="/football-data-desk/">返回数据台</a></div>')
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page(f"每日简报 · {BRAND}", f"{BRAND}每日赛事简报，含模型预测与盘口异动。",
                      ibody, f"{SITE}/daily/"))

    # ---- 并入 sitemap ----
    if os.path.exists(SEO_SITEMAP):
        s = open(SEO_SITEMAP, encoding="utf-8").read()
        add = [f"<url><loc>{SITE}/daily/index.html</loc><lastmod>{target}</lastmod>"
               f"<changefreq>daily</changefreq><priority>0.9</priority></url>"]
        for d in days[:60]:
            add.append(f"<url><loc>{SITE}/daily/{d}.html</loc><lastmod>{d}</lastmod>"
                       f"<changefreq>monthly</changefreq><priority>0.5</priority></url>")
        block = "\n".join(add)
        if "daily/" not in s:
            s = s.replace("</urlset>", block + "\n</urlset>")
            with open(SEO_SITEMAP, "w", encoding="utf-8") as fh:
                fh.write(s)

    print(f"已生成每日简报 {target}：{len(day_fixtures)} 场 / "
          f"分歧 {len(edges[:5])} 条 / 异动 {len(moves[:5])} 条")


if __name__ == "__main__":
    main()
