# -*- coding: utf-8 -*-
"""Onde uma fala começa e onde ela termina. Puro.

Esta é a única parte do transcritor que decide algo, e por isso é a única que
dá para provar sem áudio, sem GPU e sem rede: recebe uma sequência de
`(energia, duração)` e devolve onde cortar.

## Por que não mandar o áudio corrido para o reconhecedor

Porque a identificação se perderia. O valor do item "Identificação +
transcrição" é saber **quem** falou, e isso só é exato enquanto cada pedaço de
áudio continua ligado ao participante dono da faixa no LiveKit. Juntar o áudio
de todos num arquivo transforma o problema em diarização por voz -- adivinhar
quem fala pelo timbre --, que erra justamente quando duas pessoas se atropelam,
que é o normal numa plenária.

Então o áudio de cada participante é tratado em separado, e o que falta é saber
quando uma frase acabou. É isto.

## As quatro regras, e o que cada uma evita

1. **Silêncio não abre fala.** Sem isso o reconhecedor seria chamado sobre uma
   sala calada, e o Whisper ALUCINA em silêncio -- devolve "Obrigado pela
   atenção", "Legendas pela comunidade...". Uma transcrição inventada é pior que
   nenhuma, porque ninguém que a leia depois sabe que ela é falsa.
2. **Pausa curta não corta.** Quem respira no meio da frase não vira duas
   linhas. É a diferença entre ler "eu acho que" / "a gente deveria começar" e
   ler a frase que a pessoa disse.
3. **Pausa longa corta.** É o fim da frase, e é o que faz o texto aparecer na
   tela enquanto a aula acontece.
4. **Teto de duração.** Quem fala três minutos sem pausar -- um aluno
   apresentando -- ainda aparece na transcrição, em pedaços. Sem o teto a tela
   fica vazia justamente durante a apresentação, e o reconhecedor recebe um
   bloco grande demais de uma vez.

E uma quinta, que é de economia e de qualidade ao mesmo tempo: **fala curta
demais não vale transcrever.** Tosse, "uhum", o estalo do microfone abrindo. O
reconhecedor custa (GPU ou centavos por minuto) e o resultado tende a ser
invenção.

## O silêncio do fim não entra no áudio

O corte devolve `ms_uteis`: do começo do trecho até a última vez que houve voz.
O rabo de silêncio que FECHOU a fala é justamente o pedaço em que o
reconhecedor alucina. Guardá-lo custaria qualidade sem acrescentar palavra
nenhuma.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Energia (RMS, em escala 0..1) acima da qual se considera que há voz.
#:
#: É um limiar de PRODUTO, não técnico: com o valor baixo, ruído de ventilador
#: abre fala e o reconhecedor alucina sobre ele; alto, o aluno que fala baixo
#: desaparece da transcrição -- e desaparecer em silêncio é o pior dos dois,
#: porque a transcrição parece completa.
#:
#: 0,012 em áudio de microfone de notebook fica acima do ruído de fundo típico
#: e abaixo de fala normal. Quem for ajustar, ajuste aqui e meça com uma sala de
#: verdade; o agente também aceita `TRANSCRITOR_LIMIAR_DE_VOZ` para isso.
LIMIAR_DE_VOZ = 0.012

#: Silêncio contínuo que fecha a fala. 800 ms é uma pausa de fim de frase; 300
#: cortaria no meio de quem pensa enquanto fala.
SILENCIO_QUE_FECHA_MS = 800

#: Teto de uma fala. Acima disto corta mesmo sem pausa (ver regra 4).
FALA_MAXIMA_MS = 15_000

#: Voz mínima para valer uma chamada ao reconhecedor.
FALA_MINIMA_MS = 400


@dataclass(frozen=True)
class Corte:
    """Uma fala fechada, pronta para transcrever (ou para descartar).

    `ms_no_buffer` é tudo o que foi acumulado; `ms_uteis` é até a última voz --
    é o que se manda ao reconhecedor. `vale` é falso quando houve voz de menos.
    """

    ms_no_buffer: int
    ms_uteis: int
    ms_de_voz: int
    motivo: str
    vale: bool


@dataclass
class Fatiador:
    """Acompanha UM participante e diz quando a fala dele fechou.

    Um por faixa de áudio: o estado (está falando? há quanto tempo?) é por
    pessoa, e misturar dois participantes num fatiador só é o mesmo erro de
    juntar o áudio de todos num arquivo.
    """

    limiar_de_voz: float = LIMIAR_DE_VOZ
    silencio_que_fecha_ms: int = SILENCIO_QUE_FECHA_MS
    fala_maxima_ms: int = FALA_MAXIMA_MS
    fala_minima_ms: int = FALA_MINIMA_MS

    # ── estado ──────────────────────────────────────────────────────────────
    #: Há uma fala aberta (já houve voz e ela ainda não fechou)?
    aberta: bool = False
    #: Tudo o que entrou desde que a fala abriu.
    ms_no_buffer: int = 0
    #: Até a última vez que houve voz.
    ms_ate_ultima_voz: int = 0
    #: Soma dos pedaços com voz (não conta as pausas internas).
    ms_de_voz: int = 0
    #: Silêncio CONTÍNUO desde a última voz.
    ms_de_silencio: int = 0

    def alimentar(self, energia: float, ms: int) -> Corte | None:
        """Consome um pedaço de áudio. Devolve o corte, se a fala fechou.

        `energia` é o RMS do pedaço (0..1) e `ms` a duração dele. O chamador
        guarda as amostras; aqui só se contam milissegundos -- é o que permite
        provar esta regra sem áudio.
        """
        tem_voz = energia >= self.limiar_de_voz

        if not self.aberta:
            # REGRA 1: silêncio não abre fala. Nem acumula -- o pedaço calado
            # anterior à primeira palavra não interessa a ninguém.
            if not tem_voz:
                return None
            self.aberta = True
            self.ms_no_buffer = 0
            self.ms_ate_ultima_voz = 0
            self.ms_de_voz = 0
            self.ms_de_silencio = 0

        self.ms_no_buffer += ms
        if tem_voz:
            self.ms_de_voz += ms
            self.ms_ate_ultima_voz = self.ms_no_buffer
            self.ms_de_silencio = 0
        else:
            # REGRA 2: a pausa curta fica DENTRO do trecho; ela só não entra na
            # conta de voz.
            self.ms_de_silencio += ms

        # REGRA 3: pausa longa fecha.
        if self.ms_de_silencio >= self.silencio_que_fecha_ms:
            return self._fechar("pausa")
        # REGRA 4: teto de duração.
        if self.ms_no_buffer >= self.fala_maxima_ms:
            return self._fechar("teto")
        return None

    def fechar_agora(self) -> Corte | None:
        """Fecha o que estiver aberto. Para quando o participante SAI da sala.

        Sem isto, a última frase de quem desconecta morreria no buffer -- e é
        comum ser justamente a despedida, ou a resposta que ninguém mais ouviu.
        """
        if not self.aberta:
            return None
        return self._fechar("saiu")

    def _fechar(self, motivo: str) -> Corte:
        corte = Corte(
            ms_no_buffer=self.ms_no_buffer,
            ms_uteis=self.ms_ate_ultima_voz,
            ms_de_voz=self.ms_de_voz,
            motivo=motivo,
            # REGRA 5: voz de menos não vale uma chamada ao reconhecedor.
            vale=self.ms_de_voz >= self.fala_minima_ms,
        )
        self.aberta = False
        self.ms_no_buffer = 0
        self.ms_ate_ultima_voz = 0
        self.ms_de_voz = 0
        self.ms_de_silencio = 0
        return corte


#: Frases que o Whisper devolve quando lhe dão silêncio ou ruído. Não são
#: transcrição: são o que o modelo aprendeu a escrever no fim de vídeos do
#: YouTube. Gravá-las poria na boca de um aluno algo que ele não disse.
#:
#: A comparação é por texto INTEIRO normalizado, nunca por "contém": uma pessoa
#: pode realmente dizer "obrigado" numa aula.
RUIDO_CONHECIDO: frozenset[str] = frozenset({
    "obrigado", "obrigada", "obrigado.", "muito obrigado",
    "obrigado pela atencao", "obrigado por assistir",
    "legendas pela comunidade amara.org", "amara.org",
    "legendado por: ", "transcricao automatica",
    "subscribe", "tchau", "ok", "ah", "uh", "hum", "ahn",
})


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem espaço sobrando — para comparar com a lista."""
    import unicodedata

    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto.strip().lower())
        if unicodedata.category(c) != "Mn")
    return " ".join(sem_acento.split())


def vale_gravar(texto: str) -> bool:
    """O texto que o reconhecedor devolveu é fala de verdade?

    Recusa o vazio e as frases-fantasma da lista acima. Não tenta ser esperto
    além disso: filtrar por "parece estranho" apagaria fala real de quem tem
    sotaque ou microfone ruim, e a transcrição ficaria com buracos invisíveis.
    """
    limpo = normalizar(texto)
    if not limpo:
        return False
    return limpo not in RUIDO_CONHECIDO
