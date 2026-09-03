# Агент специфікації в контейнері. Збірка з кореня module8/:
#   docker build --provenance=false --sbom=false -t spec-agent-m8:local -f practice/Dockerfile .
# Ключ — тільки через env/Secret, в образі його немає. Вектори теж не тут:
# вони живуть у сусідньому контейнері Qdrant того самого пода (deploy/pod.yaml),
# і агент ходить до них на localhost:6333.

FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir anthropic python-dotenv fastapi uvicorn \
    "mcp[cli]>=2.1" fastembed==0.8.0

# Модель векторів кладеться в образ на збірці, щоб под не тягнув її 128 МБ
# з інтернету на кожному старті.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

COPY config.py ./
COPY core/ core/
COPY practice/__init__.py practice/api.py practice/
COPY practice/base/ practice/base/
COPY practice/common/ practice/common/
COPY practice/docs-full/ practice/docs-full/
COPY practice/docs-suite/ practice/docs-suite/

# Рішення про пошук за змістом ухвалене на збірці. Колекцію в под завозить
# deploy/up.sh; поки її немає, сервер знань сам чесно з'їжджає на пошук по словах.
RUN mkdir -p practice/out && printf '{"search": "vectors"}\n' > practice/out/mode.json

# Сервер знань грів би вектори у фоновому потоці й перші запити мовчки йшли б
# по словах; сервіс натомість чекає на прогрів і шукає за змістом з першого запиту.
ENV PRACTICE_VECTORS_WAIT=1

EXPOSE 8000
CMD ["uvicorn", "practice.api:app", "--host", "0.0.0.0", "--port", "8000"]
