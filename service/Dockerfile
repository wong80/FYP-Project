FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Kuala_Lumpur \
    MPLBACKEND=Agg \
    MLFLOW_DISABLE_AGENT_HINT=1 \
    GUARDRAILS_PATH=/app/config/guardrails.yaml

# libgomp1: LightGBM/XGBoost threading. curl: healthchecks.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 tzdata curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# supercronic: cron made for containers (logs to stdout, handles signals).
ARG SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-amd64
ARG SUPERCRONIC_SHA1=71b0d58cc53f6bd72cf2f293e09e294b79c666d8
RUN curl -fsSLo /usr/local/bin/supercronic "$SUPERCRONIC_URL" \
 && echo "${SUPERCRONIC_SHA1}  /usr/local/bin/supercronic" | sha1sum -c - \
 && chmod +x /usr/local/bin/supercronic

WORKDIR /app
COPY constraints.txt pyproject.toml ./
COPY src ./src
RUN pip install -c constraints.txt .

COPY config ./config
COPY crontab ./crontab

RUN useradd --system --uid 10001 --home-dir /home/app --create-home app \
 && mkdir -p /mlartifacts && chown app /mlartifacts
USER app

ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

ENTRYPOINT ["chiller"]
CMD ["--help"]
