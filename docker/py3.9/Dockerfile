FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY benchmarks ./benchmarks
COPY tests ./tests

CMD ["python", "-m", "benchmarks.benchmark", "--iterations", "10", "--repeat", "5"]
