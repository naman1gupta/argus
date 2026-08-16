FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The build context is the repo root so the local SDK package can be installed.
COPY sdk /sdk
COPY server/requirements.txt /app/requirements.txt
RUN sed 's|-e ../sdk|-e /sdk|' /app/requirements.txt > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt

COPY server /app

EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
