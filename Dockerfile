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
# tini: proper PID 1 (signal forwarding, zombie reaping)
# supervisor: process manager for agent + health monitor + watchdog
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev libxml2-dev libxslt1-dev libxml2 libxslt1.1 git \
    tini supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies directly (no pyproject.toml build needed)
RUN pip install --no-cache-dir \
    openai python-dotenv requests PyYAML prompt_toolkit rich aiohttp beautifulsoup4 \
    finnhub-python yfinance akshare feedparser \
    cryptography keyring sympy websockets \
    trafilatura duckduckgo-search lxml \
    html2text readability-lxml chardet tiktoken \
    python-telegram-bot \
    playwright \
    # Universal Search Engine deps
    flashrank \
    && \
    # Optional: search + RAG dependencies (|| true = don't fail build if any fails)
    pip install --no-cache-dir \
    faiss-cpu sentence-transformers PyPDF2 \
    crawl4ai exa_py || true

# Install Chromium for browser daemon
RUN playwright install chromium && playwright install-deps chromium

# Copy application code
COPY . .

# Create persistent data directories
RUN mkdir -p /data/neomind /data/openclaw-bridge \
    /data/neomind/evolution /data/neomind/crash_log \
    /data/neomind/db && \
    chmod 700 /data/neomind

# Supervisord config for multi-process management
COPY supervisord.conf /etc/supervisor/conf.d/neomind.conf

# Default environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HOME=/data \
    TERM=xterm-256color

# NeoMind data directory (mounted as volume for persistence)
VOLUME ["/data/neomind"]

# Expose standalone sync port + health check port
EXPOSE 18790 18791

# Entrypoint
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# tini as PID 1 — proper signal forwarding + zombie reaping
ENTRYPOINT ["tini", "--", "/docker-entrypoint.sh"]
CMD ["--mode", "fin"]
