FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY bridge ./bridge
COPY tests ./tests
COPY integration ./integration
USER 65532:65532
CMD ["python", "-m", "bridge", "demo"]
