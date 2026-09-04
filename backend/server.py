# -*- coding: utf-8 -*-
"""
商户地图后端API服务 - 纯标准库版本
无需安装任何第三方依赖
基于 http.server 实现RESTful API
"""

import json
import math
import sqlite3
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ============================================================
# 配置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "merchants.db")
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

# ============================================================
# 工具函数
# ============================================================

def haversine(lng1, lat1, lng2, lat2):
    """计算两个经纬度点之间的距离（单位：米）"""
    R = 6371000
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_stats():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM merchants")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM merchants WHERE lng IS NOT NULL AND lat IS NOT NULL")
    with_coords = cursor.fetchone()[0]
    cursor.execute("SELECT industry, COUNT(*) as cnt FROM merchants GROUP BY industry ORDER BY cnt DESC")
    industry_dist = [{"industry": r[0], "count": r[1]} for r in cursor.fetchall()]
    conn.close()
    return {"total": total, "with_coords": with_coords, "industry_distribution": industry_dist}


def get_nearby(lat, lng, radius=5000, page=1, page_size=50, industry=None):
    conn = get_db()
    cursor = conn.cursor()

    sql = "SELECT id, industry, name, address, phone, business_hours, lng, lat FROM merchants WHERE lng IS NOT NULL AND lat IS NOT NULL"
    params = []
    if industry:
        sql += " AND industry = ?"
        params.append(industry)

    cursor.execute(sql, params)
    rows = cursor.fetchall()

    results = []
    for row in rows:
        distance = haversine(lng, lat, row["lng"], row["lat"])
        if distance <= radius:
            results.append({
                "id": row["id"],
                "industry": row["industry"],
                "name": row["name"],
                "address": row["address"],
                "phone": row["phone"],
                "business_hours": row["business_hours"],
                "lng": row["lng"],
                "lat": row["lat"],
                "distance": round(distance, 1),
            })

    results.sort(key=lambda x: x["distance"])
    total = len(results)
    start = (page - 1) * page_size
    end = start + page_size
    paged = results[start:end]

    conn.close()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if page_size > 0 else 0,
        "radius": radius,
        "data": paged,
    }


def get_merchant(merchant_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM merchants WHERE id = ?", (merchant_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


# MIME types
MIME_MAP = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class RequestHandler(BaseHTTPRequestHandler):

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, filepath, content_type):
        try:
            with open(filepath, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self._send_json({"error": "File not found"}, 404)

    def _send_404(self):
        self._send_json({"error": "Not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # API routes
        if path == "/api/health":
            self._send_json({"status": "ok", "message": "商户地图API服务运行中"})
            return

        if path == "/api/stats":
            self._send_json(get_stats())
            return

        if path == "/api/nearby":
            try:
                lat = float(query.get("lat", [0])[0])
                lng = float(query.get("lng", [0])[0])
                radius = int(query.get("radius", [5000])[0])
                radius = max(100, min(50000, radius))
                page = int(query.get("page", [1])[0])
                page_size = int(query.get("page_size", [50])[0])
                page_size = max(1, min(200, page_size))
                industry = query.get("industry", [None])[0]
                if industry == "" or industry is None:
                    industry = None
                self._send_json(get_nearby(lat, lng, radius, page, page_size, industry))
            except Exception as e:
                self._send_json({"error": str(e)}, 400)
            return

        if path.startswith("/api/merchant/"):
            try:
                merchant_id = int(path.split("/")[-1])
                merchant = get_merchant(merchant_id)
                if merchant:
                    self._send_json(merchant)
                else:
                    self._send_404()
            except ValueError:
                self._send_404()
            return

        # 静态文件：H5前端
        if path == "/" or path == "/index.html":
            self._send_file(os.path.join(FRONTEND_DIR, "index.html"), "text/html; charset=utf-8")
            return

        if path.startswith("/h5/"):
            rel_path = path[4:]  # remove /h5/
            if rel_path == "" or rel_path == "/":
                rel_path = "index.html"
            filepath = os.path.join(FRONTEND_DIR, rel_path)
            ext = os.path.splitext(filepath)[1]
            content_type = MIME_MAP.get(ext, "application/octet-stream")
            self._send_file(filepath, content_type)
            return

        # 未知路由
        self._send_404()

    def log_message(self, format, *args):
        # 简化日志
        print(f"[{self.client_address[0]}] {args[0]}")


def main():
    print(f"数据库路径: {DB_PATH}")
    print(f"前端目录: {FRONTEND_DIR}")
    print(f"启动服务: http://localhost:{PORT}")
    print(f"H5页面: http://localhost:{PORT}/")
    print(f"API文档: http://localhost:{PORT}/api/health")
    print(f"周边查询: http://localhost:{PORT}/api/nearby?lat=30.28&lng=120.02&radius=5000")
    print("-" * 60)

    server = HTTPServer((HOST, PORT), RequestHandler)
    print(f"服务已启动，监听 {HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()


if __name__ == "__main__":
    main()
