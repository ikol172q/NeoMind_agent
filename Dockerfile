# ─────────────────────────────────────────────────────────
# NeoMind Agent — Docker Image
#
# Single-stage build — simple, reliable, no missing-file issues.
#
# Usage:
#   docker build -t neomind .
#   docker run -it --env-file .env neomind --mode fin
#
# With OpenClaw:
#   docker compose up -d
# ─────────────────────────────────────────────────────────

FROM python:3.11-slim

WORKDIR /app

# System deps for lxml, cryptography, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev libxml2-dev libxslt1-dev libxml2 libxslt1.1 git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies directly (no pyproject.toml build needed)
RUN pip install --no-cache-dir \
    openai python-dotenv requests PyYAML prompt_toolkit rich aiohttp beautifulsoup4 \
    finnhub-python yfinance akshare feedparser \
    cryptography keyring sympy websockets \
    trafilatura duckduckgo-search lxml \
    html2text chardet tiktoken \
    python-telegram-bot

# Copy application code
COPY . .

# Create persistent data directories
RUN mkdir -p /data/neomind /data/openclaw-bridge && \
    chmod 700 /data/neomind

# Default environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HOME=/data \
    TERM=xterm-256color

# NeoMind data directory (mounted as volume for persistence)
VOLUME ["/data/neomind"]

# Expose standalone sync port (if not using OpenClaw)
EXPOSE 18790

# Entrypoint
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["--mode", "fin"]
