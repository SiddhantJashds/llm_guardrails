FROM python:3.12-slim
WORKDIR /app
COPY governance_api/requirements.txt governance_api/requirements.txt
COPY detectors/requirements.txt detectors/requirements.txt
RUN pip install --no-cache-dir -r governance_api/requirements.txt -r detectors/requirements.txt psycopg2-binary
COPY shared shared
COPY detectors detectors
COPY governance_api governance_api
WORKDIR /app/governance_api
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
