FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV QA_STANDARDS_PATH=/app/standards/packs

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY standards ./standards
COPY evaluation ./evaluation
COPY knowledge ./knowledge

RUN pip install --no-cache-dir .

CMD ["sumo-qa"]
