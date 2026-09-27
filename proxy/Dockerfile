FROM python:3.12-slim
WORKDIR /app
COPY proxy/requirements.txt proxy/requirements.txt
RUN pip install --no-cache-dir -r proxy/requirements.txt
COPY shared shared
COPY proxy proxy
WORKDIR /app/proxy
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
