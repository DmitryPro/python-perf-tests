# python-perf-tests

Набор микробенчмарков, предназначенных для сравнения производительности разных
версий Python (3.7–3.14) и PyPy 3.11 на одном и том же коде. Репозиторий содержит
унифицированные Dockerfile для каждой версии и тесты, проверяющие корректность
бенчмарков.

## Структура

- `benchmarks/compute.py` — набор задач для измерений: численные расчёты,
  поиск простых чисел, пузырьковая сортировка и JSON round-trip.
- `benchmarks/benchmark.py` — запускает задачи через `timeit` и сохраняет
  агрегированные результаты в JSON. Для каждого кейса записывается полное
  время каждого повтора (`runs`), среднее и стандартное отклонение по суммарному
  времени, а также дополнительные метрики в пересчёте на одну итерацию.
- `tests/` — pytests, валидирующие интерфейс и поведение бенчмарков.
- `docker/` — поддиректории с Dockerfile для каждой версии Python.

## Запуск локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
python -m benchmarks.benchmark --iterations 5 --repeat 3
```

После запуска `benchmarks.benchmark` результаты будут сохранены в каталоге
`results/` в файле вида `benchmarks-<интерпретатор>-<версия>.json`, например
`benchmarks-cpython-3.11.7.json` или `benchmarks-pypy-3.11.0.json`. Каждое
значение в блоке `runs` соответствует общему времени выполнения всех итераций
в рамках повтора, а в корне JSON теперь присутствуют поля
`python_implementation` и `python_version`, чтобы отличать CPython и PyPy с
одинаковыми версиями языка. Агрегированный файл `summary.json` с
человекочитаемой сводкой создаётся утилитой `benchmarks.docker_runner`.

## Специализированные замеры конкурентности для Python 3.14

Модуль `benchmarks.concurrency` запускает набор задач для демонстрации
ограничений GIL и поведения нового режима без GIL, который появится в CPython
3.14. Он сравнивает четыре стратегии — последовательную, многопоточную,
многопроцессную и subinterpreter — на CPU-ориентированной и I/O-ориентированной
нагрузках. Скрипт можно запустить напрямую:

```bash
python -m benchmarks.concurrency --tasks 24 --workers 4
```

В метаданных результирующего JSON есть поле `gil_disabled`, показывающее,
запускался ли интерпретатор с флагом `--disable-gil` (значение `True`), с
включённым GIL (`False`) или если окружение не может определить режим (`null`).
Имя файла по умолчанию принимает вид
`results/concurrency-<implementation>-<version>[-nogil].json`, чтобы измерения с
отключённым GIL не перезаписывали результаты обычного запуска.

Через `benchmarks.docker_runner` можно запустить оба режима автоматически:

```bash
python -m benchmarks.docker_runner --suite concurrency
```

Для CPython 3.14 (включая варианты вроде 3.14t) runner создаёт два запуска —
обычный и с `python --disable-gil`. Оба результата сохраняются в `results/` и
отражают, в каком режиме работал интерпретатор. Параметры `--tasks` и
`--workers` по-прежнему пробрасываются в оба запуска.

## Docker-образы

Для сборки образа конкретной версии Python используйте команды ниже.

```bash
# Пример для Python 3.11
docker build -f docker/py3.11/Dockerfile -t python-perf:3.11 .

# Пример для PyPy 3.11
docker build -f docker/pypy3.11/Dockerfile -t python-perf:pypy3.11 .
```

Запуск бенчмарка в контейнере:

```bash
docker run --rm python-perf:3.11

# Запуск бенчмарка под PyPy
docker run --rm python-perf:pypy3.11
```

Для запуска тестов вместо бенчмарка переопределите команду:

```bash
docker run --rm python-perf:3.11 python -m pytest -q

