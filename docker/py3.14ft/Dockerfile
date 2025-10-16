FROM makukha/multipython:latest
WORKDIR /app

COPY requirements.txt .
RUN python3.14t -m pip install --upgrade pip && \
    python3.14t -m pip install --no-cache-dir -r requirements.txt

COPY benchmarks ./benchmarks
COPY tests ./tests

# Запускаем без GIL
CMD ["python", "-X", "gil=0", "-m", "benchmarks.benchmark", "--iterations", "10", "--repeat", "5"]
