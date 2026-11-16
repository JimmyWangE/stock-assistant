FROM python:3.11-slim

# 可选：国内构建时传入 pip 镜像地址
ARG PIP_INDEX_URL=
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /srv
COPY requirements.txt .
RUN if [ -n "$PIP_INDEX_URL" ]; then pip config set global.index-url "$PIP_INDEX_URL"; fi \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
