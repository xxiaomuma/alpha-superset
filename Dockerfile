#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.
#

######################################################################
# Node stage to deal with static asset construction
######################################################################
ARG PY_VER=3.11.13-slim-bookworm
ARG BUILDPLATFORM=${BUILDPLATFORM:-amd64}
ARG BUILD_TRANSLATIONS="true"

######################################################################
# superset-node-ci
######################################################################
FROM --platform=${BUILDPLATFORM} node:20-bookworm-slim AS superset-node-ci

# ---------- 国内源 ----------
COPY docker/change-apt-source.sh /tmp/change-apt-source.sh
RUN chmod +x /tmp/change-apt-source.sh && /tmp/change-apt-source.sh
RUN npm config set registry https://registry.npmmirror.com
ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
# ---------------------------

ARG BUILD_TRANSLATIONS
ENV BUILD_TRANSLATIONS=${BUILD_TRANSLATIONS}
ARG DEV_MODE="false"
ENV DEV_MODE=${DEV_MODE}

COPY docker/ /app/docker/
ARG NPM_BUILD_CMD="build"

RUN /app/docker/apt-install.sh build-essential python3 zstd

ENV BUILD_CMD=${NPM_BUILD_CMD} \
    PUPPETEER_SKIP_DOWNLOAD=true

RUN /app/docker/frontend-mem-nag.sh

WORKDIR /app/superset-frontend

RUN mkdir -p /app/superset/static/assets \
             /app/superset/translations

RUN --mount=type=bind,source=./superset-frontend/package.json,target=./package.json \
    --mount=type=bind,source=./superset-frontend/package-lock.json,target=./package-lock.json \
    --mount=type=cache,target=/root/.cache \
    --mount=type=cache,target=/root/.npm \
    if [ "$DEV_MODE" = "false" ]; then npm ci; else echo "Skipping npm ci"; fi

COPY superset-frontend /app/superset-frontend

######################################################################
# superset-node
######################################################################
FROM superset-node-ci AS superset-node

RUN --mount=type=cache,target=/root/.npm \
    if [ "$DEV_MODE" = "false" ]; then npm run ${BUILD_CMD}; fi

COPY superset/translations /app/superset/translations

RUN if [ "$BUILD_TRANSLATIONS" = "true" ]; then npm run build-translation; fi && \
    rm -rf /app/superset/translations/*/*/*.po

######################################################################
# python-base
######################################################################
FROM python:${PY_VER} AS python-base

# ---------- 国内源 ----------
COPY docker/change-apt-source.sh /tmp/change-apt-source.sh
RUN chmod +x /tmp/change-apt-source.sh && /tmp/change-apt-source.sh

ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
    PIP_TRUSTED_HOST=mirrors.aliyun.com
# ---------------------------

ARG SUPERSET_HOME="/app/superset_home"
ENV SUPERSET_HOME=${SUPERSET_HOME}

RUN mkdir -p $SUPERSET_HOME
RUN useradd --user-group -d ${SUPERSET_HOME} -m --no-log-init --shell /bin/bash superset \
    && chmod -R 1777 $SUPERSET_HOME \
    && chown -R superset:superset $SUPERSET_HOME

