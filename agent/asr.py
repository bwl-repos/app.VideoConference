# -*- coding: utf-8 -*-
"""Os motores de reconhecimento de fala, atrás de uma interface só.

Dois existem hoje, e a escolha é de CUSTO e de dados, não de arquitetura:

| motor | onde roda | custo | quando faz sentido |
|---|---|---|---|
| `whisper` | aqui, com `faster-whisper` | a máquina (GPU) | volume alto, áudio não sai da infra |
| `deepgram` | API da Deepgram | por minuto | sem GPU para manter, volume baixo |

A interface é a mesma, de propósito: trocar de motor é uma variável de
ambiente, não um reescrita. Esta decisão não deveria ter sido tomada dentro do
código do agente — ela depende de quanto a OpenPBL vai transcrever por mês, que
é informação de negócio.

## Por que não streaming

Os dois motores recebem um trecho FECHADO de fala, não um fluxo contínuo. A
razão está em `segmentacao.py`: o trecho é por participante, e é ele que carrega
a identificação. Um fluxo por participante multiplicaria conexões (uma por
pessoa por sala) para ganhar um ou dois segundos de latência num produto em que
a transcrição é registro, não legenda ao vivo.

Se um dia virar legenda na tela, a interface aguenta: o que muda é o tamanho do
trecho, não quem é o dono dele.

## O que NUNCA aparece no log

A chave da Deepgram. Erros desta classe imprimem status e corpo da resposta --
e o corpo da Deepgram não traz a chave --, nunca o cabeçalho enviado.
"""
from __future__ import annotations

import io
import logging
import os
import wave

logger = logging.getLogger("transcritor.asr")

#: Taxa em que o áudio chega aqui. É a que o `AudioStream` do LiveKit entrega
#: (ele reamostra), e a que o Whisper quer nativamente. Mudar isto sem muder o
#: `AudioStream` degrada a transcrição em silêncio.
TAXA = 16_000


def _wav(pcm16: bytes, taxa: int = TAXA) -> bytes:
    """Embrulha PCM cru num WAV mono de 16 bits.

    Existe para a Deepgram: mandar PCM cru exige acertar `encoding`, `rate` e
    `channels` na URL, e errar um deles não dá erro -- dá transcrição de ruído.
    O contêiner carrega os três.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(pcm16)
    return buf.getvalue()


class MotorWhisper:
    """`faster-whisper` nesta máquina.

    O modelo é carregado uma vez, na primeira fala -- não no `__init__`. Carregar
    1,6 GB antes de saber se alguém vai falar atrasa a entrada do agente na sala
    e, numa máquina sem GPU, trava o processo por minutos durante o boot.
    """

    nome = "whisper"

    def __init__(self, *, modelo: str = "large-v3-turbo", dispositivo: str = "cuda",
                 compute: str = "int8_float16", idioma: str = "pt") -> None:
        self.modelo, self.dispositivo, self.compute, self.idioma = (
            modelo, dispositivo, compute, idioma)
        self._m = None

    def _carregar(self):
        if self._m is None:
            from faster_whisper import WhisperModel

            logger.info("[asr] carregando %s em %s (%s)",
                        self.modelo, self.dispositivo, self.compute)
            self._m = WhisperModel(self.modelo, device=self.dispositivo,
                                   compute_type=self.compute)
        return self._m

    def transcrever(self, pcm16: bytes, taxa: int = TAXA) -> str:
        import numpy as np

        audio = np.frombuffer(pcm16, dtype="<i2").astype("float32") / 32768.0
        segmentos, _ = self._carregar().transcribe(
            audio,
            language=self.idioma,          # sempre explícito: a autodetecção
                                           # confunde pt com es nos primeiros
                                           # segundos, e aí a frase sai em
                                           # espanhol sem nenhum aviso
            beam_size=1,                   # o trecho é curto; beam 5 custa o
                                           # dobro para ganhar pouco
            vad_filter=True,               # segunda tranca contra alucinação em
                                           # silêncio (a primeira é o fatiador)
            condition_on_previous_text=False,
            # ↑ decisivo em transcrição por pedaços: com o condicionamento
            # ligado, o modelo repete a frase anterior quando o trecho novo é
            # curto ou ruim -- a transcrição entra em loop e afirma que o aluno
            # disse três vezes o que ele disse uma.
        )
        return " ".join(s.text.strip() for s in segmentos).strip()


class MotorDeepgram:
    """A API da Deepgram, um trecho por chamada.

    `model` e `language` são variáveis porque a lista de modelos da Deepgram
    muda: o `nova-3` ganhou português em 2025 e melhorou em 2026. Fixar o nome
    no código obrigaria a um deploy para trocar de modelo.
    """

    nome = "deepgram"

    def __init__(self, *, chave: str, modelo: str = "nova-3",
                 idioma: str = "pt-BR") -> None:
        if not chave:
            raise ValueError("DEEPGRAM_API_KEY vazia")
        self._chave, self.modelo, self.idioma = chave, modelo, idioma

    def transcrever(self, pcm16: bytes, taxa: int = TAXA) -> str:
        import httpx

        url = ("https://api.deepgram.com/v1/listen"
               f"?model={self.modelo}&language={self.idioma}&smart_format=true")
        r = httpx.post(url, content=_wav(pcm16, taxa), timeout=30.0, headers={
            "Authorization": f"Token {self._chave}",
            "Content-Type": "audio/wav",
        })
        if r.status_code != 200:
            # Status e corpo da resposta; nunca o cabeçalho (que leva a chave).
            logger.error("[asr] deepgram %s: %s", r.status_code, r.text[:300])
            return ""
        d = r.json()
        try:
            return (d["results"]["channels"][0]["alternatives"][0]["transcript"] or "").strip()
        except (KeyError, IndexError):
            logger.error("[asr] deepgram devolveu forma inesperada: %s", str(d)[:300])
            return ""


def motor_do_ambiente():
    """O motor que as variáveis de ambiente pedem.

    `ASR_ENGINE=whisper` (padrão) ou `deepgram`. Um nome desconhecido ERRA aqui,
    no boot, em vez de cair no padrão: um erro de digitação que escolhe
    silenciosamente outro motor trocaria o custo do mês sem ninguém notar.
    """
    qual = (os.getenv("ASR_ENGINE") or "whisper").strip().lower()
    if qual == "whisper":
        return MotorWhisper(
            modelo=os.getenv("ASR_MODELO", "large-v3-turbo"),
            dispositivo=os.getenv("ASR_DISPOSITIVO", "cuda"),
            compute=os.getenv("ASR_COMPUTE", "int8_float16"),
            idioma=os.getenv("ASR_IDIOMA", "pt"),
        )
    if qual == "deepgram":
        return MotorDeepgram(
            chave=os.getenv("DEEPGRAM_API_KEY", ""),
            modelo=os.getenv("ASR_MODELO", "nova-3"),
            idioma=os.getenv("ASR_IDIOMA", "pt-BR"),
        )
    raise SystemExit(f"ASR_ENGINE desconhecido: {qual!r} (use whisper ou deepgram)")
