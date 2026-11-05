# -*- coding: utf-8 -*-
"""O transcritor: entra nas salas, ouve cada participante, devolve o texto.

    python -B transcritor.py                 # roda
    python -B transcritor.py --uma-rodada    # pergunta as salas, mostra, e sai

## O que ele é

Um processo que roda FORA do servidor da aula (reconhecimento de fala quer GPU;
a Lightsail do app não tem) e faz três coisas em ciclo:

    1. pergunta ao backend em que salas entrar          (GET  /api/internal/transcricao/salas)
    2. entra, assina as faixas de ÁUDIO, corta em falas (LiveKit + segmentacao.py)
    3. devolve cada fala com quem falou                 (POST /api/internal/transcricao)

Ele não publica nada e entra como `hidden`: ninguém na sala o vê. Só o backend
sabe que ele existe -- e `services/presenca.py`, que o remove da contagem de
presentes, porque a API de servidor do LiveKit lista participantes escondidos e
um "aluno" que nunca vota travaria a cadência.

## Por que ele PERGUNTA em vez de ser avisado

O LiveKit manda `room_started` por webhook, e o backend já o recebe. Mas evento
perdido não volta: o agente reiniciado no meio de um encontro ficaria fora dele
até o próximo. Perguntando a cada rodada, o pior caso é entrar alguns segundos
depois -- e o processo pode morrer e voltar sem ninguém intervir.

## A identificação é de graça, e é o ponto

No LiveKit cada faixa de áudio pertence a um participante. "Quem falou" sai da
faixa, não de um palpite por timbre. É por isso que não dá para usar um
gravador de reunião de prateleira aqui: o Fireflies entra em Zoom, Meet e
Teams, não numa sala LiveKit própria, e as saídas dele exigem uma PESSOA
rodando captura na sala -- a figura que a facilitação autônoma remove.

## Falar não é esperar

O reconhecimento roda em thread (`asyncio.to_thread`), nunca no laço de
eventos: uma transcrição de 2 s dentro do laço congelaria a leitura de áudio de
TODAS as salas por 2 s, e o áudio perdido não volta. A fila tem teto; quando
estoura, o descarte é CONTADO e registrado -- transcrição que some em silêncio
pareceria uma aula calada.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
from livekit import rtc

import asr
from segmentacao import LIMIAR_DE_VOZ, Fatiador, vale_gravar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("transcritor")

# ── Quem é gente ─────────────────────────────────────────────────────────────
#
# SEGUNDA CÓPIA, de propósito: este processo não importa o backend. É a mesma
# situação de `ORDEM` em `cadencia.py`, que repete `_STAGES` do router -- e a
# mesma solução: `backend/provas/prova_transcricao.py` confere que as duas
# listas não divergiram. Sem a prova, o dia em que o gravador mudar de prefixo
# o transcritor passa a transcrever a aula duas vezes, com o nome errado.
PREFIXO_DO_GRAVADOR = "EG_"
PREFIXO_DO_TRANSCRITOR = "TR_"
SUFIXO_DO_ESPELHO = "__bc"


def e_pessoa(identity: str) -> bool:
    """A identidade é de uma pessoa, e não do gravador/transcritor/espelho?"""
    if not identity:
        return False
    if identity.startswith(PREFIXO_DO_GRAVADOR):
        return False
    if identity.startswith(PREFIXO_DO_TRANSCRITOR):
        return False
    if identity.endswith(SUFIXO_DO_ESPELHO):
        return False
    return True


# ── Configuração ─────────────────────────────────────────────────────────────

API = (os.getenv("TRANSCRITOR_API") or "https://video.pbltools.io").rstrip("/")
SEGREDO = os.getenv("NODE_SECRET", "")
#: De quanto em quanto tempo se pergunta a lista de salas. 15 s: entrar
#: atrasado custa as primeiras frases de uma etapa; perguntar a cada segundo
#: custa uma chamada ao LiveKit por segundo, para sempre.
INTERVALO = float(os.getenv("TRANSCRITOR_INTERVALO", "15"))
#: Falas à espera do reconhecedor. Com Whisper numa GPU modesta, 2 s de fala
#: levam ~0,3 s; 64 é folga de minutos. Estourar significa máquina pequena
#: demais para o número de salas -- e o log diz exatamente isso.
FILA_MAXIMA = int(os.getenv("TRANSCRITOR_FILA", "64"))
TRABALHADORES = int(os.getenv("TRANSCRITOR_TRABALHADORES", "1"))
#: Energia acima da qual se considera que há voz. Vem do ambiente porque o
#: valor certo depende do microfone da turma, e descobri-lo exige medir com uma
#: sala de verdade -- esperar um deploy para cada ajuste travaria a medição.
LIMIAR = float(os.getenv("TRANSCRITOR_LIMIAR_DE_VOZ", str(LIMIAR_DE_VOZ)))
TAXA = asr.TAXA
#: 2 bytes por amostra (PCM 16 bits, mono).
BYTES_POR_MS = TAXA * 2 // 1000


@dataclass
class Fala:
    """Uma fala fechada, à espera do reconhecedor."""

    room_id: str
    identity: str
    nome: str
    inicio: datetime
    fim: datetime
    pcm: bytes


@dataclass
class Sessao:
    """A presença do agente em UMA sala."""

    room_id: str
    sala: str
    url: str
    token: str
    fila: asyncio.Queue
    room: rtc.Room = field(default_factory=rtc.Room)
    tarefas: set[asyncio.Task] = field(default_factory=set)
    descartadas: int = 0

    async def conectar(self) -> None:
        @self.room.on("track_subscribed")
        def _assinou(track: rtc.Track, pub: rtc.TrackPublication,
                     participante: rtc.RemoteParticipant) -> None:
            # O handler do SDK é SÍNCRONO: ele só pode agendar a leitura.
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            if not e_pessoa(participante.identity):
                # O gravador republica o áudio de todos: transcrevê-lo
                # duplicaria a aula inteira, atribuída a "EG_...".
                logger.info("[%s] ignorando faixa de %s", self.sala, participante.identity)
                return
            t = asyncio.create_task(self._ouvir(track, participante))
            self.tarefas.add(t)
            t.add_done_callback(self.tarefas.discard)

        # `auto_subscribe=True` já é o padrão; o token é que limita a áudio --
        # ele não pode publicar nada e só precisa assinar. Assinar vídeo também
        # custaria banda por participante sem nenhum uso.
        await self.room.connect(self.url, self.token)
        logger.info("[%s] conectado como ouvinte", self.sala)

    async def _ouvir(self, track: rtc.Track, participante: rtc.RemoteParticipant) -> None:
        """Lê o áudio de UM participante e enfileira as falas dele."""
        fatiador = Fatiador(limiar_de_voz=LIMIAR)
        buffer = bytearray()
        inicio: datetime | None = None
        stream = rtc.AudioStream(track, sample_rate=TAXA, num_channels=1)
        try:
            async for evento in stream:
                quadro = evento.frame
                dados = bytes(quadro.data)
                ms = int(quadro.samples_per_channel * 1000 / (quadro.sample_rate or TAXA))
                if ms <= 0:
                    continue
                amostras = np.frombuffer(dados, dtype="<i2").astype("float32") / 32768.0
                energia = float(np.sqrt(np.mean(amostras * amostras))) if amostras.size else 0.0

                corte = fatiador.alimentar(energia, ms)
                if fatiador.aberta or corte is not None:
                    if inicio is None:
                        # O quadro acabou de chegar: o começo da fala é agora
                        # menos a duração dele. O relógio é o da chegada, não o
                        # do fim do reconhecimento -- senão a transcrição sairia
                        # ordenada pelo tempo de GPU.
                        inicio = datetime.now(timezone.utc) - timedelta(milliseconds=ms)
                    buffer += dados

                if corte is None:
                    continue

                uteis = buffer[:corte.ms_uteis * BYTES_POR_MS]
                if corte.vale and uteis and inicio is not None:
                    self._enfileirar(Fala(
                        room_id=self.room_id,
                        identity=participante.identity,
                        nome=participante.name or participante.identity,
                        inicio=inicio,
                        fim=inicio + timedelta(milliseconds=corte.ms_uteis),
                        pcm=bytes(uteis),
                    ))
                buffer.clear()
                inicio = None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[%s] leitura de %s caiu", self.sala, participante.identity)
        finally:
            # A última frase de quem desconecta morreria no buffer -- e costuma
            # ser a resposta que ninguém mais ouviu.
            corte = fatiador.fechar_agora()
            if corte and corte.vale and inicio is not None:
                uteis = buffer[:corte.ms_uteis * BYTES_POR_MS]
                if uteis:
                    self._enfileirar(Fala(
                        room_id=self.room_id, identity=participante.identity,
                        nome=participante.name or participante.identity,
                        inicio=inicio,
                        fim=inicio + timedelta(milliseconds=corte.ms_uteis),
                        pcm=bytes(uteis)))

    def _enfileirar(self, fala: Fala) -> None:
        try:
            self.fila.put_nowait(fala)
        except asyncio.QueueFull:
            self.descartadas += 1
            logger.error("[%s] FILA CHEIA: %d fala(s) descartada(s) nesta sala. "
                         "A máquina não dá conta do volume -- a transcrição está "
                         "incompleta, não vazia.", self.sala, self.descartadas)

    async def desconectar(self) -> None:
        for t in list(self.tarefas):
            t.cancel()
        for t in list(self.tarefas):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        with contextlib.suppress(Exception):
            await self.room.disconnect()
        logger.info("[%s] saiu", self.sala)


# ── Conversa com o backend ───────────────────────────────────────────────────


async def buscar_salas(cliente: httpx.AsyncClient) -> list[dict] | None:
    """As salas a transcrever agora, ou `None` se não deu para perguntar.

    `None` e `[]` são coisas DIFERENTES e o chamador trata diferente: lista
    vazia quer dizer "nenhuma sala ativa" (sai de todas); falha quer dizer "não
    sei" (fica onde está). Confundir as duas faria o agente abandonar um
    encontro em andamento porque o backend piscou.
    """
    try:
        r = await cliente.get(f"{API}/api/internal/transcricao/salas",
                              headers={"X-Node-Secret": SEGREDO}, timeout=20.0)
    except Exception as e:
        logger.warning("[salas] não deu para perguntar: %s", e)
        return None
    if r.status_code == 401:
        # Não é "nenhuma sala": é o agente sem credencial. Erro alto, porque o
        # sintoma de um NODE_SECRET errado é uma transcrição que nunca aparece.
        logger.error("[salas] 401: NODE_SECRET não confere com o do backend")
        return None
    if r.status_code != 200:
        logger.warning("[salas] HTTP %s", r.status_code)
        return None
    return list((r.json() or {}).get("salas") or [])


async def mandar(cliente: httpx.AsyncClient, fala: Fala, texto: str, motor: str) -> bool:
    """Devolve a fala ao backend. Três tentativas; o servidor é idempotente."""
    corpo = {
        "room_id": fala.room_id,
        "identity": fala.identity,
        "nome": fala.nome,
        "inicio": fala.inicio.isoformat(),
        "fim": fala.fim.isoformat(),
        "texto": texto,
        "motor": motor,
    }
    for tentativa in (1, 2, 3):
        try:
            r = await cliente.post(f"{API}/api/internal/transcricao", json=corpo,
                                   headers={"X-Node-Secret": SEGREDO}, timeout=20.0)
            if r.status_code == 200:
                return True
            logger.warning("[envio] HTTP %s (tentativa %d)", r.status_code, tentativa)
            if r.status_code in (400, 401, 403):
                return False      # repetir não conserta credencial nem formato
        except Exception as e:
            logger.warning("[envio] %s (tentativa %d)", e, tentativa)
        await asyncio.sleep(tentativa * 2)
    return False


async def trabalhador(n: int, fila: asyncio.Queue, motor, cliente: httpx.AsyncClient) -> None:
    """Tira falas da fila, reconhece e devolve. Um por vez, por desenho.

    O reconhecimento vai para uma thread: no laço de eventos ele pararia a
    leitura de áudio de todas as salas pelo tempo que levasse.
    """
    while True:
        fala: Fala = await fila.get()
        try:
            texto = await asyncio.to_thread(motor.transcrever, fala.pcm, TAXA)
            if not vale_gravar(texto):
                # Vazio, ou uma das frases que o Whisper inventa em silêncio.
                # Gravar poria na boca de alguém algo que ele não disse.
                logger.debug("[%d] descartado: %r", n, texto[:60])
                continue
            await mandar(cliente, fala, texto, motor.nome)
            logger.info("[%d] %s: %s", n, fala.nome, texto[:120])
        except Exception:
            logger.exception("[%d] falha ao transcrever fala de %s", n, fala.identity)
        finally:
            fila.task_done()


async def principal(uma_rodada: bool = False) -> int:
    if not SEGREDO:
        logger.error("NODE_SECRET vazio: o backend recusaria tudo com 401.")
        return 2
    motor = asr.motor_do_ambiente()
    logger.info("motor: %s | api: %s | intervalo: %ss", motor.nome, API, INTERVALO)

    fila: asyncio.Queue = asyncio.Queue(maxsize=FILA_MAXIMA)
    sessoes: dict[str, Sessao] = {}
    async with httpx.AsyncClient() as cliente:
        if uma_rodada:
            salas = await buscar_salas(cliente)
            logger.info("salas: %s", [s.get("sala") for s in (salas or [])])
            return 0 if salas is not None else 1

        trabalhadores = [asyncio.create_task(trabalhador(i, fila, motor, cliente))
                         for i in range(max(1, TRABALHADORES))]
        try:
            while True:
                desejadas = await buscar_salas(cliente)
                if desejadas is not None:
                    por_id = {s["room_id"]: s for s in desejadas}
                    for rid, s in por_id.items():
                        if rid in sessoes:
                            continue
                        sessao = Sessao(room_id=rid, sala=s["sala"], url=s["url"],
                                        token=s["token"], fila=fila)
                        try:
                            await sessao.conectar()
                            sessoes[rid] = sessao
                        except Exception:
                            logger.exception("[%s] não deu para entrar", s["sala"])
                    for rid in list(sessoes):
                        if rid not in por_id:
                            await sessoes.pop(rid).desconectar()
                await asyncio.sleep(INTERVALO)
        finally:
            for s in list(sessoes.values()):
                await s.desconectar()
            for t in trabalhadores:
                t.cancel()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Transcritor das salas da videoconferência")
    p.add_argument("--uma-rodada", action="store_true",
                   help="pergunta as salas, imprime e sai (não entra em nenhuma)")
    args = p.parse_args()
    try:
        sys.exit(asyncio.run(principal(uma_rodada=args.uma_rodada)))
    except KeyboardInterrupt:
        sys.exit(0)
