# Phase1.0 PR16：应用镜像，单实例运行（workers=1）
# 使用镜像源以规避 docker.io 在国内拉取失败或第三方镜像 403
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

WORKDIR /app

# 安装依赖（基于 pyproject.toml，不增加新业务依赖）
# 国内构建可加速：--build-arg PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX
COPY pyproject.toml ./
RUN if [ -n "$PIP_INDEX" ]; then pip install --no-cache-dir -i "$PIP_INDEX" -e .; else pip install --no-cache-dir -e .; fi

# 运行所需文件
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY config/ ./config/
COPY scripts/ ./scripts/
RUN chmod +x scripts/init_db.sh

# 可选：日志目录
RUN mkdir -p /app/logs

# 单实例约束：显式 workers=1
CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
