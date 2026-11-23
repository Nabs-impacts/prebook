FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 1001 prebook \
    && useradd --system --uid 1001 --gid prebook --create-home prebook

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=prebook:prebook app ./app
COPY --chown=prebook:prebook alembic ./alembic
COPY --chown=prebook:prebook alembic.ini ./

RUN mkdir -p /app/storage && chown -R prebook:prebook /app/storage

USER prebook

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
