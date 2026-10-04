# ---------- stage 1: builder ----------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install ".[dev]"


# ---------- stage 2: runtime ----------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    FDT_DATA_DIR=/app/data

RUN groupadd -r fdt && useradd -r -g fdt -d /app fdt
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

COPY alembic/ alembic/
COPY alembic.ini pyproject.toml ./
COPY app/ app/
COPY scripts/ scripts/
COPY data/ data/
COPY models_artifacts/ models_artifacts/

# The ML artifacts and the C-MAPSS telemetry are read at FDT_DATA_DIR at startup, and a
# wrong path there degrades silently to the deterministic fallback with the model
# sitting on disk unused. Fail the build instead of shipping that.
RUN python -c "import os,pathlib; d=pathlib.Path(os.environ['FDT_DATA_DIR']); \
    assert (d/'raw').is_dir(), f'{d}/raw missing'; \
    print('data dir OK:', d)"

RUN mkdir -p /app/static/models && chown -R fdt:fdt /app

USER fdt
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; \
      sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"

# --workers 1: the replay engine is an in-process task. Multiple workers would
# run multiple replay loops and double-advance every aircraft (docs/11 §2).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers"]
