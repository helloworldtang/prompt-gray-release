FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY gray_release ./gray_release
COPY prompts ./prompts
COPY datasets ./datasets
COPY config ./config

RUN pip install --no-cache-dir .

EXPOSE 8080
CMD ["python", "-m", "gray_release", "serve", "--host", "0.0.0.0", "--port", "8080"]
