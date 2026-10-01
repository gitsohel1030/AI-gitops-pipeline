FROM python:3.10-slim
 
WORKDIR /app
 
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
 
COPY app/ .
 
# model.pkl is produced by the CI training step and copied in
# right before docker build runs — see .github/workflows/ml-pipeline.yml
COPY model.pkl .
 
ENV MODEL_VERSION=v3
ENV AWS_REGION=ap-south-1
ENV MODEL_S3_BUCKET=mlflow-artifacts-608827180555
ENV MODEL_S3_KEY=""
 
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
 
EXPOSE 8000
 
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
 
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