# Запуск тестов внутри PyPy-контейнера
docker run --rm python-perf:pypy3.11 pypy3 -m pytest -q
```

Аналогичные команды работают для остальных версий (3.7–3.14) и PyPy 3.11.

## Автоматическая сборка и запуск всех контейнеров

Чтобы собрать образы всех поддерживаемых версий Python и запустить бенчмарки,
используйте вспомогательный скрипт. Он автоматически пробрасывает локальный
каталог `results/` внутрь контейнеров, очищает его перед запуском и сохраняет
JSON с измерениями для каждой версии:

```bash
python -m benchmarks.docker_runner
```

Скрипт по умолчанию последовательно выполнит `docker build` и `docker run`
для каждого Dockerfile в каталоге `docker/`, после чего создаст агрегированный
отчёт `results/summary.json` и выведет его в читаемом виде в консоль. В сводке
показывается среднее и стандартное отклонение по суммарному времени каждого
повтора (т.е. за все итерации).
Дополнительные опции:

- `--dry-run` — только вывести команды Docker без исполнения;
- `--skip-build` или `--skip-run` — пропустить соответствующие этапы;
- `--run-cmd "python -m pytest -q"` — переопределить команду внутри контейнера.
- `--results-dir path/to/dir` — указать альтернативный каталог для сохранения
  результатов;
- `--no-aggregate` — не собирать агрегированный отчёт по завершении запуска.
- `--iterations N` и `--repeat M` — пробросить параметры итераций и повторов
  в `benchmarks.benchmark`, сохранив при этом стандартную команду внутри
  контейнеров.

Флаги `--iterations/--repeat` нельзя комбинировать с `--run-cmd`, поскольку в
этом случае команда целиком задаётся вручную.

Например, чтобы просто вывести список команд без запуска:

```bash
python -m benchmarks.docker_runner --dry-run
```

Набор микробенчмарков, предназначенных для сравнения производительности разных
версий Python (3.7–3.14) и PyPy 3.11 на одном и том же коде. Репозиторий содержит
унифицированные Dockerfile для каждой версии и тесты, проверяющие корректность
бенчмарков.

## Структура

- `benchmarks/compute.py` — набор задач для измерений: численные расчёты,
  поиск простых чисел, пузырьковая сортировка и JSON round-trip.
- `benchmarks/benchmark.py` — запускает задачи через `timeit` и сохраняет
  агрегированные результаты в JSON.
- `tests/` — pytests, валидирующие интерфейс и поведение бенчмарков.
- `docker/` — поддиректории с Dockerfile для каждой версии Python.

## Запуск локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
python -m benchmarks.benchmark --iterations 5 --repeat 3
```

После запуска `benchmarks.benchmark` результаты будут сохранены в каталоге
`results/` в файле вида `benchmarks-<интерпретатор>-<версия>.json`, например
`benchmarks-cpython-3.11.7.json` или `benchmarks-pypy-3.11.0.json`. Агрегированный
файл `summary.json` формируется утилитой `benchmarks.docker_runner`.

## Docker-образы

Для сборки образа конкретной версии Python используйте команды ниже.

```bash
# Пример для Python 3.11
docker build -f docker/py3.11/Dockerfile -t python-perf:3.11 .

# Пример для PyPy 3.11
docker build -f docker/pypy3.11/Dockerfile -t python-perf:pypy3.11 .
```

Запуск бенчмарка в контейнере:

```bash
docker run --rm python-perf:3.11

# Запуск бенчмарка под PyPy
docker run --rm python-perf:pypy3.11
```

Для запуска тестов вместо бенчмарка переопределите команду:

```bash
docker run --rm python-perf:3.11 python -m pytest -q

# Запуск тестов внутри PyPy-контейнера
docker run --rm python-perf:pypy3.11 pypy3 -m pytest -q
```

Аналогичные команды работают для остальных версий (3.7–3.14) и PyPy 3.11.

## Автоматическая сборка и запуск всех контейнеров

Чтобы собрать образы всех поддерживаемых версий Python и запустить бенчмарки,
используйте вспомогательный скрипт. Он автоматически пробрасывает локальный
каталог `results/` внутрь контейнеров, чтобы сохранить JSON с измерениями для
каждой версии:

```bash
python -m benchmarks.docker_runner
```

Скрипт по умолчанию последовательно выполнит `docker build` и `docker run`
для каждого Dockerfile в каталоге `docker/`, после чего создаст агрегированный
отчёт `results/summary.json` и выведет его в читаемом виде в консоль.
Дополнительные опции:

- `--dry-run` — только вывести команды Docker без исполнения;
- `--skip-build` или `--skip-run` — пропустить соответствующие этапы;
- `--run-cmd "python -m pytest -q"` — переопределить команду внутри контейнера.
- `--results-dir path/to/dir` — указать альтернативный каталог для сохранения
  результатов;
