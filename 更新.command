#!/bin/bash
# 每日更新：抓取最新赛果与技术统计，重新生成 football_database.html
cd "$(dirname "$0")" || exit 1

echo "========================================"
echo " 绿茵数据台 · 数据更新"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"
echo

python3 build_data.py "$@"
status=$?

echo
if [ $status -eq 0 ]; then
  echo "更新完成，正在打开页面…"
  open "$(dirname "$0")/football_database.html"
else
  echo "更新失败（退出码 $status），请查看上方日志。"
fi

echo
echo "按回车键关闭窗口。"
read -r
