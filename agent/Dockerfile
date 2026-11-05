# Transcritor das salas. Roda numa máquina PRÓPRIA, não na da aula.
#
#   docker build -t bwl-transcritor .                    # CPU (ou Deepgram)
#   docker build --build-arg COM_GPU=1 -t bwl-transcritor .
#
# Com GPU é preciso também `--gpus all` (ou `runtime: nvidia` no compose) e o
# driver NVIDIA no host; as bibliotecas CUDA vêm por wheel, não da imagem.
FROM python:3.11-slim

ARG COM_GPU=0
WORKDIR /app

COPY requirements.txt requirements-gpu.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && if [ "$COM_GPU" = "1" ]; then pip install --no-cache-dir -r requirements-gpu.txt; fi

COPY *.py ./
COPY provas ./provas

# O cache do modelo fica num volume: sem isto, cada `docker compose up` baixa
# 1,6 GB do Hugging Face de novo — e, pior, a primeira fala da primeira aula
# depois de cada deploy espera por esse download.
ENV HF_HOME=/cache/hf
VOLUME ["/cache"]

# `-u`: log sem buffer. Com buffer, o `docker logs` de um agente que travou não
# mostra a última linha — justamente a que diz por quê.
CMD ["python", "-u", "transcritor.py"]