- `--no-aggregate` — не собирать агрегированный отчёт по завершении запуска.
- `--iterations N` и `--repeat M` — пробросить параметры итераций и повторов
  в `benchmarks.benchmark`, сохранив при этом стандартную команду внутри
  контейнеров.

Флаги `--iterations/--repeat` нельзя комбинировать с `--run-cmd`, поскольку в
этом случае команда целиком задаётся вручную.

Например, чтобы просто вывести список команд без запуска:

```bash
python -m benchmarks.docker_runner --dry-run
```

Набор микробенчмарков, предназначенных для сравнения производительности разных
версий Python (3.7–3.14) и PyPy 3.11 на одном и том же коде. Репозиторий содержит
унифицированные Dockerfile для каждой версии и тесты, проверяющие корректность
бенчмарков.

## Структура

- `benchmarks/compute.py` — набор задач для измерений: численные расчёты,
  поиск простых чисел и JSON round-trip.
- `benchmarks/benchmark.py` — запускает задачи через `timeit` и сохраняет
  агрегированные результаты в JSON.
- `tests/` — pytests, валидирующие интерфейс и поведение бенчмарков.
- `docker/` — поддиректории с Dockerfile для каждой версии Python.

## Запуск локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
python -m benchmarks.benchmark --iterations 5 --repeat 3
```

После запуска `benchmarks.benchmark` результаты будут сохранены в каталоге
`results/` в файле вида `benchmarks-<интерпретатор>-<версия>.json`, например
`benchmarks-cpython-3.11.7.json` или `benchmarks-pypy-3.11.0.json`. Агрегированный
файл `summary.json` формируется утилитой `benchmarks.docker_runner`.

## Docker-образы

Для сборки образа конкретной версии Python используйте команды ниже.

```bash
# Пример для Python 3.11
docker build -f docker/py3.11/Dockerfile -t python-perf:3.11 .

# Пример для PyPy 3.11
docker build -f docker/pypy3.11/Dockerfile -t python-perf:pypy3.11 .
```

Запуск бенчмарка в контейнере:

```bash
docker run --rm python-perf:3.11

# Запуск бенчмарка под PyPy
docker run --rm python-perf:pypy3.11
```

Для запуска тестов вместо бенчмарка переопределите команду:

```bash
docker run --rm python-perf:3.11 python -m pytest -q

# Запуск тестов внутри PyPy-контейнера
docker run --rm python-perf:pypy3.11 pypy3 -m pytest -q
```

Аналогичные команды работают для остальных версий (3.7–3.14) и PyPy 3.11.

## Автоматическая сборка и запуск всех контейнеров

Чтобы собрать образы всех поддерживаемых версий Python и запустить бенчмарки,
используйте вспомогательный скрипт. Он автоматически пробрасывает локальный
каталог `results/` внутрь контейнеров, чтобы сохранить JSON с измерениями для
каждой версии:

```bash
python -m benchmarks.docker_runner
```

Скрипт по умолчанию последовательно выполнит `docker build` и `docker run`
для каждого Dockerfile в каталоге `docker/`, после чего создаст агрегированный
отчёт `results/summary.json` и выведет его в читаемом виде в консоль.
Дополнительные опции:

- `--dry-run` — только вывести команды Docker без исполнения;
- `--skip-build` или `--skip-run` — пропустить соответствующие этапы;
- `--run-cmd "python -m pytest -q"` — переопределить команду внутри контейнера.
- `--results-dir path/to/dir` — указать альтернативный каталог для сохранения
  результатов;
- `--no-aggregate` — не собирать агрегированный отчёт по завершении запуска.

Например, чтобы просто вывести список команд без запуска:

```bash
python -m benchmarks.docker_runner --dry-run
```

Набор микробенчмарков, предназначенных для сравнения производительности разных
версий Python (3.7–3.14) и PyPy 3.11 на одном и том же коде. Репозиторий содержит
унифицированные Dockerfile для каждой версии и тесты, проверяющие корректность
бенчмарков.

## Структура

- `benchmarks/compute.py` — набор задач для измерений: численные расчёты,
  поиск простых чисел и JSON round-trip.
- `benchmarks/benchmark.py` — запускает задачи через `timeit` и сохраняет
  агрегированные результаты в JSON.
- `tests/` — pytests, валидирующие интерфейс и поведение бенчмарков.
- `docker/` — поддиректории с Dockerfile для каждой версии Python.

## Запуск локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
python -m benchmarks.benchmark --iterations 5 --repeat 3
```

