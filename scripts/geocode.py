# -*- coding: utf-8 -*-
"""
地理编码脚本 - 将商户地址转换为经纬度坐标
支持两种模式：
  1. online  - 调用高德地理编码API（需要API Key）
  2. offline - 离线模拟坐标（按区域随机分配，适合本机开发测试）

用法:
  python geocode.py --mode offline --input ../../杭州商户模拟数据_1000条.csv --output ../data/merchants.db
  python geocode.py --mode online --key YOUR_AMAP_KEY --input data.csv --output merchants.db
"""

import argparse
import csv
import os
import sqlite3
import json
import time
import math
import random
import urllib.request
import urllib.parse
from datetime import datetime

# ============================================================
# 区域经纬度范围（杭州余杭区、拱墅区真实边界近似）
# 格式: (min_lng, max_lng, min_lat, max_lat)
# ============================================================
DISTRICT_BOUNDS = {
    "余杭区": {
        # 余杭区范围很大，细分为几个子区域
        "临平": (120.15, 120.30, 30.33, 30.45),       # 临平片区
        "仓前": (119.90, 120.10, 30.25, 30.38),       # 仓前/未来科技城
        "良渚": (120.00, 120.20, 30.30, 30.42),       # 良渚
        "闲林": (119.95, 120.10, 30.20, 30.30),       # 闲林
        "瓶窑": (119.85, 120.05, 30.25, 30.40),       # 瓶窑
        "径山": (119.80, 120.00, 30.25, 30.42),       # 径山
        "塘栖": (120.10, 120.25, 30.35, 30.48),      # 塘栖
        "崇贤": (120.10, 120.22, 30.28, 30.38),      # 崇贤
        "仁和": (120.05, 120.18, 30.30, 30.40),      # 仁和
        "default": (119.90, 120.30, 30.25, 30.45),    # 全区默认
    },
    "拱墅区": {
        "default": (120.08, 120.20, 30.25, 30.38),    # 拱墅区整体范围
    }
}

# 子区域关键词匹配
SUB_AREA_KEYWORDS = {
    "临平": ["临平", "南苑", "东湖", "星桥", "乔司", "运河", "临平银泰", "万宝城", "余之城", "华元"],
    "仓前": ["仓前", "五常", "未来科技城", "海创园", "梦想小镇", "阿里巴巴", "恒生", "EFC", "海曙", "高教路", "联胜"],
    "良渚": ["良渚", "勾庄", "古墩路", "西田城", "永旺", "良渚文化村", "上亿广场", "杜甫"],
    "闲林": ["闲林", "闲富", "方家山", "甄家湾"],
    "瓶窑": ["瓶窑", "瓶仓大道", "羊城路"],
    "径山": ["径山", "黄湖", "鸬鸟", "百丈", "双溪"],
    "塘栖": ["塘栖", "超山", "塘栖路"],
    "崇贤": ["崇贤", "崇贤上亿"],
    "仁和": ["仁和", "仁和商业"],
}


def detect_sub_area(address):
    """根据地址中的关键词判断子区域"""
    for area, keywords in SUB_AREA_KEYWORDS.items():
        for kw in keywords:
            if kw in address:
                return area
    return "default"


def get_district(address):
    """从地址中提取区名"""
    if "余杭区" in address:
        return "余杭区"
    elif "拱墅区" in address:
        return "拱墅区"
    return None


def offline_geocode(address):
    """离线模式：根据地址在对应区域范围内随机生成坐标"""
    district = get_district(address)
    if not district:
        return None, None

    if district == "余杭区":
        sub_area = detect_sub_area(address)
        bounds = DISTRICT_BOUNDS["余杭区"].get(sub_area, DISTRICT_BOUNDS["余杭区"]["default"])
    else:
        bounds = DISTRICT_BOUNDS["拱墅区"]["default"]

    min_lng, max_lng, min_lat, max_lat = bounds
    lng = round(random.uniform(min_lng, max_lng), 6)
    lat = round(random.uniform(min_lat, max_lat), 6)
    return lng, lat


