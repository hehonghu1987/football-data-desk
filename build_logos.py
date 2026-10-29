#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把球队队徽下载并缩成 96px 存到 logos/，避免线上依赖 ESPN CDN。

ESPN 只提供 500px 版本（单张 35–90KB），全部热链既要 32MB 流量，国内网络也
不一定稳定。这里统一缩到 96px（够 64px 显示的高分屏），体积压到几 MB。

增量执行：已存在的不重复下载。新增球队后重跑一次即可。
需要 Pillow（仅本地跑，CI 不需要）。
"""
import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "matches.json")
OUT = os.path.join(ROOT, "logos")
BASE = "https://a.espncdn.com/i/teamlogos/soccer/500/"
SIZE = 96


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="忽略已有文件，全部重下")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("需要 Pillow：pip install pillow")
        return 1

    if not os.path.exists(DATA):
        print("缺少 data/matches.json，无法确定球队列表")
        return 1
    payload = json.load(open(DATA, encoding="utf-8"))
    ids = [str(t["id"]) for t in payload["teams"]]
    custom = {str(t["id"]): t.get("logo") or "" for t in payload["teams"]}

    os.makedirs(OUT, exist_ok=True)
    todo = [i for i in ids
            if args.all or not os.path.exists(os.path.join(OUT, i + ".png"))]
    print(f"球队 {len(ids)} 支，待下载 {len(todo)} 支")

    from concurrent.futures import ThreadPoolExecutor

    def grab(tid):
        url = custom.get(tid) or (BASE + tid + ".png")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read()
        except urllib.error.HTTPError:
            return tid, "404"
        except Exception as e:
            return tid, f"err {type(e).__name__}"
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGBA")
        except Exception:
            return tid, "bad image"
        # 等比缩放到 96×96 画布内，居中，保留透明边
        im.thumbnail((SIZE, SIZE), Image.LANCZOS)
        canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        canvas.paste(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2), im)
        canvas.save(os.path.join(OUT, tid + ".png"), optimize=True)
        return tid, "ok"

    ok = miss = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for tid, status in ex.map(grab, todo):
            if status == "ok":
                ok += 1
            elif status == "404":
                miss += 1
            else:
                fail += 1
    have = len([f for f in os.listdir(OUT) if f.endswith(".png")])
    total = sum(os.path.getsize(os.path.join(OUT, f))
                for f in os.listdir(OUT) if f.endswith(".png"))
    print(f"本次成功 {ok}，ESPN 无素材 {miss}，请求失败 {fail}")
    print(f"logos/ 现有 {have} 个文件，共 {total / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
