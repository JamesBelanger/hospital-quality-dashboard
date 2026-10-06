# "Ask the data" service: FastAPI + the answer pipeline. Database and model credentials
# come from the environment at run time; nothing secret is baked into the image.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY service/requirements.txt service/requirements.txt
RUN pip install -r service/requirements.txt

COPY service/ service/

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
CMD ["uvicorn", "service.api:app", "--host", "0.0.0.0", "--port", "8000"]
