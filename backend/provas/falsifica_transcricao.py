# -*- coding: utf-8 -*-
"""A prova da transcrição mede alguma coisa?

    python -B provas/falsifica_transcricao.py

Verde só vale se ficar vermelho quando o defeito volta. Cada estrago aqui é a
forma PLAUSÍVEL do erro — o que alguém escreveria de boa-fé, ou o que o código
era antes desta entrega. Nenhum deles daria erro: todos dariam sala plausível e
errada.

Os arquivos são alterados no disco e restaurados no `finally`, inclusive se a
prova estourar. Nada fica modificado.
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
PROVA = RAIZ / "provas/prova_transcricao.py"

ROUTER = RAIZ / "app/routers/openpbl_class.py"
INTERNO = RAIZ / "app/routers/internal.py"
CADENCIA = RAIZ / "app/services/cadencia.py"
LIVEKIT = RAIZ / "app/services/livekit_service.py"
AGENTE = RAIZ.parent / "agent/transcritor.py"
FRONT = RAIZ.parent / "frontend/src/components/video/VideoRoom.tsx"

#: (rótulo, arquivo, trecho original, trecho estragado)
ESTRAGOS = [
    # ── Presença: o estado de antes desta entrega ───────────────────────────
    ("a presenca volta a contar o gravador como aluno",
     ROUTER,
     "    vivos = presenca.so_pessoas(\n        await list_participant_identities(await _nome_no_livekit(room_id)))",
     "    vivos = await list_participant_identities(await _nome_no_livekit(room_id))"),

    # ── O limiar ────────────────────────────────────────────────────────────
    ("o limiar volta a ser ignorado dentro da regra",
     CADENCIA,
     "    return total > 0 and sim > total * limiar",
     "    return total > 0 and sim * 2 > total"),

    ("o limiar padrao muda junto com o deploy",
     CADENCIA,
     "LIMIAR_DE_AVANCO = 0.5",
     "LIMIAR_DE_AVANCO = 0.66"),

    # A trava da sala vazia e a comparacao ESTRITA, nao o `total > 0` (que e
    # redundante enquanto `apurar` so conta presentes). O estrago plausivel,
    # portanto, e o `>=` -- e com ele 0 de 0 passa.
    ("sala vazia passa a avancar (`>=` no lugar de `>`)",
     CADENCIA,
     "    return total > 0 and sim > total * limiar",
     "    return sim >= total * limiar"),

    # ── A rota de leitura ───────────────────────────────────────────────────
    ("a transcricao vira publica (o aluno le o erro do ASR)",
     ROUTER,
     '    await _require_host(user)\n    if not await tem_tabela("video_room_transcricao"):',
     '    if not await tem_tabela("video_room_transcricao"):'),

    ("a leitura deixa de se proteger da migration que falta",
     ROUTER,
     '    if not await tem_tabela("video_room_transcricao"):\n        return {"transcricao": []}',
     "    pass"),

    ("a transcricao passa a sair ordenada pela chegada",
     ROUTER,
     "FROM video_room_transcricao WHERE room_id=$1 ORDER BY inicio",
     "FROM video_room_transcricao WHERE room_id=$1 ORDER BY id"),

    # ── As rotas do agente ──────────────────────────────────────────────────
    ("servidor sem segredo passa a aceitar qualquer um",
     INTERNO,
     "    if not settings.node_secret or segredo != settings.node_secret:",
     "    if segredo != settings.node_secret:"),

    ("gravar fala deixa de exigir o segredo",
     INTERNO,
     '    _autorizar(x_node_secret)\n    texto = (body.texto or "").strip()',
     '    texto = (body.texto or "").strip()'),

    ("gravar deixa de ser idempotente (a fala duplica em rede ruim)",
     INTERNO,
     '            "ON CONFLICT (room_id, identity, inicio) DO NOTHING RETURNING id",',
     '            "RETURNING id",'),

    ("texto vazio passa a virar linha na transcricao",
     INTERNO,
     "    if not texto:\n        return {\"ok\": True, \"gravado\": False, \"porque\": \"texto vazio\"}",
     "    pass"),

    ("a fala do gravador passa a ser aceita",
     INTERNO,
     "    if not presenca.e_pessoa(body.identity):",
     "    if False:"),

    ("a etapa passa a vir do agente (2a copia do estado da aula)",
     INTERNO,
     '    stage = await pool().fetchval(\n        "SELECT stage FROM video_room_openpbl_class WHERE room_id=$1", body.room_id)',
     "    stage = getattr(body, \"stage\", \"\")"),

    ("salas vazias passam a entrar na lista do agente",
     INTERNO,
     "        if contagem.get(sala, 0) <= 0:\n            continue",
     "        pass"),

    # ── O token ─────────────────────────────────────────────────────────────
    ("o transcritor volta a aparecer na grade (tile fantasma)",
     LIVEKIT,
     "        can_publish_data=False,\n        hidden=True,",
     "        can_publish_data=False,"),

    ("o transcritor passa a poder publicar",
     LIVEKIT,
     "        can_publish=False,\n        can_subscribe=True,",
     "        can_publish=True,\n        can_subscribe=True,"),

    # ── O agente ────────────────────────────────────────────────────────────
    # O mais sutil dos estragos do agente: atribuir a fala pelo NOME. Funciona
    # na demonstracao e quebra na turma onde ha dois "Ana", ou onde alguem
    # entrou sem nome -- e quebra ATRIBUINDO a fala a outra pessoa.
    ("a fala passa a ser atribuida pelo nome, nao pela identidade",
     AGENTE,
     "                        identity=participante.identity,\n                        nome=participante.name or participante.identity,",
     "                        identity=participante.name,\n                        nome=participante.name or participante.identity,"),

    ("o reconhecimento volta para o laco de eventos",
     AGENTE,
     "            texto = await asyncio.to_thread(motor.transcrever, fala.pcm, TAXA)",
     "            texto = motor.transcrever(fala.pcm, TAXA)"),

    ("a frase-fantasma do Whisper passa a ser gravada",
     AGENTE,
     "            if not vale_gravar(texto):",
     "            if False:"),

    ("o descarte por fila cheia volta a ser silencioso",
     AGENTE,
     '            logger.error("[%s] FILA CHEIA: %d fala(s) descartada(s) nesta sala. "',
     '            logger.debug("[%s] fila cheia: %d fala(s) descartada(s). "'),

    # O defeito de uma linha que abandona um encontro em andamento porque o
    # backend piscou: `None` (nao sei) tratado como `[]` (nenhuma sala).
    ("falha de rede passa a esvaziar as sessoes",
     AGENTE,
     "                if desejadas is not None:",
     "                if desejadas:"),

    ("o agente e o backend divergem sobre o prefixo do gravador",
     AGENTE,
     'PREFIXO_DO_GRAVADOR = "EG_"',
     'PREFIXO_DO_GRAVADOR = "EGRESS_"'),

    ("401 do backend passa a parecer 'nenhuma sala'",
     AGENTE,
     '    if r.status_code == 401:',
     '    if False:'),

    # ── A tela ──────────────────────────────────────────────────────────────
    ("a tela passa a buscar a transcricao tambem para o aluno",
     FRONT,
     "    if (!scorm || !amStaff) return;\n    const juntar",
     "    if (!scorm) return;\n    const juntar"),

    ("a tela perde o dedupe (a fala aparece duas vezes)",
     FRONT,
     "      const porChave = new Map(atuais.map((f) => [`${f.identity}|${f.inicio}`, f]));",
     "      const porChave = new Map(atuais.map((f, i) => [String(i), f]));"),

    ("a linha da transcricao perde o nome de quem falou",
     FRONT,
     '                <b className="vr-transcricao__quem">{f.nome || f.identity}</b>{" "}',
     '                {" "}'),

    ("o painel passa a aparecer para a turma inteira",
     FRONT,
     "        {pblActive && amStaff && (\n          <PainelDaTranscricao",
     "        {pblActive && (\n          <PainelDaTranscricao"),
]


def prova_passa() -> bool:
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(PROVA)], cwd=str(RAIZ),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.returncode == 0


print("sanidade: a prova passa com a arvore intacta?")
if not prova_passa():
    raise SystemExit("[ERRO] a prova ja falha ANTES de qualquer estrago; "
                     "conserte a arvore antes de falsificar.")
print("   sim\n")

falhas = 0
for rotulo, arquivo, de, para in ESTRAGOS:
    original = io.open(arquivo, encoding="utf-8").read()
    if de not in original:
        print(f"   NAO MEDIDO  {rotulo}")
        print(f"               trecho ausente em {arquivo.name}: {de!r}")
        falhas += 1
        continue
    if original.count(de) > 1:
        # Ancora ambigua: `replace(..., 1)` estragaria a PRIMEIRA ocorrencia,
        # que pode nao ser a que a prova mede -- e a prova ficaria verde com o
        # defeito de volta em outro lugar. Ja aconteceu neste repositorio.
        print(f"   AMBIGUO     {rotulo}")
        print(f"               {original.count(de)} ocorrencias em {arquivo.name}")
        falhas += 1
        continue
    try:
        io.open(arquivo, "w", encoding="utf-8", newline="\n").write(
            original.replace(de, para, 1))
        pegou = not prova_passa()
    finally:
        io.open(arquivo, "w", encoding="utf-8", newline="\n").write(original)
    print(f"   {'ok   ' if pegou else 'PASSOU'}      {rotulo}")
    if not pegou:
        print("               a prova ficou VERDE com o defeito de volta")
    falhas += not pegou

print(f"\nestragos nao detectados: {falhas}")
raise SystemExit(1 if falhas else 0)
