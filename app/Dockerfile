FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /workspace

COPY pyproject.toml ./
COPY app ./app

RUN pip install --no-cache-dir .

CMD ["sh", "-c", "streamlit run app/streamlit_app.py --server.port ${PORT} --server.address 0.0.0.0"]
