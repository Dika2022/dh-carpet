FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY backend/ ./
COPY integrations/1c/SalesAdapter.bsl /integrations/1c/SalesAdapter.bsl
COPY integrations/1c/CustomerReturnsAdapter.bsl /integrations/1c/CustomerReturnsAdapter.bsl
COPY integrations/1c/tests/confirmed-metadata.json /integrations/1c/tests/confirmed-metadata.json

RUN pip install --no-cache-dir .

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