def online_geocode(address, api_key):
    """在线模式：调用高德地理编码API"""
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        "address": address,
        "key": api_key,
        "output": "json",
    }
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"

    try:
        req = urllib.request.Request(full_url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "1" and data.get("geocodes"):
            location = data["geocodes"][0].get("location", "")
            if location:
                parts = location.split(",")
                return float(parts[0]), float(parts[1])
        return None, None
    except Exception as e:
        print(f"  API调用失败: {e}")
        return None, None


def init_database(db_path):
    """初始化SQLite数据库，创建商户表"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS merchants (
            id INTEGER PRIMARY KEY,
            industry TEXT NOT NULL,
            name TEXT NOT NULL,
            address TEXT NOT NULL,
            phone TEXT,
            business_hours TEXT,
            lng REAL,
            lat REAL,
            geocode_status TEXT DEFAULT 'pending',
            geocode_time TEXT
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_merchants_coords
        ON merchants(lng, lat)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_merchants_industry
        ON merchants(industry)
    """)
    conn.commit()
    conn.close()
    print(f"数据库已初始化: {db_path}")


def haversine(lng1, lat1, lng2, lat2):
    """计算两个经纬度点之间的距离（单位：米）"""
    R = 6371000  # 地球半径（米）
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def process_csv(csv_path, db_path, mode, api_key):
    """读取CSV并逐条地理编码，写入数据库"""
    # 初始化数据库
    init_database(db_path)

    # 读取CSV
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"读取到 {len(rows)} 条商户数据")
    print(f"地理编码模式: {mode}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    success = 0
    failed = 0

    for i, row in enumerate(rows):
        seq = int(row["序号"])
        industry = row["行业"]
        name = row["商户名称"]
        address = row["地址"]
        phone = row["联系电话"]
        hours = row["营业时间"]

        # 地理编码
        if mode == "online":
            lng, lat = online_geocode(address, api_key)
            time.sleep(0.02)  # 限速：QPS 50
        else:
            lng, lat = offline_geocode(address)

        if lng is not None and lat is not None:
            status = "success"
            success += 1
        else:
            status = "failed"
            failed += 1

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT OR REPLACE INTO merchants
            (id, industry, name, address, phone, business_hours, lng, lat, geocode_status, geocode_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (seq, industry, name, address, phone, hours,
              lng if lng else None, lat if lat else None, status, now))

        # 进度显示
        if (i + 1) % 100 == 0 or i == len(rows) - 1:
            conn.commit()
            print(f"  进度: {i+1}/{len(rows)} | 成功: {success} | 失败: {failed}")

    conn.commit()
    conn.close()

    print(f"\n地理编码完成！")
    print(f"  总计: {len(rows)} 条")
    print(f"  成功: {success} 条")
    print(f"  失败: {failed} 条")

    # 验证：打印前5条
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, industry, name, lng, lat FROM merchants LIMIT 5")
    samples = cursor.fetchall()
    print(f"\n前5条样本:")
    for s in samples:
        print(f"  {s[0]}. [{s[1]}] {s[2]} → ({s[3]}, {s[4]})")

    # 统计坐标分布
    cursor.execute("SELECT COUNT(*) FROM merchants WHERE lng IS NOT NULL")
    total_with_coords = cursor.fetchone()[0]
    cursor.execute("SELECT MIN(lng), MAX(lng), MIN(lat), MAX(lat) FROM merchants WHERE lng IS NOT NULL")
    bounds = cursor.fetchone()
    print(f"\n坐标分布:")
    print(f"  有效坐标: {total_with_coords} 条")
    print(f"  经度范围: {bounds[0]:.4f} ~ {bounds[1]:.4f}")
    print(f"  纬度范围: {bounds[2]:.4f} ~ {bounds[3]:.4f}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="商户地理编码脚本")
    parser.add_argument("--mode", choices=["online", "offline"], default="offline",
                        help="地理编码模式：online=高德API, offline=离线模拟（默认）")
    parser.add_argument("--key", type=str, default="",
                        help="高德API Key（仅online模式需要）")
    parser.add_argument("--input", type=str, required=True,
                        help="输入CSV文件路径")
    parser.add_argument("--output", type=str, default="merchants.db",
                        help="输出SQLite数据库路径")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"错误：输入文件不存在: {args.input}")
        return

    if args.mode == "online" and not args.key:
        print("错误：online模式需要提供 --key 参数")
        return

    process_csv(args.input, args.output, args.mode, args.key)


if __name__ == "__main__":
    main()
