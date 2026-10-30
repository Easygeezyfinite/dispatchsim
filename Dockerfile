FROM python:3.11-slim

# Don't write .pyc files into the image and print logs straight away.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

# pyproject also lists numpy, pandas and pyarrow for the planned ETA model, but the
# API never imports them. Installing the package without dependencies and adding only
# what the API needs keeps the image a few hundred MB smaller.
RUN pip install --no-cache-dir --no-deps . \
    && pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.32"

# Run as a normal user instead of root.
RUN useradd --create-home dispatch
USER dispatch

EXPOSE 8000

# slim images don't ship curl, so the health check uses Python itself.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

# One worker on purpose: couriers and orders live in this process's memory, so a
# second worker would have its own separate city and requests would land in either.
CMD ["uvicorn", "dispatchsim.dispatch_service.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
