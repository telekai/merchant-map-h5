FROM python:3.12-slim

WORKDIR /app

# 目录结构需匹配server.py中的路径逻辑：
#   BASE_DIR = server.py所在目录 → /app/backend
#   DB_PATH = BASE_DIR/merchants.db → /app/backend/merchants.db
#   FRONTEND_DIR = BASE_DIR的上级目录/frontend → /app/frontend

# 复制后端代码和数据库
COPY backend/server.py /app/backend/server.py
COPY backend/merchants.db /app/backend/merchants.db

# 复制前端静态文件
COPY frontend/ /app/frontend/

# 环境变量
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

# 用 -u 确保日志不缓冲
CMD ["python", "-u", "/app/backend/server.py"]