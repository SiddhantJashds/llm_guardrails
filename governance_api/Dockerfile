FROM python:3.12-slim
WORKDIR /app
COPY governance_api/requirements.txt governance_api/requirements.txt
RUN pip install --no-cache-dir -r governance_api/requirements.txt psycopg2-binary
COPY shared shared
COPY governance_api governance_api
WORKDIR /app/governance_api
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
