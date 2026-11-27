FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MURAL_DB=/data/mural.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 确保内置样片 SVG 齐全（仓库中已生成，这一步是幂等保险）
RUN python -m app.scene

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 5000

# 容器健康检查（slim 镜像自带 python，无需 curl）
HEALTHCHECK --interval=10s --timeout=4s --start-period=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=3)"

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--preload", "--timeout", "60", "wsgi:application"]
