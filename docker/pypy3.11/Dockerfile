FROM pypy:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY benchmarks ./benchmarks
COPY tests ./tests

CMD ["pypy3", "-m", "benchmarks.benchmark", "--iterations", "10", "--repeat", "5"]
