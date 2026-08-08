FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

RUN mkdir -p /data /media/ebooks /media/music

VOLUME ["/data"]

ENTRYPOINT ["foliotone"]
CMD ["status"]
