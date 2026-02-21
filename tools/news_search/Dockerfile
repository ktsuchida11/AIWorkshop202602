FROM python:3.13-slim

# -----------------------------
# OS packages
# -----------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# install uv (official way)
# -----------------------------
ENV UV_INSTALL_DIR=/usr/local/bin

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# uv が PATH にあることを保証
ENV PATH="/usr/local/bin:${PATH}"

# -----------------------------
# app setup
# -----------------------------
WORKDIR /app

COPY pyproject.toml uv.lock* /app/
RUN uv sync --frozen

COPY . /app

ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "python", "server.py"]
