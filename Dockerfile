# SheetAgent container image.
#
# NOTE ON SCOPE: the Excel COM engine drives the real Microsoft Excel
# application and therefore requires Windows + an Excel installation. Linux
# containers cannot provide that, so this image runs the headless openpyxl
# engine and the agent says so in its result (`engine`, `fallback_reason`,
# `warning`) rather than silently pretending Excel ran. Everything else -
# planning, the tool-calling loop, CSV generation, Google Sheets, verification,
# the MCP server - is fully functional here.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SHEETAGENT_EXCEL_ENGINE=openpyxl

WORKDIR /app

# Dependencies first so the layer caches across source edits.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY sheetagent/ ./sheetagent/
COPY config.yaml ./

# Writable, and mountable so artifacts survive the container.
RUN mkdir -p output logs memory && \
    useradd --create-home --uid 10001 agent && \
    chown -R agent:agent /app
USER agent

VOLUME ["/app/output", "/app/logs", "/app/memory"]

ENTRYPOINT ["python", "-m", "sheetagent"]
CMD ["Create a sample employee CSV and import it into Excel and Google Sheets."]
