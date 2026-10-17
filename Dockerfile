FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 VERIQ_DATA_DIR=/data
WORKDIR /app
COPY pyproject.toml constraints.txt README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir -c constraints.txt '.[hosted]' \
    && groupadd --gid 10001 veriq \
    && useradd --uid 10001 --gid veriq --no-create-home veriq \
    && mkdir /data && chown veriq:veriq /data
USER 10001:10001
EXPOSE 8000
CMD ["veriq", "serve"]
