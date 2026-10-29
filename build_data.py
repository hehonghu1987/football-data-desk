#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""足球赛事数据采集器

数据源：ESPN 公开站点 API（无需 key）
覆盖：英超/西甲/意甲/德甲/法甲/英冠/欧冠/欧联杯/巴西甲
      以及足总杯/英联杯/国王杯/意大利杯/德国杯/法国杯/巴西杯
产出：data/matches.json + football_database.html（单文件、可离线打开）

用法：
  python3 build_data.py                 # 全量构建（首次约 5-15 分钟）
  python3 build_data.py --leagues 西甲,英超 --max-summaries 40   # 快速测试
  python3 build_data.py --no-html       # 只更新 JSON
  python3 build_data.py --refresh       # 忽略赛程缓存（比分统计缓存仍复用）
"""

import argparse
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

def _season_code(today=None):
    d = today or date.today()
    return d.year if d.month >= 7 else d.year - 1


CURRENT_SEASON = _season_code()
# 滚动保留最近 5 个赛季，避免页面数据无限增长
SEASONS = list(range(CURRENT_SEASON, CURRENT_SEASON - 5, -1))

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, "cache")
DATA_DIR = os.path.join(ROOT, "data")
API = "https://site.api.espn.com/apis/site/v2/sports/soccer"
CORE = "https://sports.core.api.espn.com/v2/sports/soccer"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

LEAGUES = [
    {"label": "英超", "code": "eng.1", "cat": "major", "seasons": SEASONS},
    {"label": "西甲", "code": "esp.1", "cat": "major", "seasons": SEASONS},
    {"label": "意甲", "code": "ita.1", "cat": "major", "seasons": SEASONS},
    {"label": "德甲", "code": "ger.1", "cat": "major", "seasons": SEASONS},
    {"label": "法甲", "code": "fra.1", "cat": "major", "seasons": SEASONS},
    {"label": "欧冠", "code": "uefa.champions", "cat": "major", "seasons": SEASONS},
    {"label": "欧联杯", "code": "uefa.europa", "cat": "major", "seasons": SEASONS},
    {"label": "英冠", "code": "eng.2", "cat": "champ", "seasons": SEASONS},
    {"label": "巴西甲", "code": "bra.1", "cat": "brazil", "seasons": SEASONS},
    # 国内杯赛：不单独列分类，只补充到相关球队的历史里
    {"label": "足总杯", "code": "eng.fa", "cat": "major", "seasons": SEASONS,
     "support_for": ["英超", "英冠"], "core_schedule": True},
    {"label": "英联杯", "code": "eng.league_cup", "cat": "major", "seasons": SEASONS,
     "support_for": ["英超", "英冠"]},
    {"label": "国王杯", "code": "esp.copa_del_rey", "cat": "major", "seasons": SEASONS,
     "support_for": ["西甲"]},
    {"label": "意大利杯", "code": "ita.coppa_italia", "cat": "major", "seasons": SEASONS,
     "support_for": ["意甲"]},
    {"label": "德国杯", "code": "ger.dfb_pokal", "cat": "major", "seasons": SEASONS,
     "support_for": ["德甲"]},
    {"label": "法国杯", "code": "fra.coupe_de_france", "cat": "major", "seasons": SEASONS,
     "support_for": ["法甲"]},
    {"label": "巴西杯", "code": "bra.copa_do_brazil", "cat": "brazil", "seasons": SEASONS,
     "support_for": ["巴西甲"]},
]

CATEGORIES = [
    {"id": "major", "label": "五大联赛 + 欧战",
     "desc": "英超、西甲、意甲、德甲、法甲，以及欧冠、欧联杯"},
    {"id": "champ", "label": "英冠", "desc": "英格兰足球冠军联赛"},
    {"id": "brazil", "label": "巴西甲", "desc": "巴西足球甲级联赛"},
]

# ESPN displayName -> 中文名 / 搜索别名
CN = {
    # 英超
    "AFC Bournemouth": ("伯恩茅斯", ["樱桃"]),
    "Arsenal": ("阿森纳", ["阿仙奴", "枪手"]),
    "Aston Villa": ("阿斯顿维拉", ["维拉"]),
    "Brentford": ("布伦特福德", ["宾福特", "蜜蜂"]),
    "Brighton & Hove Albion": ("布莱顿", ["白礼顿", "海鸥"]),
    "Chelsea": ("切尔西", ["蓝军"]),
    "Coventry City": ("考文垂", []),
    "Crystal Palace": ("水晶宫", []),
    "Everton": ("埃弗顿", ["太妃糖"]),
    "Fulham": ("富勒姆", []),
    "Hull City": ("赫尔城", []),
    "Ipswich Town": ("伊普斯维奇", ["拖拉机男孩"]),
    "Leeds United": ("利兹联", ["利兹"]),
    "Liverpool": ("利物浦", ["红军"]),
    "Manchester City": ("曼城", ["曼彻斯特城", "蓝月亮"]),
    "Manchester United": ("曼联", ["曼彻斯特联", "红魔"]),
    "Newcastle United": ("纽卡斯尔联", ["纽卡", "喜鹊"]),
    "Nottingham Forest": ("诺丁汉森林", ["森林"]),
    "Sunderland": ("桑德兰", ["黑猫"]),
    "Tottenham Hotspur": ("热刺", ["托特纳姆热刺"]),
    # 西甲
    "Alavés": ("阿拉维斯", []),
    "Athletic Club": ("毕尔巴鄂竞技", ["毕尔巴鄂"]),
    "Atlético Madrid": ("马德里竞技", ["马竞", "床单军团"]),
    "Barcelona": ("巴塞罗那", ["巴萨", "红蓝军团"]),
    "Celta Vigo": ("塞尔塔", []),
    "Deportivo": ("拉科鲁尼亚", ["拉科"]),
    "Elche": ("埃尔切", []),
    "Espanyol": ("西班牙人", []),
    "Getafe": ("赫塔费", ["赫塔菲"]),
    "Levante": ("莱万特", []),
    "Málaga": ("马拉加", []),
    "Osasuna": ("奥萨苏纳", []),
    "Racing Santander": ("桑坦德竞技", []),
    "Rayo Vallecano": ("巴列卡诺", []),
    "Real Betis": ("皇家贝蒂斯", ["贝蒂斯"]),
    "Real Madrid": ("皇家马德里", ["皇马", "银河战舰"]),
    "Real Sociedad": ("皇家社会", []),
    "Sevilla": ("塞维利亚", []),
    "Valencia": ("瓦伦西亚", ["蝙蝠军团"]),
    "Villarreal": ("比利亚雷亚尔", ["黄潜"]),
    "Girona": ("赫罗纳", []),
    "Mallorca": ("马略卡", []),
    "Real Oviedo": ("皇家奥维耶多", ["奥维耶多"]),
    "Las Palmas": ("拉斯帕尔马斯", []),
    "Leganés": ("莱加内斯", []),
    "Real Valladolid": ("皇家巴拉多利德", ["巴拉多利德"]),
    "Almería": ("阿尔梅里亚", []),
    "Cádiz": ("加的斯", []),
    "Granada": ("格拉纳达", []),
    # 意甲
    "AC Milan": ("AC米兰", ["米兰", "红黑军团"]),
    "AS Roma": ("罗马", ["红狼"]),
    "Atalanta": ("亚特兰大", ["真蓝黑"]),
    "Bologna": ("博洛尼亚", []),
    "Cagliari": ("卡利亚里", []),
    "Como": ("科莫", []),
    "Fiorentina": ("佛罗伦萨", ["紫百合"]),
    "Frosinone": ("弗罗西诺内", []),
    "Genoa": ("热那亚", []),
    "Internazionale": ("国际米兰", ["国米", "蓝黑军团"]),
    "Juventus": ("尤文图斯", ["尤文", "斑马军团"]),
    "Lazio": ("拉齐奥", ["蓝鹰"]),
    "Lecce": ("莱切", []),
    "Monza": ("蒙扎", []),
    "Napoli": ("那不勒斯", ["拿坡里"]),
    "Parma": ("帕尔马", []),
    "Sassuolo": ("萨索洛", []),
    "Torino": ("都灵", []),
    "Udinese": ("乌迪内斯", []),
    "Venezia": ("威尼斯", []),
    # 德甲
    "1. FC Union Berlin": ("柏林联合", []),
    "Bayer Leverkusen": ("勒沃库森", ["药厂"]),
    "Bayern Munich": ("拜仁慕尼黑", ["拜仁"]),
    "Borussia Dortmund": ("多特蒙德", ["多特", "大黄蜂"]),
    "Borussia Mönchengladbach": ("门兴格拉德巴赫", ["门兴"]),
    "Eintracht Frankfurt": ("法兰克福", []),
    "FC Augsburg": ("奥格斯堡", []),
    "FC Cologne": ("科隆", []),
    "Hamburg SV": ("汉堡", []),
    "Mainz": ("美因茨", []),
    "RB Leipzig": ("RB莱比锡", ["莱比锡", "红牛"]),
    "SC Freiburg": ("弗赖堡", []),
    "SC Paderborn 07": ("帕德博恩", []),
    "SV Elversberg": ("埃尔弗斯贝格", []),
    "Schalke 04": ("沙尔克04", ["沙尔克"]),
    "TSG Hoffenheim": ("霍芬海姆", []),
    "VfB Stuttgart": ("斯图加特", []),
    "Werder Bremen": ("云达不莱梅", ["不莱梅"]),
    # 法甲
    "AJ Auxerre": ("欧塞尔", []),
    "AS Monaco": ("摩纳哥", []),
    "Angers": ("昂热", []),
    "Brest": ("布雷斯特", []),
    "Le Havre AC": ("勒阿弗尔", []),
    "Le Mans": ("勒芒", []),
    "Lens": ("朗斯", []),
    "Lille": ("里尔", []),
    "Lorient": ("洛里昂", []),
    "Lyon": ("里昂", []),
    "Marseille": ("马赛", []),
    "Nice": ("尼斯", []),
    "Paris FC": ("巴黎FC", []),
    "Paris Saint-Germain": ("巴黎圣日耳曼", ["大巴黎", "巴黎"]),
    "Stade Rennais": ("雷恩", []),
    "Strasbourg": ("斯特拉斯堡", []),
    "Toulouse": ("图卢兹", []),
    "Troyes": ("特鲁瓦", []),
    "AS Saint-Étienne": ("圣埃蒂安", []),
    "Stade de Reims": ("兰斯", []),
    "Montpellier": ("蒙彼利埃", []),
    "FC Nantes": ("南特", []),
    "FC Metz": ("梅斯", []),
    "Clermont Foot": ("克莱蒙", []),
    # 其他常见欧战/历史对手
    "Hellas Verona": ("维罗纳", []),
    "Pisa": ("比萨", []),
    "Cremonese": ("克雷莫纳", []),
    "Empoli": ("恩波利", []),
    "Salernitana": ("萨勒尼塔纳", []),
    "Spezia": ("斯佩齐亚", []),
    "FC St. Pauli": ("圣保利", []),
    "Holstein Kiel": ("荷尔斯泰因基尔", ["基尔"]),
    "FC Copenhagen": ("哥本哈根", []),
    "Ajax": ("阿贾克斯", []),
    "Rangers": ("格拉斯哥流浪者", ["流浪者"]),
    "Red Star Belgrade": ("贝尔格莱德红星", ["红星"]),
    "SC Braga": ("布拉加", []),
    "BSC Young Boys": ("年轻人", []),
    "FC Basel": ("巴塞尔", []),
    "FC Midtjylland": ("中日德兰", []),
    "Legia Warsaw": ("华沙莱吉亚", []),
    "Panathinaikos": ("帕纳辛奈科斯", []),
    "PAOK": ("塞萨洛尼基PAOK", ["PAOK"]),
    "Rapid Wien": ("维也纳快速", []),
    "Maccabi Tel Aviv": ("特拉维夫马卡比", []),
    "Leicester City": ("莱斯特城", ["莱斯特"]),
    # 英冠
    "Birmingham City": ("伯明翰", []),
    "Blackburn Rovers": ("布莱克本", []),
    "Bolton Wanderers": ("博尔顿", []),
    "Bristol City": ("布里斯托尔城", []),
    "Burnley": ("伯恩利", []),
    "Cardiff City": ("卡迪夫城", []),
    "Charlton Athletic": ("查尔顿", []),
    "Derby County": ("德比郡", []),
    "Lincoln City": ("林肯城", []),
    "Middlesbrough": ("米德尔斯堡", []),
    "Millwall": ("米尔沃尔", []),
    "Norwich City": ("诺维奇", []),
    "Portsmouth": ("朴茨茅斯", []),
    "Preston North End": ("普雷斯顿", []),
    "Queens Park Rangers": ("女王公园巡游者", ["QPR"]),
    "Sheffield United": ("谢菲尔德联", ["谢菲联"]),
    "Southampton": ("南安普顿", []),
    "Stoke City": ("斯托克城", []),
    "Swansea City": ("斯旺西", []),
    "Watford": ("沃特福德", []),
    "West Bromwich Albion": ("西布罗姆维奇", ["西布朗"]),
    "West Ham United": ("西汉姆联", ["西汉姆"]),
    "Wolverhampton Wanderers": ("狼队", ["伍尔弗汉普顿"]),
    "Wrexham": ("雷克斯汉姆", []),
    # 欧冠 / 欧联杯补充球队
    "AEK Athens": ("雅典AEK", []),
    "Bodo/Glimt": ("博多格林特", ["博德闪耀"]),
    "Club Brugge": ("布鲁日", []),
    "FC Porto": ("波尔图", []),
    "Fenerbahce": ("费内巴切", []),
    "Feyenoord Rotterdam": ("费耶诺德", []),
    "Galatasaray": ("加拉塔萨雷", []),
    "LASK Linz": ("LASK林茨", ["林茨"]),
    "PSV Eindhoven": ("埃因霍温", ["PSV"]),
    "Sabah FK": ("萨巴巴", []),
    "Shakhtar Donetsk": ("顿涅茨克矿工", ["矿工"]),
    "Slavia Prague": ("布拉格斯拉维亚", []),
    "Slovan Bratislava": ("布拉迪斯拉发斯洛万", []),
    "Sporting CP": ("葡萄牙体育", ["里斯本竞技"]),
    "VIKING FK": ("维京", []),
    "AZ Alkmaar": ("阿尔克马尔", ["AZ"]),
    "Anderlecht": ("安德莱赫特", []),
    "Ararat-Armenia": ("亚美尼亚阿拉拉特", []),
    "Benfica": ("本菲卡", []),
    "Besiktas": ("贝西克塔斯", []),
    "Celtic": ("凯尔特人", []),
    "Dinamo Zagreb": ("萨格勒布迪纳摩", []),
    "Ferencvaros": ("费伦茨瓦罗斯", []),
    "Hapoel Be'er": ("贝尔谢巴夏普尔", []),
    "Jagiellonia Bialystok": ("比亚韦斯托克雅盖隆", []),
    "Lech Poznan": ("波兹南莱赫", []),
    "Levski Sofia": ("索菲亚列夫斯基", []),
    "Lillestrom": ("利勒斯特罗姆", []),
    "NEC Nijmegen": ("奈梅亨", []),
    "NK Celje": ("采列", []),
    "OFI Crete": ("克里特OFI", []),
    "Olympiacos": ("奥林匹亚科斯", []),
    "Omonia Nicosia": ("尼科西亚奥莫尼亚", []),
    "RB Salzburg": ("萨尔茨堡红牛", ["萨尔茨堡"]),
    "SK Sturm Graz": ("格拉茨风暴", []),
    "Sparta Prague": ("布拉格斯巴达", []),
    "Torreense": ("托里恩塞", []),
    "Union St.-Gilloise": ("圣吉尔联合", []),
    "Viktoria Plzen": ("比尔森胜利", []),
    # 巴西甲
    "Athletico-PR": ("巴拉纳竞技", []),
    "Atlético-MG": ("米内罗竞技", []),
    "Bahia": ("巴伊亚", []),
    "Botafogo": ("博塔弗戈", []),
    "Chapecoense": ("沙佩科恩斯", []),
    "Corinthians": ("科林蒂安", []),
    "Coritiba": ("科里蒂巴", []),
    "Cruzeiro": ("克鲁塞罗", []),
    "Flamengo": ("弗拉门戈", []),
    "Fluminense": ("弗鲁米嫩塞", []),
    "Grêmio": ("格雷米奥", []),
    "Internacional": ("巴西国际", []),
    "Mirassol": ("米拉索尔", []),
    "Palmeiras": ("帕尔梅拉斯", []),
    "Red Bull Bragantino": ("布拉甘蒂诺红牛", ["布拉甘蒂诺"]),
    "Remo": ("雷莫", []),
    "Santos": ("桑托斯", []),
    "São Paulo": ("圣保罗", []),
    "Vasco da Gama": ("瓦斯科达伽马", ["瓦斯科"]),
    "Vitória": ("维多利亚", []),
    "Juventude": ("尤文图德", []),
    "Ceará": ("塞阿拉", []),
    "Sport Recife": ("累西腓体育", ["累西腓"]),
    "Fortaleza": ("福塔莱萨", []),
    "Atlético Goianiense": ("戈亚尼亚竞技", []),
    "Cuiabá": ("库亚巴", []),
    "Criciúma": ("克里西乌马", []),
    # 杯赛常见对手（英格兰低级别）
    "AFC Wimbledon": ("AFC温布尔登", []),
    "Barnsley": ("巴恩斯利", []),
    "Blackpool": ("布莱克浦", []),
    "Bradford City": ("布拉德福德城", []),
    "Bromley": ("布罗姆利", []),
    "Cambridge United": ("剑桥联", []),
    "Doncaster Rovers": ("唐卡斯特流浪者", []),
    "Exeter City": ("埃克塞特城", []),
    "Grimsby Town": ("格里姆斯比镇", []),
    "Huddersfield Town": ("哈德斯菲尔德", []),
    "Luton Town": ("卢顿", []),
    "Macclesfield FC": ("麦克尔斯菲尔德", []),
    "Mansfield Town": ("曼斯菲尔德镇", []),
    "Oxford United": ("牛津联", []),
    "Plymouth Argyle": ("普利茅斯", []),
    "Port Vale": ("维尔港", []),
    "Reading": ("雷丁", []),
    "Salford City": ("索尔福德城", []),
    "Sheffield Wednesday": ("谢周三", []),
    "Wigan Athletic": ("维冈竞技", []),
    "Wycombe Wanderers": ("韦康比流浪者", []),
}

CN.update({
    # ESPN 使用的名称与常见译名不同，单独映射
    "VfL Wolfsburg": ("沃尔夫斯堡", ["狼堡"]),
    "St. Pauli": ("圣保利", []),
    "Nantes": ("南特", []),
    "Metz": ("梅斯", []),
    "1. FC Heidenheim 1846": ("海登海姆", []),
    "Ajax Amsterdam": ("阿贾克斯", []),
    "Braga": ("布拉加", []),
    "Young Boys": ("年轻人", []),
    "Ludogorets Razgrad": ("卢多戈雷茨", []),
    "Malmö FF": ("马尔默", []),
    "Kairat Almaty": ("阿拉木图凯拉特", []),
    "FCSB": ("布加勒斯特星", []),
    "Maccabi Tel-Aviv": ("特拉维夫马卡比", []),
    "FK Qarabag": ("卡拉巴赫", []),
    "F.C. København": ("哥本哈根", []),
    "Dynamo Kyiv": ("基辅迪纳摩", []),
    "Racing Genk": ("亨克", []),
    "FC Twente": ("特温特", []),
    "Go Ahead Eagles": ("前进之鹰", []),
    "FC Utrecht": ("乌得勒支", []),
    "Pafos": ("帕福斯", []),
    "SK Brann": ("布兰", []),
    "IF Elfsborg": ("埃尔夫斯堡", []),
    "Rigas Futbola Skola": ("里加足球学校", []),
    # 英格兰低级别球队
    "AFC Wimbledon": ("温布尔登竞技", []),
    "Barrow": ("巴罗", []),
    "Bromley": ("布罗姆利", []),
    "Colchester United": ("科尔切斯特联", []),
    "Crawley Town": ("克劳利镇", []),
    "Exeter City": ("埃克塞特城", []),
    "Fleetwood Town": ("弗利特伍德", []),
    "Harrogate Town": ("哈罗盖特", []),
    "Newport County": ("纽波特郡", []),
    "Northampton Town": ("北安普顿", []),
    "Notts County": ("诺茨郡", []),
    "Oldham Athletic": ("奥尔德姆", []),
    "Rotherham United": ("罗瑟汉姆", []),
    "Shrewsbury Town": ("什鲁斯伯里", []),
    "Stevenage": ("斯蒂夫尼奇", []),
    "Swindon Town": ("斯温登", []),
    "Walsall": ("沃尔索尔", []),
    "Burton Albion": ("伯顿阿尔比恩", []),
    # 德国低级别球队
    "Arminia Bielefeld": ("比勒费尔德", []),
    "VfL Bochum": ("波鸿", []),
    "VfL Osnabruck": ("奥斯纳布吕克", []),
    "TSV Eintracht Braunschweig": ("不伦瑞克", []),
    "SV Darmstadt 98": ("达姆施塔特", []),
    "SV Wehen Wiesbaden": ("韦恩威斯巴登", []),
    "SV Sandhausen": ("桑德豪森", []),
    "SSV Ulm 1846": ("乌尔姆", []),
    "SSV Jahn Regensburg": ("雷根斯堡", []),
    "Hertha Berlin": ("柏林赫塔", []),
    "Hansa Rostock": ("汉莎罗斯托克", []),
    "Hallescher FC": ("哈勒", []),
    "Fortuna Düsseldorf": ("杜塞尔多夫", []),
    "Energie Cottbus": ("科特布斯", []),
    "Dynamo Dresden": ("德累斯顿迪纳摩", []),
    "Rot-Weiss Essen": ("红白埃森", []),
    "Karlsruher SC": ("卡尔斯鲁厄", []),
    "MSV Duisburg": ("杜伊斯堡", []),
    "FC Erzgebirge Aue": ("奥厄", []),
    "1. FC Magdeburg": ("马格德堡", []),
    "1. FC Lokomotive Leipzig": ("莱比锡火车头", []),
    "1. FC Phönix Lübeck": ("吕贝克凤凰", []),
    "Viktoria Köln": ("科隆维多利亚", []),
    # 西班牙低级别球队
    "Albacete": ("阿尔瓦塞特", []),
    "Burgos": ("布尔戈斯", []),
    "Cultural Leonesa": ("莱昂内萨", []),
    "Sporting Gijón": ("希洪竞技", []),
    "Real Murcia": ("穆尔西亚", []),
    "Eibar": ("埃瓦尔", []),
    "Huesca": ("韦斯卡", []),
    "Ponferradina": ("蓬费拉迪纳", []),
    "CD Sabadell": ("萨瓦德尔", []),
    "CD Extremadura": ("埃斯特雷马杜拉", []),
    "FC Cartagena": ("卡塔赫纳", []),
    "Eldense": ("埃尔登塞", []),
    "Atlético Baleares": ("巴利阿里竞技", []),
    # 意大利低级别球队
    "Palermo": ("巴勒莫", []),
    "Pescara": ("佩斯卡拉", []),
    "Bari": ("巴里", []),
    "Bastia": ("巴斯蒂亚", []),
    "Benevento": ("贝内文托", []),
    "Catania": ("卡塔尼亚", []),
    "Cesena": ("切塞纳", []),
    "Ascoli": ("阿斯科利", []),
    "Arezzo": ("阿雷佐", []),
    "Vicenza": ("维琴察", []),
    "Padova": ("帕多瓦", []),
    "Modena": ("摩德纳", []),
    "Mantova": ("曼托瓦", []),
    "Carrarese": ("卡拉雷塞", []),
    "Juve Stabia": ("尤维斯塔比亚", []),
    "Sudtirol": ("南蒂罗尔", []),
    "Virtus Entella": ("恩特拉", []),
    "US Avellino": ("阿韦利诺", []),
    "Catanzaro": ("卡坦扎罗", []),
    # 法国低级别球队
    "SC Amiens": ("亚眠", []),
    "Saint-Étienne": ("圣埃蒂安", []),
    "Sochaux": ("索肖", []),
    "Orléans": ("奥尔良", []),
    "Avranches": ("阿夫朗什", []),
    "Stade Laval": ("拉瓦勒", []),
    "Dunkerque": ("敦刻尔克", []),
    "AS Nancy Lorraine": ("南锡", []),
    # 巴西低级别球队
    "Paysandu": ("帕桑杜", []),
    "Operário PR": ("巴拉那奥佩拉里奥", []),
    "Novorizontino": ("新奥里藏特", []),
    "Goiás": ("戈亚斯", []),
    "CSA": ("阿拉戈阿诺", []),
    "CRB": ("雷加塔斯", []),
    "Náutico": ("瑙蒂科", []),
    "Vila Nova": ("维拉诺瓦", []),
    "Maringá": ("马林加", []),
    "Brusque": ("布鲁斯克", []),
    "Confiança": ("孔菲安萨", []),
    "Botafogo PB": ("帕拉伊巴博塔弗戈", []),
    "Aparecidense": ("阿帕雷西登塞", []),
    "Jacuipense": ("雅库伊彭塞", []),
    "Retró": ("雷特罗", []),
    "Barra FC": ("巴拉", []),
    "Athletic": ("阿蒂莱蒂克MG", []),
    "Sport": ("累西腓体育", []),
    "Sousa EC": ("索萨", []),
    "Aguia de Maraba": ("马拉巴老鹰", []),
    "Leyton Orient": ("莱顿东方", []),
    "Stade Briochin": ("布列塔尼体育场", []),
    "Sampdoria": ("桑普多利亚", []),
    "Pontevedra": ("蓬特韦德拉", []),
    "Ourense CF": ("奥伦塞", []),
    "Peterborough United": ("彼得堡联", []),
    "Milton Keynes Dons": ("米尔顿凯恩斯", []),
})

STAT_KEYS = [
    ("shots", "totalShots"),
    ("sot", "shotsOnTarget"),
    ("corners", "wonCorners"),
    ("offsides", "offsides"),
    ("yellow", "yellowCards"),
    ("red", "redCards"),
    ("fouls", "foulsCommitted"),
    ("possession", "possessionPct"),
    ("blocked", "blockedShots"),
    ("saves", "saves"),
]

_print_lock = threading.Lock()
_meta_lock = threading.Lock()
TEAM_META = {}


def log(msg):
    with _print_lock:
        print(msg, file=sys.stderr, flush=True)


_CN_EXTRA_DONE = False


def merge_cn_extra():
    """把 team_cn_extra.json 里的补充中文队名并进 CN（懒加载，只做一次）。"""
    global _CN_EXTRA_DONE
    if _CN_EXTRA_DONE:
        return 0
    _CN_EXTRA_DONE = True
    path = os.path.join(ROOT, "team_cn_extra.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0
    added = 0
    for name, cn in data.items():
        if name and cn and name not in CN:
            CN[name] = (cn, [])
            added += 1
    return added


def remember_team(t):
    """记录赛程/比分板里出现的球队元数据（含历史对手）。"""
    if not t or not t.get("id"):
        return
    tid = str(t["id"])
    with _meta_lock:
        if tid in TEAM_META:
            return
        TEAM_META[tid] = {
            "id": tid,
            "name": t.get("displayName") or t.get("name") or tid,
            "short": t.get("shortDisplayName") or t.get("displayName") or tid,
            "abbr": t.get("abbreviation") or "",
            "color": (t.get("color") or "").lstrip("#"),
            "alt": (t.get("alternateColor") or "").lstrip("#"),
            "location": t.get("location") or "",
        }


def ensure_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)


def read_cache(name, max_age=None):
    path = os.path.join(CACHE_DIR, name)
    if not os.path.exists(path):
        return None
    if max_age is not None and time.time() - os.path.getmtime(path) > max_age:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_cache(name, obj):
    path = os.path.join(CACHE_DIR, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


RATE_LOCK = threading.Lock()
RATE_STATE = {"interval": 0.0, "last": 0.0}


def throttle():
    interval = RATE_STATE["interval"]
    if interval <= 0:
        return
    with RATE_LOCK:
        now = time.time()
        wait = RATE_STATE["last"] + interval - now
        if wait > 0:
            time.sleep(wait)
            now = time.time()
        RATE_STATE["last"] = now


def get_json(url, tries=6, timeout=30):
    last = None
    for i in range(tries):
        try:
            throttle()
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://www.espn.com/",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429, 500, 502, 503, 504):
                time.sleep(3 * (i + 1))
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"请求失败 {url}: {last}")


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def score_value(side):
    s = (side or {}).get("score")
    if isinstance(s, dict):
        return to_int(s.get("value"))
    return to_int(s)


def to_float(v):
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def fetch_teams(league, refresh=False):
    name = f"teams_{league['code']}.json"
    cached = None if refresh else read_cache(name, max_age=6 * 3600)
    if cached is not None:
        return cached
    d = get_json(f"{API}/{league['code']}/teams?limit=60")
    teams = []
    for item in d["sports"][0]["leagues"][0]["teams"]:
        t = item["team"]
        teams.append({
            "id": str(t["id"]),
            "name": t.get("displayName") or t.get("name"),
            "short": t.get("shortDisplayName") or t.get("displayName"),
            "abbr": t.get("abbreviation") or "",
            "color": (t.get("color") or "").lstrip("#"),
            "alt": (t.get("alternateColor") or "").lstrip("#"),
            "location": t.get("location") or "",
        })
    write_cache(name, teams)
    return teams


def extract_teams_meta(d):
    out = []
    for e in d.get("events", []):
        for c in (e.get("competitions") or [])[:1]:
            for t in c.get("competitors", []):
                if t.get("team"):
                    out.append(t["team"])
    return out


def parse_schedule(d, league, season):
    out = []
    for e in d.get("events", []):
        comps = e.get("competitions") or []
        if not comps:
            continue
        c = comps[0]
        status = (c.get("status") or {}).get("type") or {}
        home = away = None
        for t in c.get("competitors", []):
            remember_team(t.get("team"))
            if t.get("homeAway") == "home":
                home = t
            elif t.get("homeAway") == "away":
                away = t
        if not home or not away:
            continue
        hs = score_value(home)
        as_ = score_value(away)
        so_h = home.get("shootoutScore")
        so_a = away.get("shootoutScore")
        out.append({
            "id": str(e["id"]),
            "date": e.get("date"),
            "league": league["label"],
            "leagueCode": league["code"],
            "season": season,
            "completed": bool(status.get("completed")),
            "state": status.get("state") or "",
            "home": str(home["team"]["id"]),
            "away": str(away["team"]["id"]),
            "hs": to_int(hs),
            "as": to_int(as_),
            "so": [to_int(so_h), to_int(so_a)] if so_h is not None and so_a is not None else None,
            "neutral": bool(c.get("neutralSite")),
            "venue": ((c.get("venue") or {}).get("fullName")) or "",
            "attendance": to_int(c.get("attendance")),
        })
    return out


def fetch_schedule(league, team_id, season, refresh=False):
    name = f"sched_{league['code']}_{team_id}_{season}.json"
    current = season >= CURRENT_SEASON
    cached = None if refresh else read_cache(name, max_age=(6 * 3600 if current else None))
    if cached is not None:
        if isinstance(cached, dict):
            for t in cached.get("teams", []):
                remember_team(t)
            return cached.get("rows", [])
        return cached
    url = f"{API}/{league['code']}/teams/{team_id}/schedule?season={season}"
    try:
        d = get_json(url)
    except Exception as e:
        log(f"  赛程失败 {league['label']} {team_id} {season}: {e}")
        return []
    metas = extract_teams_meta(d)
    for t in metas:
        remember_team(t)
    rows = parse_schedule(d, league, season)
    write_cache(name, {"rows": rows, "teams": metas})
    return rows


def parse_scoreboard(d, league):
    out = []
    for e in d.get("events", []):
        comps = e.get("competitions") or []
        if not comps:
            continue
        c = comps[0]
        status = (c.get("status") or {}).get("type") or {}
        home = away = None
        for t in c.get("competitors", []):
            remember_team(t.get("team"))
            if t.get("homeAway") == "home":
                home = t
            elif t.get("homeAway") == "away":
                away = t
        if not home or not away:
            continue
        out.append({
            "id": str(e["id"]),
            "date": e.get("date"),
            "league": league["label"],
            "leagueCode": league["code"],
            "season": None,
            "completed": bool(status.get("completed")),
            "state": status.get("state") or "",
            "home": str(home["team"]["id"]),
            "away": str(away["team"]["id"]),
            "hs": score_value(home),
            "as": score_value(away),
            "so": None,
            "neutral": bool(c.get("neutralSite")),
            "venue": ((c.get("venue") or {}).get("fullName")) or "",
            "attendance": to_int(c.get("attendance")),
        })
    return out


def fetch_scoreboard(league, date_str, refresh=False):
    name = f"sb_{league['code']}_{date_str}.json"
    cached = None if refresh else read_cache(name, max_age=3600)
    if cached is not None:
        if isinstance(cached, dict):
            for t in cached.get("teams", []):
                remember_team(t)
            return cached.get("rows", [])
        return cached
    try:
        d = get_json(f"{API}/{league['code']}/scoreboard?dates={date_str}")
    except Exception as e:
        log(f"  比分板失败 {league['label']} {date_str}: {e}")
        return []
    metas = extract_teams_meta(d)
    for t in metas:
        remember_team(t)
    rows = parse_scoreboard(d, league)
    write_cache(name, {"rows": rows, "teams": metas})
    return rows


def extract_summary_stats(d):
    box = (d.get("boxscore") or {}).get("teams") or []
    stats = {}
    for t in box:
        side = t.get("homeAway")
        if side not in ("home", "away"):
            continue
        raw = {s.get("name"): s.get("displayValue") for s in (t.get("statistics") or [])}
        item = {}
        for key, src in STAT_KEYS:
            if key == "possession":
                item[key] = to_float(raw.get(src))
            else:
                item[key] = to_int(raw.get(src))
        stats[side] = item
    if len(stats) != 2:
        return None
    if all(v is None for item in stats.values() for v in item.values()):
        return None
    # 部分老比赛接口只返回全零占位，视为无统计
    if not any(item.get("shots") for item in stats.values()):
        return None
    return stats


def fetch_core_stats(league_code, event_id, team_id):
    """site 接口对部分杯赛不返回 boxscore，改从核心接口取单队统计。"""
    url = (f"{CORE}/leagues/{league_code}/events/{event_id}/competitions/{event_id}"
           f"/competitors/{team_id}/statistics?lang=en&region=us")
    try:
        d = get_json(url)
    except Exception:
        return None
    raw = {}
    for cat in (d.get("splits") or {}).get("categories", []):
        for s in cat.get("stats", []):
            if s.get("name"):
                raw[s["name"]] = s.get("value")
    item = {}
    for key, src in STAT_KEYS:
        item[key] = to_float(raw.get(src)) if key == "possession" else to_int(raw.get(src))
    return item


def stats_from_core(league_code, event_id, home_id, away_id):
    h = fetch_core_stats(league_code, event_id, home_id)
    a = fetch_core_stats(league_code, event_id, away_id)
    if not h or not a:
        return None
    if not any([h.get("shots"), a.get("shots")]):
        return None
    return {"home": h, "away": a}


def stats_for_summary(league_code, event_id, d):
    stats = extract_summary_stats(d)
    if stats:
        return stats
    comps = (d.get("header") or {}).get("competitions") or []
    if not comps:
        return None
    hid = aid = None
    for t in comps[0].get("competitors", []):
        tid = (t.get("team") or {}).get("id") or t.get("id")
        if t.get("homeAway") == "home":
            hid = tid
        elif t.get("homeAway") == "away":
            aid = tid
    if not hid or not aid:
        return None
    return stats_from_core(league_code, event_id, hid, aid)


def fetch_summary(league_code, event_id):
    name = f"sum_{league_code}_{event_id}.json"
    cached = read_cache(name)
    if cached is not None and "stats" in cached:
        if cached.get("stats"):
            return cached
        # 无统计的场次负缓存 7 天；请求失败的只缓存 6 小时
        path = os.path.join(CACHE_DIR, name)
        limit = 6 * 3600 if cached.get("err") else 7 * 86400
        if time.time() - os.path.getmtime(path) < limit:
            return cached
    try:
        d = get_json(f"{API}/{league_code}/summary?event={event_id}")
    except Exception as e:
        log(f"  统计失败 {event_id}: {e}")
        write_cache(name, {"ok": False, "stats": None, "err": True})
        return None
    stats = stats_for_summary(league_code, event_id, d)
    write_cache(name, {"ok": bool(stats), "stats": stats})
    return {"ok": bool(stats), "stats": stats}


def american_to_decimal(ml):
    """美式赔率转欧洲小数赔率。"""
    try:
        v = float(ml)
    except (TypeError, ValueError):
        return None
    if v == 0:
        return None
    return round(1 + (v / 100 if v > 0 else 100 / -v), 2)


def parse_odds(d):
    """从 summary 的 pickcenter 提取欧赔、亚盘、大小球。

    pickcenter 可能挂多家供应商，也可能首条缺少胜平负（冷门杯赛常只挂单边盘）。
    按顺序取第一条三项齐全的记录，而不是盲取第一条。
    """
    books = []
    for p in (d.get("pickcenter") or []):
        home = p.get("homeTeamOdds") or {}
        away = p.get("awayTeamOdds") or {}
        draw = p.get("drawOdds") or {}
        ml = {
            "h": american_to_decimal(home.get("moneyLine")),
            "d": american_to_decimal(draw.get("moneyLine")),
            "a": american_to_decimal(away.get("moneyLine")),
        }
        if not all(ml.values()):
            continue
        books.append({
            "provider": ((p.get("provider") or {}).get("name")) or "",
            "ml": ml,
            "ah": {
                "line": p.get("spread"),
                "h": american_to_decimal(home.get("spreadOdds")),
                "a": american_to_decimal(away.get("spreadOdds")),
            } if p.get("spread") is not None else None,
            "ou": {
                "line": p.get("overUnder"),
                "over": american_to_decimal(p.get("overOdds")),
                "under": american_to_decimal(p.get("underOdds")),
            } if p.get("overUnder") is not None else None,
        })
    if not books:
        return None
    out = books[0]
    out["books"] = len(books)
    out["fetchedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return out


def fetch_odds(league_code, event_id):
    """赔率时效短，单独缓存 1 小时；同时保留赛前快照用于赛后回测。"""
    name = f"odds_{league_code}_{event_id}.json"
    path = os.path.join(CACHE_DIR, name)
    raw = read_cache(name)
    if raw is not None and time.time() - os.path.getmtime(path) < 3600:
        return raw.get("odds")
    history = (raw or {}).get("history") or []
    try:
        d = get_json(f"{API}/{league_code}/summary?event={event_id}")
    except Exception as e:
        log(f"  赔率失败 {event_id}: {e}")
        return (raw or {}).get("odds")
    odds = parse_odds(d)
    if odds:
        ml = odds.get("ml") or {}
        if all(ml.get(k) for k in ("h", "d", "a")):
            inv = [1 / ml["h"], 1 / ml["d"], 1 / ml["a"]]
            total = sum(inv)
            snap = {
                "t": datetime.now().astimezone().isoformat(timespec="minutes"),
                "p": [round(x / total, 3) for x in inv],
            }
            if not history or history[-1].get("p") != snap["p"]:
                history.append(snap)
                history = history[-8:]
        write_cache(name, {"odds": odds, "history": history})
    return odds


ODDS_SNAP_DIR = os.path.join(ROOT, "odds_snapshots")
ODDS_SNAP_MAX = 6        # 每个事件最多保留的快照条数，控制仓库体积
ODDS_SNAP_MONTHS = 3     # 回读最近几个月作为回测依据
ODDS_SNAP_MOVE = 0.01    # 去水概率变化超过此阈值才追加新快照
_ODDS_SNAP_INDEX = {}


def _snap_months(n=ODDS_SNAP_MONTHS):
    d = date.today().replace(day=1)
    out = []
    for _ in range(n):
        out.append(f"{d.year:04d}-{d.month:02d}")
        d = (d - timedelta(days=1)).replace(day=1)
    return out


def _snap_probs(o):
    ml = [o.get("h"), o.get("d"), o.get("a")]
    if not all(ml):
        return None
    inv = [1 / v for v in ml]
    s = sum(inv)
    return [x / s for x in inv]


def _load_snapshot_state():
    """回读仓库内全部快照，返回 (事件→最后一条, 事件→已存条数)。"""
    last, counts = {}, {}
    for key in _snap_months():
        path = os.path.join(ODDS_SNAP_DIR, key + ".jsonl")
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                eid = str(o.get("e") or "")
                if eid:
                    last[eid] = o
                    counts[eid] = counts.get(eid, 0) + 1
    return last, counts


def load_odds_snapshots():
    """读取赛前赔率快照索引（eventId → 最后一条），供回测使用。"""
    return _load_snapshot_state()[0]


def write_odds_snapshots(events, odds_map):
    """把本次采集到的赛前盘口追加到 odds_snapshots/YYYY-MM.jsonl。

    追加式写入，避免每天重写整个文件造成仓库抖动。同一事件只在首次出现、
    赔率变化超过阈值或盘口线变动时追加，且每个事件最多保留 ODDS_SNAP_MAX 条。
    """
    if not odds_map:
        return 0
    os.makedirs(ODDS_SNAP_DIR, exist_ok=True)
    last, counts = _load_snapshot_state()
    path = os.path.join(ODDS_SNAP_DIR, date.today().strftime("%Y-%m") + ".jsonl")
    now = datetime.now().astimezone().isoformat(timespec="minutes")
    lines = []
    for eid, od in odds_map.items():
        if not od:
            continue
        ml = od.get("ml") or {}
        if not all(ml.get(k) for k in ("h", "d", "a")):
            continue
        ev = events.get(eid) or {}
        ko_day = parse_match_date(ev.get("date"))
        # 防御：只保留真正赛前的盘口。跨天后 ESPN 仍可能返回残留赔率，
        # 一旦写入就会污染回测，因此开赛日期早于今天的一律丢弃。
        if ko_day is not None and ko_day < date.today():
            continue
        snap = {
            "e": str(eid),
            "lg": ev.get("league"),
            "ko": ev.get("date"),
            "t": now,
            "h": ml["h"], "d": ml["d"], "a": ml["a"],
        }
        ah = od.get("ah") or {}
        if ah.get("line") is not None:
            snap["ah"] = [ah.get("line"), ah.get("h"), ah.get("a")]
        ou = od.get("ou") or {}
        if ou.get("line") is not None:
            snap["ou"] = [ou.get("line"), ou.get("over"), ou.get("under")]
        prev = last.get(str(eid))
        n = counts.get(str(eid), 0)
        if prev is not None:
            if n >= ODDS_SNAP_MAX:
                continue
            p0, p1 = _snap_probs(prev), _snap_probs(snap)
            changed = bool(p0 and p1 and
                           max(abs(a - b) for a, b in zip(p0, p1)) >= ODDS_SNAP_MOVE)
            if (prev.get("ah") or [None])[0] != (snap.get("ah") or [None])[0]:
                changed = True
            if (prev.get("ou") or [None])[0] != (snap.get("ou") or [None])[0]:
                changed = True
            if not changed:
                continue
        lines.append(json.dumps(snap, ensure_ascii=False, separators=(",", ":")))
        counts[str(eid)] = n + 1
        last[str(eid)] = snap
    if lines:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return len(lines)


def odds_market_probs(league_code, event_id):
    """读取赛前盘口的去水概率（供已结束比赛回测综合预测）。

    先用采集缓存（最近一次抓到的赔率），缓存缺失时回落到仓库内的快照，
    使回测样本不受 CI 缓存淘汰影响。
    """
    raw = read_cache(f"odds_{league_code}_{event_id}.json")
    if raw:
        ml = (raw.get("odds") or {}).get("ml") or {}
        if all(ml.get(k) for k in ("h", "d", "a")):
            inv = [1 / ml["h"], 1 / ml["d"], 1 / ml["a"]]
            total = sum(inv)
            return [round(x / total, 3) for x in inv]
    snap = _ODDS_SNAP_INDEX.get(str(event_id))
    if snap:
        probs = _snap_probs(snap)
        if probs:
            return [round(x, 3) for x in probs]
    return None


def fetch_lineup(league_code, event_id):
    """抓取一场比赛的首发名单（已结束比赛才有）。"""
    name = f"lineup_{league_code}_{event_id}.json"
    cached = read_cache(name)
    if cached is not None:
        lineups = cached.get("lineups") or {}
        if lineups:
            return lineups
        path = os.path.join(CACHE_DIR, name)
        if time.time() - os.path.getmtime(path) < 86400:
            return {}
    try:
        d = get_json(f"{API}/{league_code}/summary?event={event_id}")
    except Exception:
        return {}
    out = {}
    for t in d.get("rosters") or []:
        team = t.get("team") or {}
        tid = team.get("id") or t.get("teamId")
        if not tid:
            continue
        players = []
        for p in t.get("roster") or []:
            if not p.get("starter"):
                continue
            ath = p.get("athlete") or {}
            nm = ath.get("displayName") or p.get("displayName") or ""
            if not nm:
                continue
            pos = ((p.get("position") or {}).get("abbreviation")) or ""
            players.append({"n": nm, "j": p.get("jersey") or "", "p": pos})
        if players:
            out[str(tid)] = {
                "formation": t.get("formation") or "",
                "players": players[:11],
            }
    write_cache(name, {"lineups": out})
    return out


POS_ORDER = {"G": 0, "GK": 0, "D": 1, "CB": 1, "LB": 1, "RB": 1, "WB": 1,
             "M": 2, "CDM": 2, "CM": 2, "CAM": 2, "LM": 2, "RM": 2,
             "F": 3, "ST": 3, "CF": 3, "LW": 3, "RW": 3}


def build_team_lineups(match_rows, team_ids, workers):
    """按最近 3 场首发频率，推算每队参考阵容。"""
    recent = defaultdict(list)
    for m in match_rows:
        for tid in (m["home"], m["away"]):
            if tid in team_ids and len(recent[tid]) < 3:
                recent[tid].append(m)
    jobs = {(m["leagueCode"], m["id"]) for ms in recent.values() for m in ms}
    log(f"  首发名单：{len(recent)} 队，{len(jobs)} 场近期比赛")
    fetched = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_lineup, code, eid): (code, eid) for code, eid in jobs}
        for fut in as_completed(futs):
            fetched[futs[fut]] = fut.result()
    out = {}
    total = named = 0
    for tid, ms in recent.items():
        weights = [1.0, 0.65, 0.4][:len(ms)]
        score = {}
        info = {}
        formation = ""
        for m, w in zip(ms, weights):
            lu = (fetched.get((m["leagueCode"], m["id"])) or {}).get(tid)
            if not lu:
                continue
            if not formation:
                formation = lu.get("formation") or ""
            for p in lu.get("players", []):
                key = p["n"]
                score[key] = score.get(key, 0) + w
                info[key] = p
        if not score:
            continue
        picks = sorted(score, key=lambda k: -score[k])[:11]
        picks.sort(key=lambda k: (POS_ORDER.get(info[k]["p"], 2), -score[k]))
        total += len(picks)
        named += sum(1 for k in picks if PLAYER_CN.get(info[k]["n"]))
        out[tid] = {
            "f": formation,
            "p": [{
                "n": player_cn(info[k]["n"]),
                "en": info[k]["n"],
                "j": info[k].get("j", ""),
                "p": info[k].get("p", ""),
            } for k in picks],
            "from": (ms[0]["date"] or "")[:10],
        }
    if total:
        log(f"  阵容译名覆盖 {named}/{total}")
    return out


def _load_player_cn():
    path = os.path.join(ROOT, "player_cn.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


PLAYER_CN = _load_player_cn()


def player_cn(name):
    return PLAYER_CN.get(name) or name


RATING_LEAGUES = {"eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "eng.2", "bra.1"}

# 欧战球队的国内联赛（仅 ESPN 公开可用的联赛）；标签用于页面显示
EURO_DOMESTIC = {
    "aut.1": "奥甲",
    "bel.1": "比甲",
    "gre.1": "希腊超",
    "ned.1": "荷甲",
    "nor.1": "挪超",
    "por.1": "葡超",
    "sco.1": "苏超",
    "tur.1": "土超",
    # 以下经 ESPN 联赛目录核对确认可用；波甲、捷甲、克甲、以超、保甲、罗甲、
    # 塞甲、瑞士超、乌超、匈甲等代码在 ESPN 站点接口并不存在（请求返回 400），
    # 加入只会产生无效请求，故不收录。
    "den.1": "丹超",
    "ger.2": "德乙",
    "swe.1": "瑞超",
}


ALL_LEAGUES = {
    "uefa.champions": ("欧冠", "uefa.champions"),
    "uefa.champions_qual": ("欧冠资格赛", "uefa.champions_qual"),
    "uefa.europa": ("欧联杯", "uefa.europa"),
    "uefa.europa_qual": ("欧联杯资格赛", "uefa.europa_qual"),
    "uefa.conference": ("欧协联", "uefa.conference"),
    "uefa.conference_qual": ("欧协联资格赛", "uefa.conference_qual"),
}


def parse_all_schedule(d, season):
    """解析 all/teams/{id}/schedule，仅保留欧战与资格赛（不含友谊赛）。"""
    out = []
    for e in d.get("events") or []:
        slug = ((e.get("league") or {}).get("slug")) or ""
        if slug not in ALL_LEAGUES:
            continue
        label, code = ALL_LEAGUES[slug]
        comps = e.get("competitions") or []
        if not comps:
            continue
        c = comps[0]
        status = (c.get("status") or {}).get("type") or {}
        home = away = None
        for t in c.get("competitors", []):
            remember_team(t.get("team"))
            if t.get("homeAway") == "home":
                home = t
            elif t.get("homeAway") == "away":
                away = t
        if not home or not away:
            continue
        out.append({
            "id": str(e["id"]),
            "date": e.get("date"),
            "league": label,
            "leagueCode": code,
            "season": (e.get("season") or {}).get("year") or season,
            "completed": bool(status.get("completed")),
            "state": status.get("state") or "",
            "home": str(home["team"]["id"]),
            "away": str(away["team"]["id"]),
            "hs": score_value(home),
            "as": score_value(away),
            "so": None,
            "neutral": bool(c.get("neutralSite")),
            "venue": ((c.get("venue") or {}).get("fullName")) or "",
            "attendance": to_int(c.get("attendance")),
        })
    return out


def fetch_all_schedule(team_id, season, refresh=False):
    name = f"allsched_{team_id}_{season}.json"
    current = season >= CURRENT_SEASON
    cached = None if refresh else read_cache(name, max_age=(6 * 3600 if current else None))
    if cached is not None:
        if isinstance(cached, dict):
            for t in cached.get("teams", []):
                remember_team(t)
            return cached.get("rows", [])
        return cached
    try:
        d = get_json(f"{API}/all/teams/{team_id}/schedule?season={season}")
    except Exception as e:
        log(f"  跨赛事赛程失败 {team_id} {season}: {e}")
        return []
    metas = extract_teams_meta(d)
    for t in metas:
        remember_team(t)
    rows = parse_all_schedule(d, season)
    write_cache(name, {"rows": rows, "teams": metas})
    return rows


def fetch_team_league(team_id):
    """识别球队的国内联赛代码；欧战球队常见 defaultLeague 指向 uefa.*。"""
    name = f"teamlg_{team_id}.json"
    cached = read_cache(name)
    if cached is not None:
        return cached.get("league")
    try:
        d = get_json(f"{CORE}/teams/{team_id}")
    except Exception:
        return None
    ref = ((d.get("defaultLeague") or {}).get("$ref")) or ""
    code = ref.split("/leagues/")[-1].split("?")[0] if "/leagues/" in ref else ""
    if not code or code.startswith("uefa."):
        slug = d.get("slug") or ""
        prefix = slug.split(".")[0] if "." in slug else ""
        # slug 形如 tur.fenerbahce / por.porto；team.* 等无法识别
        if prefix and prefix not in ("team", "uefa"):
            code = f"{prefix}.1"
    if not code or code.startswith("uefa."):
        code = None
    write_cache(name, {"league": code})
    return code
RATING_HALF_LIFE = 300.0
RATING_SHRINK = 8.0

# 盘口输出网格：进球线 / 亚盘让球线 / 角球线
GRID_N = 11                       # 比分网格上限，保证 4.5 球线与亚盘尾部分量
GOAL_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
AH_LINES = (-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0)
CORNER_LINES = (6.5, 7.5, 8.5, 9.5, 10.5)
CORNER_PRIOR = 5.2                # 单队单场角球先验均值（主客同值，靠主客场分项拟合）
CORNER_SHRINK = 6.0               # 角球样本向先验收缩的权重
CORNER_DISP = 1.30                # 角球过散布系数：方差 ≈ 1.30 × 均值（低于泊松假设的 1.0）
GOAL_TOTAL_DAMP = 0.30            # 预期总进球向联赛基准收缩的强度（1=不收缩，0=完全收缩）


def _damp_total(lh, la, bh, ba):
    """把预期总进球向联赛基准收缩，同时保持主客比例。

    回测发现原始 λ 的总进球过度发散：预期 1.64 档实际 2.68、预期 4.43 档实际 2.96，
    大小球概率校准误差 11.9%，Brier 甚至不如「永远猜联赛平均值」。
    收缩到 0.30 后：方向命中 49.4%→50.4%，Brier 0.2044→0.2021，
    大小球校准误差 11.9%→3.5%，且按时间切分的样本外验证结论一致。
    """
    tot = lh + la
    if tot <= 0:
        return lh, la
    base = bh + ba
    new_tot = base + (tot - base) * GOAL_TOTAL_DAMP
    return lh * new_tot / tot, la * new_tot / tot


def parse_match_date(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def build_ratings(match_rows):
    """按联赛基准计算各队主客场攻防强度（时间衰减 + 向均值收缩）。"""
    today = date.today()
    lg_sum = defaultdict(lambda: {"w": 0.0, "hg": 0.0, "ag": 0.0})
    team_sum = defaultdict(lambda: defaultdict(lambda: {
        "wh": 0.0, "wa": 0.0, "hgf": 0.0, "hga": 0.0, "agf": 0.0, "aga": 0.0,
        "hn": 0, "an": 0,
    }))
    for m in match_rows:
        if m.get("leagueCode") not in RATING_LEAGUES:
            continue
        if m.get("hs") is None or m.get("as") is None:
            continue
        d = parse_match_date(m.get("date"))
        if not d:
            continue
        age = (today - d).days
        if age < 0 or age > 1200:
            continue
        w = 0.5 ** (age / RATING_HALF_LIFE)
        lg = m["leagueCode"]
        lg_sum[lg]["w"] += w
        lg_sum[lg]["hg"] += w * m["hs"]
        lg_sum[lg]["ag"] += w * m["as"]
        h = team_sum[m["home"]][lg]
        a = team_sum[m["away"]][lg]
        h["wh"] += w
        h["hgf"] += w * m["hs"]
        h["hga"] += w * m["as"]
        h["hn"] += 1
        a["wa"] += w
        a["agf"] += w * m["as"]
        a["aga"] += w * m["hs"]
        a["an"] += 1

    baselines = {}
    for lg, s in lg_sum.items():
        if s["w"] >= 20:
            baselines[lg] = {
                "bh": s["hg"] / s["w"],
                "ba": s["ag"] / s["w"],
            }

    k = RATING_SHRINK
    teams = {}
    for tid, by_lg in team_sum.items():
        lg = max(by_lg, key=lambda x: by_lg[x]["wh"] + by_lg[x]["wa"])
        s = by_lg[lg]
        base = baselines.get(lg)
        if not base:
            continue
        bh, ba = base["bh"], base["ba"]
        # 加权和向联赛均值收缩：分母 = 该场景的样本权重 + 先验权重 k
        dh, da = s["wh"] + k, s["wa"] + k
        teams[tid] = {
            "lg": lg,
            "bh": bh, "ba": ba,
            "HA": ((s["hgf"] + k * bh) / dh) / bh if bh else 1.0,
            "HD": ((s["hga"] + k * ba) / dh) / ba if ba else 1.0,
            "AA": ((s["agf"] + k * ba) / da) / ba if ba else 1.0,
            "AD": ((s["aga"] + k * bh) / da) / bh if bh else 1.0,
            "n": s["hn"] + s["an"],
        }
    return teams


def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _score_grid(lh, la, n=GRID_N):
    """带 Dixon-Coles 低比分修正的比分网格，已归一化。"""
    rho = -0.06
    grid = [[poisson_pmf(i, lh) * poisson_pmf(j, la) for j in range(n)] for i in range(n)]
    for i in (0, 1):
        for j in (0, 1):
            if i == 0 and j == 0:
                grid[i][j] *= 1 - lh * la * rho
            elif i == 0 and j == 1:
                grid[i][j] *= 1 + lh * rho
            elif i == 1 and j == 0:
                grid[i][j] *= 1 + la * rho
            else:
                grid[i][j] *= 1 - rho
    total = sum(sum(r) for r in grid)
    return [[v / total for v in row] for row in grid]


def _over_total(grid, line):
    """总进球大于某条半球线的概率（网格已归一化）。"""
    need = int(line + 0.5)
    n = len(grid)
    return sum(grid[i][j] for i in range(n) for j in range(n) if i + j >= need)


def _ah_home(grid, line):
    """主队让球盘（负数为让球）的有效赢盘概率，走盘按退还本金折算 0.5。"""
    frac = abs(line) % 1
    if abs(frac - 0.25) < 1e-9 or abs(frac - 0.75) < 1e-9:
        # 四分之一球盘拆成上下两条半球/整数线各半
        return 0.5 * (_ah_home(grid, line - 0.25) + _ah_home(grid, line + 0.25))
    n = len(grid)
    win = push = 0.0
    for i in range(n):
        for j in range(n):
            d = i - j + line
            if d > 1e-9:
                win += grid[i][j]
            elif d > -1e-9:
                push += grid[i][j]
    return win + push * 0.5


def poisson_probs(lh, la):
    grid = _score_grid(lh, la)
    n = len(grid)
    ph = sum(grid[i][j] for i in range(n) for j in range(n) if i > j)
    pd = sum(grid[i][i] for i in range(n))
    pa = max(0.0, 1 - ph - pd)
    lines = {f"{ln:.1f}": round(_over_total(grid, ln), 3) for ln in GOAL_LINES}
    ah = {f"{ln:g}": round(_ah_home(grid, ln), 3) for ln in AH_LINES}
    btts = sum(grid[i][j] for i in range(1, n) for j in range(1, n))
    tops = sorted(
        ((f"{i}-{j}", grid[i][j]) for i in range(5) for j in range(5)),
        key=lambda x: -x[1]
    )[:3]
    return {
        "xgH": round(lh, 2),
        "xgA": round(la, 2),
        "ph": round(ph, 3),
        "pd": round(pd, 3),
        "pa": round(pa, 3),
        "o25": lines["2.5"],
        "btts": round(btts, 3),
        "top": [[s, round(p, 3)] for s, p in tops],
        "lines": lines,
        "ah": ah,
    }


def build_corner_ratings(match_rows):
    """各队主/客场角球的创造与让出强度（时间衰减 + 向先验收缩）。"""
    today = date.today()
    acc = defaultdict(lambda: {
        "wh": 0.0, "wa": 0.0, "ch": 0.0, "cd": 0.0, "ah": 0.0, "ad": 0.0,
    })
    for m in match_rows:
        st = m.get("stats") or {}
        h = (st.get("home") or {}).get("corners")
        a = (st.get("away") or {}).get("corners")
        if h is None or a is None:
            continue
        d = parse_match_date(m.get("date"))
        if not d:
            continue
        age = (today - d).days
        if age < 0 or age > 1200:
            continue
        w = 0.5 ** (age / RATING_HALF_LIFE)
        hi = acc[m["home"]]
        hi["wh"] += w
        hi["ch"] += w * h
        hi["cd"] += w * a
        ai = acc[m["away"]]
        ai["wa"] += w
        ai["ah"] += w * a
        ai["ad"] += w * h
    return {tid: s for tid, s in acc.items() if s["wh"] + s["wa"] > 0}


def _corner_rate(value, weight):
    """角球单项强度，样本不足时向先验收缩。"""
    return (value + CORNER_PRIOR * CORNER_SHRINK) / (weight + CORNER_SHRINK)


def corner_probs(home_id, away_id, ratings):
    """双方期望角球数：自身创造与对手让出取平均。"""
    hs = ratings.get(str(home_id)) or {}
    as_ = ratings.get(str(away_id)) or {}
    h_for = _corner_rate(hs.get("ch", 0.0), hs.get("wh", 0.0))
    h_against = _corner_rate(hs.get("cd", 0.0), hs.get("wh", 0.0))
    a_for = _corner_rate(as_.get("ah", 0.0), as_.get("wa", 0.0))
    a_against = _corner_rate(as_.get("ad", 0.0), as_.get("wa", 0.0))
    eh = (h_for + a_against) / 2
    ea = (a_for + h_against) / 2
    return max(0.5, eh), max(0.5, ea)


def _nb_pmf(k, mu, disp):
    """负二项分布 pmf，方差 = disp × 均值；disp 不大于 1 时退化为泊松。

    用 lgamma 在对数空间计算，避免 k 较大时 math.gamma 溢出。
    """
    if disp <= 1.0 or mu <= 0:
        return poisson_pmf(k, mu)
    r = mu / (disp - 1.0)
    if k == 0:
        return (r / (r + mu)) ** r
    logp = (math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
            + r * math.log(r / (r + mu)) + k * math.log(mu / (r + mu)))
    return math.exp(logp)


def corner_output(eh, ea):
    """由期望角球数给出总角球分布与各条大小线概率。"""
    mu = eh + ea
    n = 40
    pmf = [_nb_pmf(i, mu, CORNER_DISP) for i in range(n)]
    total = sum(pmf) or 1.0
    over = {}
    for ln in CORNER_LINES:
        need = int(ln + 0.5)
        over[f"{ln:.1f}"] = round(sum(pmf[need:]) / total, 3)
    return {
        "expH": round(eh, 1),
        "expA": round(ea, 1),
        "exp": round(mu, 1),
        "over": over,
    }


def predict_match(home_id, away_id, league_code, ratings, corner_ratings=None):
    rh = ratings.get(str(home_id))
    ra = ratings.get(str(away_id))
    if not rh or not ra:
        return None
    if rh["lg"] == ra["lg"]:
        bh, ba = rh["bh"], rh["ba"]
        ha, hd, aa, ad = rh["HA"], rh["HD"], ra["AA"], ra["AD"]
    else:
        bh, ba = (rh["bh"] + ra["bh"]) / 2, (rh["ba"] + ra["ba"]) / 2
        # 跨联赛时向均值收缩，降低升降级/不同联赛基准带来的极端判断
        s = 0.6
        ha, hd = 1 + s * (rh["HA"] - 1), 1 + s * (rh["HD"] - 1)
        aa, ad = 1 + s * (ra["AA"] - 1), 1 + s * (ra["AD"] - 1)
    lh = min(max(bh * ha * ad, 0.2), 4.5)
    la = min(max(ba * aa * hd, 0.2), 4.5)
    lh, la = _damp_total(lh, la, bh, ba)
    out = poisson_probs(lh, la)
    out["nH"], out["nA"] = rh["n"], ra["n"]
    out["xlg"] = rh["lg"] != ra["lg"]
    if corner_ratings:
        eh, ea = corner_probs(home_id, away_id, corner_ratings)
        out["corners"] = corner_output(eh, ea)
    return out


STAT_ORDER = ("shots", "sot", "corners", "offsides", "yellow", "red",
              "fouls", "possession", "blocked", "saves")


def compact_payload(payload):
    """压缩页面体积：统计数组化、场地去重、移除前端不用的字段。"""
    venues = []
    seen = {}
    for m in payload["matches"] + payload["fixtures"]:
        st = m.get("stats")
        if st and st.get("home") and st.get("away"):
            m["st"] = [[st["home"].get(k) for k in STAT_ORDER],
                       [st["away"].get(k) for k in STAT_ORDER]]
            del m["stats"]
        v = m.get("venue")
        if v:
            idx = seen.get(v)
            if idx is None:
                idx = len(venues)
                seen[v] = idx
                venues.append(v)
            m["v"] = idx
        m.pop("venue", None)
        m.pop("season", None)
        m.pop("leagueCode", None)
        m.pop("neutral", None)
        if m.get("so") is None:
            m.pop("so", None)
    payload["venues"] = venues


def _decay(item, day):
    dt = day - item["last"]
    if dt > 0:
        f = 0.5 ** (dt / RATING_HALF_LIFE)
        for key in ("w", "hg", "ag", "wh", "wa", "hgf", "hga", "agf", "aga"):
            if key in item:
                item[key] *= f
        item["last"] = day


def build_pre_match(match_rows):
    """按时间顺序滚动计算每场比赛开赛前的模型预期进球（无未来数据泄漏）。"""
    rows = [m for m in match_rows
            if m.get("leagueCode") in RATING_LEAGUES and m.get("hs") is not None]
    rows.sort(key=lambda m: m.get("date") or "")
    lg = {}
    tm = defaultdict(dict)
    out = {}
    k = RATING_SHRINK
    for m in rows:
        d = parse_match_date(m.get("date"))
        if not d:
            continue
        day = d.toordinal()
        code = m["leagueCode"]
        base = lg.get(code)
        if base is not None:
            _decay(base, day)
        hi = tm[m["home"]].get(code)
        ai = tm[m["away"]].get(code)
        if hi is not None:
            _decay(hi, day)
        if ai is not None:
            _decay(ai, day)
        if base and base["w"] >= 20 and hi and ai:
            bh = base["hg"] / base["w"]
            ba = base["ag"] / base["w"]
            dh, da = hi["wh"] + k, hi["wa"] + k
            ha = ((hi["hgf"] + k * bh) / dh) / bh if bh else 1.0
            hd = ((hi["hga"] + k * ba) / dh) / ba if ba else 1.0
            aa = ((ai["agf"] + k * ba) / da) / ba if ba else 1.0
            ad = ((ai["aga"] + k * bh) / da) / bh if bh else 1.0
            lh = min(max(bh * ha * ad, 0.2), 4.5)
            la = min(max(ba * aa * hd, 0.2), 4.5)
            lh, la = _damp_total(lh, la, bh, ba)
            p = poisson_probs(lh, la)
            out[m["id"]] = {
                "xh": p["xgH"], "xa": p["xgA"],
                "ph": p["ph"], "pd": p["pd"], "pa": p["pa"],
                # 各条进球线的大球概率，按 GOAL_LINES 顺序存千分比整数以压缩体积
                "o": [int(round(p["lines"][f"{ln:.1f}"] * 1000)) for ln in GOAL_LINES],
            }
        # 记录本场结果
        if base is None:
            base = lg[code] = {"w": 0.0, "hg": 0.0, "ag": 0.0, "last": day}
        for key, val in (("w", 1.0), ("hg", m["hs"]), ("ag", m["as"])):
            base[key] = base.get(key, 0.0) + val
        for tid, gf, ga in ((m["home"], m["hs"], m["as"]), (m["away"], m["as"], m["hs"])):
            item = tm[tid].get(code)
            if item is None:
                item = tm[tid][code] = {
                    "wh": 0.0, "wa": 0.0, "hgf": 0.0, "hga": 0.0,
                    "agf": 0.0, "aga": 0.0, "last": day,
                }
            if tid == m["home"]:
                item["wh"] += 1.0
                item["hgf"] += gf
                item["hga"] += ga
            else:
                item["wa"] += 1.0
                item["agf"] += gf
                item["aga"] += ga
    return out




def summary_to_event(d, league, season, event_id):
    """从 summary 的 header 还原一场比赛（足总杯球队赛程接口不可用时使用）。"""
    h = d.get("header") or {}
    comps = h.get("competitions") or []
    if not comps:
        return None, []
    c = comps[0]
    status = (c.get("status") or {}).get("type") or {}
    home = away = None
    metas = []
    for t in c.get("competitors", []):
        team = t.get("team") or {}
        if team:
            remember_team(team)
            metas.append(team)
        if t.get("homeAway") == "home":
            home = t
        elif t.get("homeAway") == "away":
            away = t
    if not home or not away:
        return None, metas
    hid = (home.get("team") or {}).get("id") or home.get("id")
    aid = (away.get("team") or {}).get("id") or away.get("id")
    if not hid or not aid:
        return None, metas
    ev = {
        "id": str(event_id),
        "date": c.get("date") or h.get("gameDate"),
        "league": league["label"],
        "leagueCode": league["code"],
        "season": season,
        "completed": bool(status.get("completed")),
        "state": status.get("state") or "",
        "home": str(hid),
        "away": str(aid),
        "hs": score_value(home),
        "as": score_value(away),
        "so": None,
        "neutral": bool(c.get("neutralSite")),
        "venue": ((c.get("venue") or {}).get("fullName")) or "",
        "attendance": to_int(c.get("attendance")),
    }
    return ev, metas


def fetch_cup_schedule(league, team_id, season, refresh=False):
    """足总杯专用：核心接口列赛事 ID，再取 summary 还原比分与统计。"""
    name = f"fasched_{league['code']}_{team_id}_{season}.json"
    current = season >= CURRENT_SEASON
    cached = None if refresh else read_cache(name, max_age=(6 * 3600 if current else None))
    if cached is not None:
        for t in cached.get("teams", []):
            remember_team(t)
        return cached.get("rows", [])
    url = f"{CORE}/leagues/{league['code']}/seasons/{season}/teams/{team_id}/events?limit=100"
    try:
        d = get_json(url)
    except Exception as e:
        log(f"  赛程失败 {league['label']} {team_id} {season}: {e}")
        return []
    ids = []
    for item in d.get("items", []):
        ref = item.get("$ref") or ""
        if "/events/" in ref:
            eid = ref.split("/events/")[1].split("?")[0]
            if eid:
                ids.append(eid)
    rows, metas = [], []
    for eid in ids:
        cache_name = f"faev_{eid}.json"
        evd = read_cache(cache_name)
        if evd is None:
            try:
                full = get_json(f"{API}/{league['code']}/summary?event={eid}")
            except Exception as e:
                log(f"  杯赛详情失败 {eid}: {e}")
                continue
            ev, ms = summary_to_event(full, league, season, eid)
            stats = stats_for_summary(league["code"], eid, full)
            evd = {"event": ev, "teams": ms, "stats": stats}
            write_cache(cache_name, evd)
            if stats:
                write_cache(f"sum_{league['code']}_{eid}.json", {"ok": True, "stats": stats})
        for t in evd.get("teams", []):
            remember_team(t)
            metas.append(t)
        if evd.get("event"):
            rows.append(evd["event"])
    write_cache(name, {"rows": rows, "teams": metas})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="", help="只处理指定联赛，逗号分隔，如 西甲,英超")
    ap.add_argument("--max-summaries", type=int, default=0, help="限制抓取统计的场次（测试用）")
    ap.add_argument("--no-html", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="忽略赛程/比分板缓存")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--rate", type=float, default=0.0, help="请求最小间隔秒数，0 表示不限速")
    args = ap.parse_args()
    RATE_STATE["interval"] = max(0.0, args.rate)

    ensure_dirs()
    n_cn = merge_cn_extra()
    if n_cn:
        log(f"  补充中文队名 {n_cn} 条")
    _ODDS_SNAP_INDEX.update(load_odds_snapshots())
    if _ODDS_SNAP_INDEX:
        log(f"  已载入赛前盘口快照 {len(_ODDS_SNAP_INDEX)} 条")
    wanted = [s.strip() for s in args.leagues.split(",") if s.strip()]
    leagues = [l for l in LEAGUES if not wanted or l["label"] in wanted]
    if wanted:
        selected_labels = {l["label"] for l in leagues}
        for l in LEAGUES:
            if l.get("support_for") and any(x in selected_labels for x in l["support_for"]):
                if l not in leagues:
                    leagues.append(l)
    if not leagues:
        log("没有匹配的联赛")
        return

    log(f"开始采集：{', '.join(l['label'] for l in leagues)}")

    # 1) 球队（杯赛不拉球队名单，只借用已收录球队）
    teams = {}
    for lg in leagues:
        if lg.get("support_for") or lg.get("skip_team_list"):
            continue
        rows = fetch_teams(lg, refresh=args.refresh)
        for t in rows:
            cur = teams.setdefault(t["id"], dict(t))
            cur.setdefault("leagues", [])
            cur.setdefault("currentLeagues", [])
            if lg["label"] not in cur["currentLeagues"]:
                cur["currentLeagues"].append(lg["label"])
        log(f"  {lg['label']}: {len(rows)} 队")

    # 1.5) 欧战球队国内联赛补齐（仅 ESPN 公开可用的联赛）
    covered = {"英超", "西甲", "意甲", "德甲", "法甲", "英冠", "巴西甲"}
    extra = {}
    euro_teams = [t for t in teams.values()
                  if any(x in t.get("currentLeagues", []) for x in ("欧冠", "欧联杯"))]
    euro_n = 0
    for t in euro_teams:
        if set(t.get("currentLeagues", [])) & covered:
            continue
        euro_n += 1
        code = fetch_team_league(t["id"])
        if code in EURO_DOMESTIC:
            extra.setdefault(code, set()).add(t["id"])
    for code, ids in extra.items():
        label = EURO_DOMESTIC[code]
        for tid in ids:
            t = teams[tid]
            if label not in t["currentLeagues"]:
                t["currentLeagues"].append(label)
            if label not in t["leagues"]:
                t["leagues"].append(label)
        leagues.append({
            "label": label, "code": code, "cat": "major",
            "seasons": SEASONS[:2], "team_scope": sorted(ids),
            "skip_team_list": True, "no_scoreboard": True,
        })
    if extra:
        RATING_LEAGUES.update(extra.keys())
        log(f"  欧战国内联赛补齐：{euro_n} 支球队，覆盖 {len(extra)} 个联赛")
    for label, code in (("欧冠资格赛", "uefa.champions_qual"),
                        ("欧联杯资格赛", "uefa.europa_qual"),
                        ("欧协联", "uefa.conference"),
                        ("欧协联资格赛", "uefa.conference_qual")):
        leagues.append({
            "label": label, "code": code, "cat": "major",
            "seasons": [], "skip_team_list": True, "no_scoreboard": True,
        })

    # 2) 赛程
    jobs = []
    for lg in leagues:
        if lg.get("team_scope"):
            for tid in lg["team_scope"]:
                for s in lg["seasons"]:
                    jobs.append((lg, tid, s))
        elif lg.get("support_for"):
            for t in teams.values():
                if any(x in t.get("currentLeagues", []) for x in lg["support_for"]):
                    for s in lg["seasons"]:
                        jobs.append((lg, t["id"], s))
        else:
            for t in [x for x in teams.values() if lg["label"] in x.get("currentLeagues", [])]:
                for s in lg["seasons"]:
                    jobs.append((lg, t["id"], s))
    log(f"  赛程请求 {len(jobs)} 个")

    events = {}
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_cup_schedule if lg.get("core_schedule") else fetch_schedule,
                          lg, tid, s, args.refresh): (lg, tid, s)
                for lg, tid, s in jobs}
        for fut in as_completed(futs):
            rows = fut.result()
            for ev in rows:
                events.setdefault(ev["id"], ev)
            done += 1
            if done % 60 == 0:
                log(f"    赛程 {done}/{len(jobs)}，已收集 {len(events)} 场")

    # 2.5) 欧战球队跨赛事补充（资格赛、欧协联）
    all_jobs = [(t["id"], s) for t in euro_teams for s in SEASONS[:2]]
    if all_jobs:
        added = 0
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(fetch_all_schedule, tid, s, args.refresh): (tid, s)
                    for tid, s in all_jobs}
            for fut in as_completed(futs):
                for ev in fut.result():
                    if ev["id"] not in events:
                        events[ev["id"]] = ev
                        added += 1
        log(f"  欧战跨赛事补充：请求 {len(all_jobs)} 个，新增 {added} 场")

    # 3) 未来 8 天比分板（今日赛程 + 当天赛果）
    today = datetime.now()
    fixtures = {}
    sb_jobs = []
    for offset in range(-1, 9):
        ds = (today + timedelta(days=offset)).strftime("%Y%m%d")
        for lg in leagues:
            if lg.get("no_scoreboard"):
                continue
            sb_jobs.append((lg, ds))
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(fetch_scoreboard, lg, ds, args.refresh) for lg, ds in sb_jobs]
        for fut in as_completed(futs):
            for ev in fut.result():
                events.setdefault(ev["id"], ev)
                if not ev["completed"] and ev["state"] in ("pre", "in"):
                    fixtures[ev["id"]] = ev
    log(f"  未来赛程 {len(fixtures)} 场")

    # 合并历史对手元数据，并补全每支球队出现过的赛事
    for tid, meta in TEAM_META.items():
        if tid not in teams:
            teams[tid] = dict(meta)
            teams[tid]["leagues"] = []
    for ev in events.values():
        for tid in (ev["home"], ev["away"]):
            t = teams.get(tid)
            if t is None:
                t = teams[tid] = {"id": tid, "name": tid, "short": tid,
                                  "abbr": "", "color": "", "alt": "",
                                  "location": "", "leagues": []}
            if ev["league"] not in t["leagues"]:
                t["leagues"].append(ev["league"])

    # 4) 每队最近 30 场
    team_events = {}
    for ev in events.values():
        if not ev["completed"]:
            continue
        for tid in (ev["home"], ev["away"]):
            team_events.setdefault(tid, []).append(ev["id"])
    selected = set()
    for tid, ids in team_events.items():
        ids.sort(key=lambda i: events[i]["date"] or "", reverse=True)
        selected.update(ids[:30])
    counts = {}
    for eid in selected:
        ev = events[eid]
        for tid in (ev["home"], ev["away"]):
            counts[tid] = counts.get(tid, 0) + 1
    # 所有已结束比赛都抓统计，保证历史交锋表逐场数据完整
    h2h_recent = {eid for eid, ev in events.items()
                  if ev["completed"] and ev["league"] in [lg["label"] for lg in leagues]}
    # 旧赛季比赛只在已有缓存时复用，不再联网重试（ESPN 对老场次多为全零或无数据）
    def cached_stats(ev):
        return os.path.exists(os.path.join(
            CACHE_DIR, f"sum_{ev['leagueCode']}_{ev['id']}.json"))
    todo_ids = {eid for eid in (selected | h2h_recent)
                if eid in selected
                or (events[eid]["date"] or "") >= "2025-07-01"
                or cached_stats(events[eid])}
    log(f"  需要抓取统计的已结束比赛 {len(todo_ids)} 场")

    # 5) 统计
    todo = sorted(todo_ids, key=lambda i: events[i]["date"] or "", reverse=True)
    if args.max_summaries:
        todo = todo[:args.max_summaries]
    stats_map = {}
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_summary, events[eid]["leagueCode"], eid): eid for eid in todo}
        for fut in as_completed(futs):
            eid = futs[fut]
            res = fut.result()
            stats_map[eid] = res["stats"] if res else None
            done += 1
            if done % 100 == 0:
                ok = sum(1 for v in stats_map.values() if v)
                log(f"    统计 {done}/{len(todo)}，成功 {ok}")
    log(f"  统计完成：{sum(1 for v in stats_map.values() if v)}/{len(todo)} 场有数据")

    # 6) 组装
    def team_cn(t):
        cn, aliases = CN.get(t["name"], (t["name"], []))
        return cn, aliases

    league_labels = [lg["label"] for lg in leagues]
    all_done = {eid for eid, ev in events.items()
                if ev["completed"] and ev["league"] in league_labels}

    match_rows = []
    for eid in all_done:
        ev = events[eid]
        if ev["league"] in league_labels:
            st = stats_map.get(eid)
            match_rows.append({
                "id": eid,
                "date": ev["date"],
                "league": ev["league"],
                "leagueCode": ev["leagueCode"],
                "season": ev["season"],
                "home": ev["home"],
                "away": ev["away"],
                "hs": ev["hs"],
                "as": ev["as"],
                "so": ev["so"],
                "neutral": ev["neutral"],
                "venue": ev["venue"],
                "stats": st,
                "mkt": odds_market_probs(ev["leagueCode"], eid),
            })
    match_rows.sort(key=lambda m: m["date"] or "", reverse=True)
    pre_map = build_pre_match(match_rows)
    for m in match_rows:
        m["pre"] = pre_map.get(m["id"])
    log(f"  赛前预期进球：{len(pre_map)} 场")

    FIVE = ("英超", "西甲", "意甲", "德甲", "法甲")
    team_rows = []
    for t in teams.values():
        cn, aliases = team_cn(t)
        cur_lgs = t.get("currentLeagues", [])
        if "英冠" in cur_lgs:
            cat = "champ"
        elif "巴西甲" in cur_lgs:
            cat = "brazil"
        elif any(x in cur_lgs for x in FIVE):
            cat = "major"
        elif "英冠" in t["leagues"]:
            cat = "champ"
        elif "巴西甲" in t["leagues"]:
            cat = "brazil"
        else:
            cat = "major"
        team_rows.append({
            "id": t["id"],
            "name": t["name"],
            "short": t["short"],
            "cn": cn,
            "aliases": aliases,
            "abbr": t["abbr"],
            "color": t["color"],
            "alt": t["alt"],
            "location": t["location"],
            "leagues": t["leagues"],
            "currentLeagues": cur_lgs,
            "cat": cat,
            "count": counts.get(t["id"], 0),
        })
    team_rows.sort(key=lambda t: (t["cn"], t["name"]))

# 中文队名覆盖自检：新增球队若未收录译名，会在日志里提示，避免前端回落到英文
    untranslated = sorted({t["name"] for t in team_rows if t.get("cn") == t.get("name")})
    if untranslated:
        log(f"  ⚠ 未翻译球队 {len(untranslated)} 支，需补进 team_cn_extra.json："
            + "、".join(untranslated[:10]))
    else:
        log(f"  中文队名：{len(team_rows)} 支全部已翻译")

    ratings = build_ratings(match_rows)
    corner_ratings = build_corner_ratings(match_rows)
    log(f"  攻防模型：{len(ratings)} 支球队；角球模型：{len(corner_ratings)} 支球队")

    fixture_events = [ev for ev in fixtures.values()
                      if ev["league"] in [lg["label"] for lg in leagues]
                      and ev["home"] in teams and ev["away"] in teams]
    odds_map = {}
    odds_jobs = [ev for ev in fixture_events if not ev["completed"]]
    if odds_jobs and not args.max_summaries:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(fetch_odds, ev["leagueCode"], ev["id"]): ev["id"] for ev in odds_jobs}
            for fut in as_completed(futs):
                odds_map[futs[fut]] = fut.result()
        log(f"  赔率：{sum(1 for v in odds_map.values() if v)}/{len(odds_jobs)} 场有数据")
        snap_added = write_odds_snapshots(events, odds_map)
        if snap_added:
            log(f"  盘口快照：新增 {snap_added} 条")

    fixture_rows = []
    for ev in fixture_events:
        fixture_rows.append({
            "id": ev["id"], "date": ev["date"], "league": ev["league"],
            "leagueCode": ev["leagueCode"],
            "home": ev["home"], "away": ev["away"], "venue": ev["venue"],
            "state": ev["state"],
            "odds": odds_map.get(ev["id"]),
            "pred": predict_match(ev["home"], ev["away"], ev["leagueCode"],
                                  ratings, corner_ratings),
        })
    fixture_rows.sort(key=lambda f: f["date"] or "")

    upcoming_teams = {ev["home"] for ev in fixture_events if not ev["completed"]}
    upcoming_teams |= {ev["away"] for ev in fixture_events if not ev["completed"]}
    lineups = {}
    if upcoming_teams and not args.max_summaries:
        log(f"  参考阵容：{len(lineups)} 支球队")

    # 球员中文名覆盖自检（必须在 lineups 构建之后）
    miss_players = set()
    for lu in lineups.values():
        for pl in (lu.get("p") or []):
            en = pl.get("en") or ""
            n = pl.get("n") or ""
            if en and n and not any(0x4E00 <= ord(ch) <= 0x9FFF for ch in n):
                miss_players.add(en)
    if miss_players:
        log(f"  ⚠ 未翻译球员 {len(miss_players)} 人，需补进 player_cn.json："
            + "、".join(sorted(miss_players)[:8]))
    elif lineups:
        log("  球员中文名：阵容中已全部翻译")

    dates = [m["date"] for m in match_rows if m["date"]]
    meta = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "matchCount": len(match_rows),
        "teamCount": len(team_rows),
        "fixtureCount": len(fixture_rows),
        "dateMin": min(dates) if dates else None,
        "dateMax": max(dates) if dates else None,
        "source": "ESPN",
        "season": f"{CURRENT_SEASON}/{(CURRENT_SEASON + 1) % 100:02d}",
    }
    payload = {
        "meta": meta,
        "leagues": [{"label": l["label"], "code": l["code"], "cat": l["cat"]} for l in leagues],
        "categories": CATEGORIES,
        "teams": team_rows,
        "matches": match_rows,
        "fixtures": fixture_rows,
        "lineups": lineups,
    }
    compact_payload(payload)
    out_json = os.path.join(DATA_DIR, "matches.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    log(f"已写入 {out_json}（{len(match_rows)} 场比赛，{len(team_rows)} 支球队）")

    if not args.no_html:
        tpl_path = os.path.join(ROOT, "template.html")
        if not os.path.exists(tpl_path):
            log("缺少 template.html，跳过 HTML 生成")
            return
        with open(tpl_path, "r", encoding="utf-8") as f:
            tpl = f.read()
        js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        html = tpl.replace("__DATA_JSON__", js)
        out_html = os.path.join(ROOT, "football_database.html")
        with open(out_html, "w", encoding="utf-8") as f:
            f.write(html)
        log(f"已生成 {out_html}（{os.path.getsize(out_html)/1024/1024:.1f} MB）")


if __name__ == "__main__":
    main()