COPY --chmod=755 docker/*.sh /app/docker/

RUN pip install --no-cache-dir --upgrade uv
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:${PATH}"

######################################################################
# python-translation-compiler
######################################################################
FROM python-base AS python-translation-compiler

ARG BUILD_TRANSLATIONS
ENV BUILD_TRANSLATIONS=${BUILD_TRANSLATIONS}

COPY requirements/translations.txt requirements/
RUN --mount=type=cache,target=/root/.cache/uv \
    . /app/.venv/bin/activate && \
    /app/docker/pip-install.sh --requires-build-essential -r requirements/translations.txt

COPY superset/translations/ /app/translations_mo/
RUN if [ "$BUILD_TRANSLATIONS" = "true" ]; then pybabel compile -d /app/translations_mo || true; fi && \
    rm -f /app/translations_mo/*/*/*.po && \
    rm -f /app/translations_mo/*/*/*.json

######################################################################
# python-common
######################################################################
FROM python-base AS python-common

ENV SUPERSET_HOME="/app/superset_home" \
    HOME="/app/superset_home" \
    SUPERSET_ENV="production" \
    FLASK_APP="superset.app:create_app()" \
    PYTHONPATH="/app/pythonpath" \
    SUPERSET_PORT="8088" \
    PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright

COPY --chmod=755 docker/entrypoints /app/docker/entrypoints

WORKDIR /app

RUN mkdir -p \
      ${PYTHONPATH} \
      superset/static \
      requirements \
      superset-frontend \
      apache_superset.egg-info \
    && touch superset/static/version_info.json

ARG INCLUDE_CHROMIUM="true"
ARG INCLUDE_FIREFOX="false"
RUN --mount=type=cache,target=${SUPERSET_HOME}/.cache/uv \
    if [ "$INCLUDE_CHROMIUM" = "true" ] || [ "$INCLUDE_FIREFOX" = "true" ]; then \
        uv pip install playwright && \
        playwright install-deps && \
        [ "$INCLUDE_CHROMIUM" = "true" ] && playwright install chromium || true && \
        [ "$INCLUDE_FIREFOX" = "true" ] && playwright install firefox || true; \
    fi

COPY pyproject.toml setup.py MANIFEST.in ./
COPY superset-frontend/package.json superset-frontend/
COPY scripts/check-env.py scripts/
COPY --chmod=755 docker/entrypoints/run-server.sh /usr/bin/

RUN /app/docker/apt-install.sh \
      curl \
      libsasl2-dev \
      libsasl2-modules-gssapi-mit \
      libpq-dev \
      libecpg-dev \
      libldap2-dev

COPY --from=superset-node /app/superset/static/assets superset/static/assets
COPY superset superset
RUN rm superset/translations/*/*/*.po

COPY --from=superset-node /app/superset/translations superset/translations
COPY --from=python-translation-compiler /app/translations_mo superset/translations

HEALTHCHECK CMD curl -f "http://localhost:${SUPERSET_PORT}/health"
CMD ["/app/docker/entrypoints/run-server.sh"]
EXPOSE ${SUPERSET_PORT}

######################################################################
# lean
######################################################################
FROM python-common AS lean

# ---------- 国内源 ----------
COPY docker/change-apt-source.sh /tmp/change-apt-source.sh
RUN chmod +x /tmp/change-apt-source.sh && /tmp/change-apt-source.sh

ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
    PIP_TRUSTED_HOST=mirrors.aliyun.com
# 安装 MySQL 客户端编译所需的依赖
RUN /app/docker/apt-install.sh \
    pkg-config \
    default-libmysqlclient-dev \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    libmariadb-dev

COPY requirements/base.txt requirements/
RUN --mount=type=cache,target=${SUPERSET_HOME}/.cache/uv \
    /app/docker/pip-install.sh -r requirements/base.txt

# 安装 Superset 本体
RUN --mount=type=cache,target=${SUPERSET_HOME}/.cache/uv \
    uv pip install .

# 安装 MySQL driver（关键）
RUN --mount=type=cache,target=${SUPERSET_HOME}/.cache/uv \
    uv pip install mysqlclient

# 安装 ClickHouse driver（关键）
RUN --mount=type=cache,target=${SUPERSET_HOME}/.cache/uv \
    uv pip install clickhouse-connect

RUN python -m compileall /app/superset

USER superset



######################################################################
# dev
######################################################################
FROM python-common AS dev
# ---------- 国内源 ----------
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple/ \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY docker/change-apt-source.sh /tmp/change-apt-source.sh
RUN chmod +x /tmp/change-apt-source.sh && /tmp/change-apt-source.sh

RUN /app/docker/apt-install.sh \
    git \
    pkg-config \
    default-libmysqlclient-dev

COPY requirements/*.txt requirements/
RUN --mount=type=cache,target=${SUPERSET_HOME}/.cache/uv \
    /app/docker/pip-install.sh --requires-build-essential -r requirements/development.txt

RUN --mount=type=cache,target=${SUPERSET_HOME}/.cache/uv \
    uv pip install .

RUN uv pip install .[postgres]
RUN python -m compileall /app/superset
USER superset

######################################################################
# ci
######################################################################
FROM lean AS ci
USER root
RUN uv pip install .[postgres]
USER superset
CMD ["/app/docker/entrypoints/docker-ci.sh"]
