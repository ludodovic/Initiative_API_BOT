FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

RUN groupadd --system initiative \
    && useradd --system --gid initiative --create-home initiative

COPY --chown=initiative:initiative app ./app

RUN mkdir -p /app/uploads/claims /app/uploads/profile_pictures \
    && chown -R initiative:initiative /app/uploads

USER initiative

EXPOSE 8000
VOLUME ["/app/uploads"]

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
