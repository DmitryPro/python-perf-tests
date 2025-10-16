FROM makukha/multipython

WORKDIR /app

COPY requirements.txt ./
RUN ln -sf /usr/local/bin/python3.14t /usr/local/bin/python && \
    python -V && \
    python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

COPY benchmarks ./benchmarks
COPY tests ./tests

CMD ["python", "-m", "benchmarks.benchmark", "--iterations", "10", "--repeat", "5"]
