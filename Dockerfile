# SheetAgent - CI / headless test-runner image.
#
# ---------------------------------------------------------------------------
# SCOPE: THIS IS NOT A DEPLOYMENT OF THE FULL AGENT.
#
# The assignment's Excel requirement is to launch the real Microsoft Excel
# application. SheetAgent does that through COM (pywin32), which requires
# Windows and an installed copy of Excel. A Linux container has neither, and
# pywin32 is marker-gated in requirements.txt so it is not even installed here.
#
# What this image therefore CANNOT do:
#   * launch Microsoft Excel
#   * exercise the COM engine, its error classification, or its cleanup paths
#
# What it IS for:
#   * running the test suite reproducibly (the same thing CI does)
#   * exercising the planner, the tool-calling loop, CSV generation, the Google
#     Sheets integration, verification and the MCP server
#   * proving the openpyxl fallback produces an equivalent workbook headlessly
#
# For the real-Excel demo, and for any use that is meant to satisfy the Excel
# requirement, run natively on Windows:
#
#     python -m sheetagent "Create a sample employee CSV and import it into
#                           Excel and Google Sheets."
#
# The agent reports `engine: openpyxl` plus a `warning` whenever it runs this
# way, so a container run is never mistakable for a run that drove Excel.
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Pinned, not merely defaulted: `auto` would also pick openpyxl here, but
    # being explicit means the image never appears to have "tried" COM.
    SHEETAGENT_EXCEL_ENGINE=openpyxl

WORKDIR /app

# Dependencies first so the layer caches across source edits.
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY sheetagent/ ./sheetagent/
COPY tests/ ./tests/
COPY config.yaml ./

RUN mkdir -p output logs memory && \
    useradd --create-home --uid 10001 agent && \
    chown -R agent:agent /app
USER agent

VOLUME ["/app/output", "/app/logs", "/app/memory"]

# Default to the test suite, because testing is what this image is for.
# Override the command to run the agent headlessly:
#   docker run --rm sheetagent python -m sheetagent --test-mode "..."
CMD ["pytest", "-q"]
