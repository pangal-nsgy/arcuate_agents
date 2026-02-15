FROM python:3.12-slim

WORKDIR /app

# Copy everything needed for install + runtime
COPY pyproject.toml .
COPY src/ src/
COPY scripts/ scripts/
COPY agents/ agents/
COPY agent_memory/ agent_memory/
COPY architecture_changelog.yaml .

# Install Python dependencies (needs src/ present for the package build)
RUN pip install --no-cache-dir .

# Data directories (Railway volume mounts here)
RUN mkdir -p /app/data /tmp
ENV CHROMA_PERSIST_DIR=/app/data/chroma_data
ENV SQLITE_DB_PATH=/app/data/chief_of_staff.db
ENV AGENTS_DIR=/app/agents
ENV AGENT_MEMORY_DIR=/app/agent_memory
ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD uvicorn chief_of_staff.main:app --host 0.0.0.0 --port ${PORT:-8000}