После запуска `benchmarks.benchmark` результаты будут сохранены в каталоге
`results/` в файле вида `benchmarks-<интерпретатор>-<версия>.json`, например
`benchmarks-cpython-3.11.7.json` или `benchmarks-pypy-3.11.0.json`.

## Docker-образы

Для сборки образа конкретной версии Python используйте команды ниже.

```bash
# Пример для Python 3.11
docker build -f docker/py3.11/Dockerfile -t python-perf:3.11 .

# Пример для PyPy 3.11
docker build -f docker/pypy3.11/Dockerfile -t python-perf:pypy3.11 .
```

Запуск бенчмарка в контейнере:

```bash
docker run --rm python-perf:3.11

# Запуск бенчмарка под PyPy
docker run --rm python-perf:pypy3.11
```

Для запуска тестов вместо бенчмарка переопределите команду:

```bash
docker run --rm python-perf:3.11 python -m pytest -q

# Запуск тестов внутри PyPy-контейнера
docker run --rm python-perf:pypy3.11 pypy3 -m pytest -q
```

Аналогичные команды работают для остальных версий (3.7–3.14) и PyPy 3.11.

## Автоматическая сборка и запуск всех контейнеров

Чтобы собрать образы всех поддерживаемых версий Python и запустить бенчмарки,
используйте вспомогательный скрипт:

```bash
python -m benchmarks.docker_runner
```

Скрипт по умолчанию последовательно выполнит `docker build` и `docker run`
для каждого Dockerfile в каталоге `docker/`. Дополнительные опции:

- `--dry-run` — только вывести команды Docker без исполнения;
- `--skip-build` или `--skip-run` — пропустить соответствующие этапы;
- `--run-cmd "python -m pytest -q"` — переопределить команду внутри контейнера.

Например, чтобы просто вывести список команд без запуска:

```bash
python -m benchmarks.docker_runner --dry-run
```

Набор микробенчмарков, предназначенных для сравнения производительности разных
версий Python (3.7–3.14) и PyPy 3.11 на одном и том же коде. Репозиторий содержит
унифицированные Dockerfile для каждой версии и тесты, проверяющие корректность
бенчмарков.

## Структура

- `benchmarks/compute.py` — набор задач для измерений: численные расчёты,
  поиск простых чисел и JSON round-trip.
- `benchmarks/benchmark.py` — запускает задачи через `timeit` и сохраняет
  агрегированные результаты в JSON.
- `tests/` — pytests, валидирующие интерфейс и поведение бенчмарков.
- `docker/` — поддиректории с Dockerfile для каждой версии Python.

## Запуск локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
python -m benchmarks.benchmark --iterations 5 --repeat 3
```

После запуска `benchmarks.benchmark` результаты будут сохранены в каталоге
`results/` в файле вида `benchmarks-<интерпретатор>-<версия>.json`, например
`benchmarks-cpython-3.11.7.json` или `benchmarks-pypy-3.11.0.json`.

## Docker-образы

Для сборки образа конкретной версии Python используйте команды ниже.

```bash
# Пример для Python 3.11
docker build -f docker/py3.11/Dockerfile -t python-perf:3.11 .

# Пример для PyPy 3.11
docker build -f docker/pypy3.11/Dockerfile -t python-perf:pypy3.11 .
```

Запуск бенчмарка в контейнере:

```bash
docker run --rm python-perf:3.11

# Запуск бенчмарка под PyPy
docker run --rm python-perf:pypy3.11
```

Для запуска тестов вместо бенчмарка переопределите команду:

```bash
docker run --rm python-perf:3.11 python -m pytest -q

# Запуск тестов внутри PyPy-контейнера
docker run --rm python-perf:pypy3.11 pypy3 -m pytest -q
```

Аналогичные команды работают для остальных версий (3.7–3.14) и PyPy 3.11.
