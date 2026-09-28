FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY oms ./oms
COPY manage.py cloud_serve.py cloud_transfer.py ./
ENV PYTHONUNBUFFERED=1 OMS_CLOUD=1 OMS_HTTPS=1 OMS_INSTANCE_PATH=/data
EXPOSE 8080
CMD ["python", "cloud_serve.py"]
