FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY context_budgeter ./context_budgeter
RUN pip install --no-cache-dir . && useradd --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "context_budgeter.api:app", "--host", "0.0.0.0", "--port", "8000"]
