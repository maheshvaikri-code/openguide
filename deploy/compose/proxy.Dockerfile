# OpenGuide proxy image.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY guidancegrid ./guidancegrid
COPY proxy ./proxy
COPY spec ./spec

RUN pip install --no-cache-dir ".[proxy,otel,obc]"

EXPOSE 8088
CMD ["uvicorn", "proxy.server:app", "--host", "0.0.0.0", "--port", "8088"]
