FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY desk/ desk/
COPY cases/ cases/
COPY tests/ tests/
COPY env/data/ env/data/

# Secrets come from --env-file / Compose at runtime. Never bake .env into the image.
ENV PYTHONUNBUFFERED=1
ENV OPS_BASE_URL=http://127.0.0.1:8642

ENTRYPOINT ["python", "-m", "desk"]
