"""Aula OpenPBL ao vivo — a webconf substitui o pacote PRESENTATION do facilitador.

Replica exatamente a sequência que o pacote faz contra a integration.openpbl.ai
(ContentBuilder C#):
  1. POST /api/Presentation {ActivityId, email}            → presentationCode
  2. POST /api/ClassCourse {name,email,courseId:"",code}   → ClassCourseId + 6 grupos
  Liberar Riscos:      POST /api/ClassRoom/release/{email}/{ccid}/performance
  Liberar Percepções:  POST /api/ClassRoom/release/{email}/{ccid}
  Encerrar registro:   POST /api/Presentation/CloseChecking {Code, ActivityCourseId}
Os pacotes dos alunos já fazem polling desses estados (5s) — nada muda para eles.

O chat do facilitador é um proxy do chat.openpbl.ai (painel do professor, HTTP
Basic). O aluno continua mandando pelo chat do pacote; o facilitador responde
daqui de dentro da sala.
"""
import asyncio
import json
import math
import time
import httpx
from datetime import timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..auth import get_current_user, optional_user, CurrentUser
from ..config import settings
from ..db import pool
from ..realtime.hub import hub
from .breakouts import _broadcast_state as _broadcast_breakout_state

router = APIRouter(prefix="/api/rooms", tags=["openpbl-class"])


# ── schemas ───────────────────────────────────────────────────────────────
class ClassStart(BaseModel):
    activity_id: str
    facilitator_email: str | None = None   # default: user.id quando for e-mail


class ClassRelease(BaseModel):
    gate: str   # "risks" (dimensões, /performance) | "perceptions"


class ChatReply(BaseModel):
    content: str


class AvaliacaoDesempenho(BaseModel):
    """A nota que o facilitador dá a um aluno na plenária, pela própria sala.

    Ele clica com o botão direito na câmera e escolhe ali, sem trocar de tela:
    sair da videoconferência no meio da plenária para preencher um formulário
    em outra aba é a diferença entre a avaliação acontecer e não acontecer.
    """

    #: A identidade LiveKit do participante — é o que o clique tem em mãos. O
    #: e-mail é resolvido aqui, contra `video_room_participants`: aceitar o
    #: e-mail direto do navegador deixaria o facilitador (ou qualquer um com o
    #: token dele) escrever nota sobre quem não está na sala.
    identity: str
    #: 4 = DESTACADA · 3 = pró-ativa · 2 = reativa · 1 = resistente.
    nota: int
    #: Em qual critério ele se destacou (índice da dimensão). Só com nota 4.
    #: Um 4 vale 4 apenas nesse critério; nos outros vale 3 — é a regra do
    #: `N12` da planilha, aplicada no elearn, na leitura.
    destaque: int | None = None


# ── helpers ───────────────────────────────────────────────────────────────
def _integration_headers() -> dict:
    if not settings.openpbl_integration_apikey:
        raise HTTPException(503, "Integração OpenPBL não configurada (apikey ausente)")
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "apikey": settings.openpbl_integration_apikey,
    }


def _chat_auth() -> tuple[str, str]:
    if not settings.openpbl_chat_user:
        raise HTTPException(503, "Chat OpenPBL não configurado (credenciais ausentes)")
    return (settings.openpbl_chat_user, settings.openpbl_chat_pass)


async def _require_host(user: CurrentUser):
    if not user.is_staff:
        raise HTTPException(403)


def _row_to_state(row) -> dict:
    groups = row["group_codes"]
    if isinstance(groups, str):
        groups = json.loads(groups)
    return {
        "active": True,
        "activity_id": row["activity_id"],
        "presentation_code": row["presentation_code"],
        "class_course_id": row["class_course_id"],
        "group_codes": groups,
        "facilitator_email": row["facilitator_email"],
        "facilitator_name": row["facilitator_name"],
        "checking_open": row["checking_open"],
        "released_dimensions": row["released_dimensions"],
        "released": row["released"],
        "code_hidden": row["code_hidden"],
        "stage": row["stage"] if "stage" in row else "session_start",
    }


def _room_scoped_email(email: str, room_id: str) -> str:
    """Email exclusivo da sala, usado como IDENTIFICADOR da apresentação no OpenPBL
    (nada é enviado a ele). Plus-addressing: `nome+r<8hex>@dominio`. Determinístico
    por sala — a mesma sala sempre gera a mesma chave (código estável durante a
    sessão), salas diferentes geram chaves diferentes (código novo por aula).

    Se o email já tiver um '+', o local é truncado antes dele para não empilhar tags a
    cada chamada. Sem '@' (não deveria ocorrer aqui), devolve o email intacto."""
    short = room_id.replace("-", "")[:8]
    local, sep, domain = email.partition("@")
    if not sep:
        return email
    local = local.split("+", 1)[0]
    return f"{local}+r{short}@{domain}"


def _facilitator_base_email(scoped: str) -> str:
    """Recupera o email SEM o sufixo por-sala (`+r<id>`).

    O email derivado tem um '+' e o endpoint de release do ContentBuilder o coloca na
    URL — onde o '+' quebra o roteamento (404), mesmo URL-encodado. A criação não sofre
    disso (email vai no corpo JSON). O release é chaveado pelo ccid; o email na path é só
    roteamento, então usamos a base sem '+'. Salas antigas (sem '+') passam intactas."""
    local, sep, domain = (scoped or "").partition("@")
    if not sep:
        return scoped
    return f"{local.split('+', 1)[0]}@{domain}"


async def _get_class(room_id: str):
    return await pool().fetchrow(
        "SELECT * FROM video_room_openpbl_class WHERE room_id=$1", room_id)


# ── endpoints ─────────────────────────────────────────────────────────────
@router.post("/{room_id}/openpbl/start")
async def start_class(room_id: str, body: ClassStart, user: CurrentUser = Depends(get_current_user)):
    """Gera o class-code e cria a turma — igual ao pacote PRESENTATION ao abrir."""
    await _require_host(user)
    room = await pool().fetchrow("SELECT id FROM video_rooms WHERE id=$1", room_id)
    if not room:
        raise HTTPException(404, "room not found")

    real_email = (body.facilitator_email or "").strip() or (user.id if "@" in user.id else "")
    if not real_email:
        raise HTTPException(400, "facilitator_email é obrigatório (identidade sem e-mail)")
    activity_id = body.activity_id.strip()
    if not activity_id:
        raise HTTPException(400, "activity_id é obrigatório")

    # Class-code POR SALA. O /api/Presentation do OpenPBL reusa o código quando a chave
    # (activityId, email) se repete dentro de uma janela de horas — então dar duas aulas
    # do MESMO episódio caía no mesmo código, misturando as turmas. Derivamos um email
    # exclusivo da sala (o OpenPBL usa o email só como identificador, não envia nada):
    # sala nova → chave nova → código novo na hora; reabrir a MESMA sala mantém o código
    # (o id da sala é estável), preservando a sessão em andamento.
    email = _room_scoped_email(real_email, room_id)

    base = settings.openpbl_integration_url.rstrip("/")
    headers = _integration_headers()
    async with httpx.AsyncClient(timeout=20) as c:
        # 1. presentationCode
        r1 = await c.post(f"{base}/api/Presentation",
                          headers=headers,
                          json={"ActivityId": activity_id, "email": email})
        if r1.status_code != 200:
            raise HTTPException(502, f"OpenPBL /api/Presentation falhou ({r1.status_code})")
        code = r1.json() if r1.headers.get("content-type", "").startswith("application/json") else r1.text.strip('"')
        if not code or not isinstance(code, str):
            raise HTTPException(502, "OpenPBL não retornou o código da sessão")

        # 2. ClassCourse (turma + 6 grupos)
        r2 = await c.post(f"{base}/api/ClassCourse",
                          headers=headers,
                          json={"name": user.name or "Facilitador", "email": email,
                                "courseId": "", "presentationCode": code})
        if r2.status_code != 200:
            raise HTTPException(502, f"OpenPBL /api/ClassCourse falhou ({r2.status_code})")
        cc = r2.json() or {}
        ccid = cc.get("id")
        group_codes = [g.get("codigo") for g in (cc.get("classeRooms") or []) if g.get("codigo")]
        if not ccid:
            raise HTTPException(502, "OpenPBL não retornou o ClassCourseId")

    await pool().execute(
        """
        INSERT INTO video_room_openpbl_class
          (room_id, activity_id, presentation_code, class_course_id, group_codes,
           facilitator_email, facilitator_name, checking_open, released_dimensions, released)
        VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,true,false,false)
        ON CONFLICT (room_id) DO UPDATE SET
          activity_id=EXCLUDED.activity_id, presentation_code=EXCLUDED.presentation_code,
          class_course_id=EXCLUDED.class_course_id, group_codes=EXCLUDED.group_codes,
          facilitator_email=EXCLUDED.facilitator_email, facilitator_name=EXCLUDED.facilitator_name,
          checking_open=true, released_dimensions=false, released=false, created_at=now()
        """,
        # Guarda o email DERIVADO: é ele que identifica esta apresentação no OpenPBL, e
        # as liberações (release_gate) precisam usar o mesmo. O nome segue o real.
        room_id, activity_id, code, str(ccid), json.dumps(group_codes),
        email, user.name or "")

    row = await _get_class(room_id)
    state = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", state)
    return state


@router.get("/{room_id}/openpbl")
async def get_class(room_id: str, user: CurrentUser | None = Depends(optional_user)):
    # optional_user (não host): é estado só de leitura — mesma política de roster/roles/
    # risk-chart. Necessário para o gravador (egress) espelhar a etapa atual sem host.
    row = await _get_class(room_id)
    if not row:
        return {"active": False}
    return _row_to_state(row)


@router.post("/{room_id}/openpbl/release")
async def release_gate(room_id: str, body: ClassRelease, user: CurrentUser = Depends(get_current_user)):
    """Libera um questionário para a turma (Riscos → /performance; Percepções → base)."""
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    if body.gate not in ("risks", "perceptions"):
        raise HTTPException(400, "gate deve ser 'risks' ou 'perceptions'")

    base = settings.openpbl_integration_url.rstrip("/")
    # Email SEM o sufixo por-sala: o '+' do email derivado quebra a URL do release (404).
    # O que identifica a turma é o ccid; o email na path é só roteamento.
    email, ccid = _facilitator_base_email(row["facilitator_email"]), row["class_course_id"]
    suffix = "/performance" if body.gate == "risks" else ""
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{base}/api/ClassRoom/release/{email}/{ccid}{suffix}",
                         headers={"Accept": "*/*", "apikey": settings.openpbl_integration_apikey})
        if r.status_code != 200:
            raise HTTPException(502, f"OpenPBL release falhou ({r.status_code})")

        # Push em tempo real (SSE) para os alunos conectados ao pacote: destrava na
        # hora, sem depender do polling. Mesmo canal do facilitador (classCourseId).
        # gate: "risks"->"riscos", "perceptions"->"percepcoes" (nomes que o pagetreat
        # espera). Best-effort — se o Scorm/Redis falhar, o fallback do pacote cobre.
        try:
            rt_gate = "riscos" if body.gate == "risks" else "percepcoes"
            await c.post(
                f"{settings.scorm_lrs_url.rstrip('/')}/realtime/class/{ccid}/release",
                json={"gate": rt_gate, "released": True},
                headers={"X-Release-Token": settings.scorm_realtime_release_token},
            )
        except Exception:
            pass

    field = "released_dimensions" if body.gate == "risks" else "released"
    await pool().execute(
        f"UPDATE video_room_openpbl_class SET {field}=true WHERE room_id=$1", room_id)
    row = await _get_class(room_id)
    state = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", state)
    return state


#: Os critérios mudam com o template do Encontro, não durante uma plenária.
#: Buscá-los a cada abertura do menu de contexto seria uma chamada ao elearn
#: por clique direito do facilitador.
_criterios_cache: tuple[float, list] | None = None
_CRITERIOS_TTL = 300.0


@router.get("/{room_id}/openpbl/criterios")
async def listar_criterios(room_id: str, user: CurrentUser = Depends(get_current_user)):
    """Os nomes dos critérios de desempenho, para o menu de avaliação.

    Proxy do elearn, e não chamada direta do navegador: o token do elearn não
    pode chegar ao browser — mesmo motivo de `/api/salas/*` existir no
    CustomerApp.

    A ORDEM é o contrato: o índice de um critério aqui é o `destaque` que volta
    em `/avaliar`. Reordenar a lista no caminho trocaria os eixos sem erro
    nenhum.
    """
    await _require_host(user)
    global _criterios_cache
    agora = time.monotonic()
    if _criterios_cache and agora - _criterios_cache[0] < _CRITERIOS_TTL:
        return {"criterios": _criterios_cache[1]}
    if not settings.openpbl_rise_token:
        return {"criterios": []}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{settings.openpbl_rise_url.rstrip('/')}/desempenho/criterios",
                headers={"Authorization": f"Bearer {settings.openpbl_rise_token}"})
        lista = (r.json() or {}).get("criterios") or [] if r.status_code == 200 else []
    except Exception:
        # Sem nomes o menu ainda avalia — só não oferece destaque por critério.
        # Derrubar o menu inteiro por causa do rótulo seria perder a nota.
        lista = []
    _criterios_cache = (agora, lista)
    return {"criterios": lista}


@router.post("/{room_id}/openpbl/avaliar")
async def avaliar_desempenho(room_id: str, body: AvaliacaoDesempenho,
                             user: CurrentUser = Depends(get_current_user)):
    """A nota de participação do aluno na plenária, dada durante a sessão.

    ## Para onde ela vai, e por que não é a integração de sempre

    Vai para o ELEARN (Rise), e não para `openpbl_integration_url`. Aquela é a
    API legada (ContentBuilder, PerformanceEvaluation); o pacote de desempenho
    novo e a conta da planilha vivem no Rise. Mandar para o lugar errado não
    daria erro — a nota simplesmente não apareceria para o aluno, que é o pior
    tipo de falha que esta rota pode ter.

    ## O que esta rota NÃO faz

    Não calcula nada. A regra do destaque (um 4 vale 4 só no critério
    apontado), os pesos e a normalização 0–10 ficam todos no Rise, derivados na
    LEITURA. Aqui só se registra o que o facilitador disse.

    Também não deriva o `dimensionsId`: manda o `activity_id` e deixa o Rise
    resolver. Uma segunda cópia daquela regra concordaria hoje e divergiria na
    primeira correção — e o sintoma seria a nota sumir, sem erro nenhum.

    ## Só o host, e só sobre quem está na sala

    `_require_host` porque é nota sobre terceiro. E o e-mail do avaliado é
    resolvido contra `video_room_participants`, não aceito do navegador: do
    contrário bastaria o token do facilitador para escrever nota sobre
    qualquer e-mail do mundo.
    """
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    if body.nota not in (1, 2, 3, 4):
        raise HTTPException(400, "nota deve ser 1, 2, 3 ou 4")
    if not settings.openpbl_rise_token:
        raise HTTPException(503, "Integração com o elearn não configurada (token ausente)")

    alvo = await pool().fetchrow(
        "SELECT email, display_name FROM video_room_participants "
        "WHERE room_id=$1 AND user_id=$2", room_id, body.identity)
    email = ((alvo["email"] if alvo else "") or "").strip().lower()
    if not email:
        # 404 e não 400: o pedido estava bem formado; quem não existe é o alvo.
        # Acontece de verdade quando o aluno entrou como convidado sem e-mail —
        # e aí a nota não teria onde cair.
        raise HTTPException(404, "participante sem e-mail nesta sala")

    corpo = {
        "activity_id": str(row["activity_id"]),
        "avaliado": email,
        "avaliado_nome": (alvo["display_name"] or "") if alvo else "",
        "avaliador": _facilitator_base_email(row["facilitator_email"] or ""),
        "avaliador_nome": row["facilitator_name"] or "",
        "nota": body.nota,
        # Destaque só faz sentido com 4. Mandar o índice junto de uma nota 2
        # encheria o banco de destaques que a regra ignora, e um dia alguém
        # leria aquilo como se valesse.
        "destaque": body.destaque if body.nota == 4 else None,
        "class_code": str(row["class_course_id"] or ""),
    }
    base = settings.openpbl_rise_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{base}/desempenho/facilitador", json=corpo,
                             headers={"Authorization":
                                      f"Bearer {settings.openpbl_rise_token}"})
    except Exception as erro:  # noqa: BLE001
        raise HTTPException(502, f"não foi possível falar com o elearn: {erro}")
    if r.status_code >= 400:
        raise HTTPException(502, f"elearn recusou a nota ({r.status_code})")

    dados = r.json() if r.content else {}
    if not dados.get("ok"):
        # O elearn devolve 200 com `ok: false` quando o episódio não está
        # publicado — ver a rota lá. Aqui vira erro VISÍVEL: o facilitador
        # precisa saber que clicou e nada foi gravado, senão ele avalia a turma
        # inteira achando que registrou.
        raise HTTPException(409, dados.get("erro") or "o elearn não gravou a nota")

    return {"ok": True, "avaliado": email, "nota": body.nota,
            "destaque": corpo["destaque"],
            "dimensions_id": dados.get("dimensions_id", "")}


@router.post("/{room_id}/openpbl/close-registration")
async def close_registration(room_id: str, user: CurrentUser = Depends(get_current_user)):
    """Encerra o registro/presença — novos alunos não conseguem mais entrar."""
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")

    base = settings.openpbl_integration_url.rstrip("/")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{base}/api/Presentation/CloseChecking",
                         headers=_integration_headers(),
                         json={"Code": row["presentation_code"],
                               "ActivityCourseId": row["activity_id"]})
        if r.status_code != 200:
            raise HTTPException(502, f"OpenPBL CloseChecking falhou ({r.status_code})")

    await pool().execute(
        "UPDATE video_room_openpbl_class SET checking_open=false WHERE room_id=$1", room_id)

    # Ao encerrar o registro, divide automaticamente os alunos presentes em grupos
    # (ninguém sozinho, máx 6 grupos, máx 5 por grupo). Best-effort: não derruba o
    # fechamento se algo falhar.
    try:
        await _auto_group_breakouts(room_id)
    except Exception:
        pass

    row = await _get_class(room_id)
    state = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", state)
    return state


@router.get("/{room_id}/openpbl/groups")
async def list_groups(room_id: str, user: CurrentUser = Depends(get_current_user)):
    """Grupos da turma com os alunos que entraram (listarGrupos, ao vivo)."""
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    base = settings.openpbl_integration_url.rstrip("/")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{base}/api/ClassRoomStudent/listarGrupos/{row['class_course_id']}",
                        headers=_integration_headers())
        if r.status_code != 200:
            raise HTTPException(502, f"OpenPBL listarGrupos falhou ({r.status_code})")
        return r.json()


async def _sync_openpbl_groups(room_id: str, cls) -> int:
    """Reflete os grupos montados pela API OpenPBL (ao encerrar o registro) nos
    breakout rooms da webconf. Cada grupo do `listarGrupos` vira um breakout, e
    cada aluno é atribuído mapeando o e-mail → identity do participante da sala.
    Recria a configuração de grupos do zero. Retorna o nº de grupos criados."""
    ccid = cls["class_course_id"]
    if not ccid:
        return 0
    base = settings.openpbl_integration_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{base}/api/ClassRoomStudent/listarGrupos/{ccid}",
                            headers=_integration_headers())
        if r.status_code != 200:
            return 0
        payload = r.json() or {}
    except Exception:
        return 0

    # `data` costuma vir como string JSON (o pacote facilitador faz eval()).
    raw = payload.get("data") if isinstance(payload, dict) else payload
    try:
        groups = raw if isinstance(raw, list) else (json.loads(raw) if raw else [])
    except Exception:
        return 0
    groups = [g for g in groups if isinstance(g, dict) and (g.get("Alunos") or [])]
    if not groups:
        return 0

    # Mapa e-mail → (identity, nome) dos participantes atuais da sala.
    parts = await pool().fetch(
        "SELECT user_id, display_name, email FROM video_room_participants "
        "WHERE room_id=$1 AND left_at IS NULL", room_id)
    by_email = {(p["email"] or "").strip().lower(): (p["user_id"], p["display_name"] or "")
                for p in parts if p["email"]}

    room = await pool().fetchrow("SELECT * FROM video_rooms WHERE id=$1", room_id)
    if not room:
        return 0
    # Recria do zero (mesma semântica do create_breakouts). Fecha se estava aberto.
    if room["breakout_open"]:
        await hub.broadcast(room_id, "breakout-close", {"room_id": room_id})
    await pool().execute("DELETE FROM video_breakout_groups WHERE parent_room_id=$1", room_id)
    await pool().execute(
        "UPDATE video_rooms SET breakout_open=false, breakout_ends_at=NULL, breakout_mode='manual' WHERE id=$1",
        room_id)

    for i, g in enumerate(groups):
        rn = f"{room['room_id']}__bo{i + 1}"
        gid = await pool().fetchval(
            "INSERT INTO video_breakout_groups (parent_room_id, name, room_name, position) "
            "VALUES ($1,$2,$3,$4) RETURNING id", room_id, f"Grupo {i + 1}", rn, i)
        for aluno in (g.get("Alunos") or []):
            email = (aluno.get("Email") or "").strip().lower()
            hit = by_email.get(email)
            if not hit:
                continue   # aluno do grupo não está (ainda) na sala de vídeo
            await pool().execute(
                "INSERT INTO video_breakout_assignments (parent_room_id, group_id, identity, display_name) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT (parent_room_id, identity) DO UPDATE "
                "SET group_id=EXCLUDED.group_id, display_name=EXCLUDED.display_name",
                room_id, str(gid), hit[0], (aluno.get("Name") or hit[1]))

    await _broadcast_breakout_state(room_id)
    return len(groups)


async def _auto_group_breakouts(room_id: str) -> int:
    """Divide os alunos PRESENTES em grupos de vídeo: ninguém sozinho, no máximo
    6 grupos e no máximo 5 por grupo. Distribuição round-robin (equilibrada).
    Determinístico (ordem de entrada) — recria a configuração. Retorna nº de grupos."""
    parts = await pool().fetch(
        "SELECT p.user_id, p.display_name FROM video_room_participants p "
        "JOIN video_rooms r ON r.id = p.room_id "
        "WHERE p.room_id=$1 AND p.left_at IS NULL AND p.is_staff=false AND p.user_id <> r.owner_id "
        "ORDER BY p.joined_at", room_id)
    n = len(parts)
    if n < 1:
        return 0
    if n == 1:
        g = 1
    else:
        # ~raiz(n) grupos: equilibra o nº de grupos com o tamanho de cada um
        # (4→2×2, 5→3+2, 6→2×3, 12→3×4, …). Para n≥4 isso já garante ninguém
        # sozinho (menor grupo = floor(n/g) ≥ 2).
        g = max(1, math.isqrt(n))
        while (n + g - 1) // g > 5 and g < 6:   # respeita o máximo de 5 por grupo
            g += 1
        g = min(g, 6)                            # e o máximo de 6 grupos

    room = await pool().fetchrow("SELECT * FROM video_rooms WHERE id=$1", room_id)
    if not room:
        return 0
    if room["breakout_open"]:
        await hub.broadcast(room_id, "breakout-close", {"room_id": room_id})
    await pool().execute("DELETE FROM video_breakout_groups WHERE parent_room_id=$1", room_id)
    await pool().execute(
        "UPDATE video_rooms SET breakout_open=false, breakout_ends_at=NULL, breakout_mode='manual' WHERE id=$1",
        room_id)

    gids = []
    for i in range(g):
        rn = f"{room['room_id']}__bo{i + 1}"
        gid = await pool().fetchval(
            "INSERT INTO video_breakout_groups (parent_room_id, name, room_name, position) "
            "VALUES ($1,$2,$3,$4) RETURNING id", room_id, f"Grupo {i + 1}", rn, i)
        gids.append(str(gid))
    for idx, p in enumerate(parts):
        await pool().execute(
            "INSERT INTO video_breakout_assignments (parent_room_id, group_id, identity, display_name) "
            "VALUES ($1,$2,$3,$4) ON CONFLICT (parent_room_id, identity) DO UPDATE "
            "SET group_id=EXCLUDED.group_id, display_name=EXCLUDED.display_name",
            room_id, gids[idx % g], p["user_id"], p["display_name"] or "")

    await _broadcast_breakout_state(room_id)
    return g


@router.post("/{room_id}/openpbl/sync-groups")
async def sync_groups(room_id: str, user: CurrentUser = Depends(get_current_user)):
    """(Re)divide os alunos presentes em grupos (ninguém sozinho, máx 6 grupos,
    máx 5 por grupo). Determinístico — útil se entrou/saiu aluno."""
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    n = await _auto_group_breakouts(room_id)
    return {"ok": True, "groups": n}


def _parse_listar_grupos(raw) -> list:
    """`listarGrupos` devolve `data` como string em notação JS: `{[ {...}, {...} ]}`
    com aspas simples e \\r\\n (INVÁLIDO como JSON). Normaliza e parseia."""
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        return []
    s = raw.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()                # remove o wrapper { } → resta [ ... ]
    s = s.replace("'", '"')
    try:
        data = json.loads(s)
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def _openpbl_student_ids(client: httpx.AsyncClient, base: str, ccid: str) -> dict:
    """email(lower) → (studentId, name), via listarGrupos (traz Id+Email de todos)."""
    out: dict[str, tuple[str, str]] = {}
    try:
        r = await client.get(f"{base}/api/ClassRoomStudent/listarGrupos/{ccid}",
                             headers=_integration_headers())
        if r.status_code != 200:
            return out
        payload = r.json() or {}
    except Exception:
        return out
    for g in _parse_listar_grupos(payload.get("data") if isinstance(payload, dict) else payload):
        for a in (g.get("Alunos") or []):
            email = (a.get("Email") or "").strip().lower()
            sid = a.get("Id")
            if email and sid:
                out[email] = (sid, a.get("Name") or "")
    return out


async def _student_perf(client: httpx.AsyncClient, base: str, sid: str, dims_id: str):
    """Notas individuais do aluno no Questionário de Riscos → {dimensions, grades, baseGrades}."""
    try:
        r = await client.get(f"{base}/api/PerformanceEvaluation/performance/{sid}/{dims_id}")
        if r.status_code != 200:
            return None
        d = (r.json() or {}).get("data")
        return d if isinstance(d, dict) else None
    except Exception:
        return None


_chart_cache: dict[str, tuple[float, dict]] = {}
_CHART_TTL = 4.0


@router.get("/{room_id}/openpbl/risk-chart")
async def risk_chart(room_id: str, user: CurrentUser | None = Depends(optional_user)):
    """Radar do Questionário de Riscos agregado pelos GRUPOS DA WEBCONF (os grupos
    do pacote não batem com os nossos). Busca as respostas individuais
    (`performance/{studentId}/{dims}`) e média por grupo + contagem de quem respondeu.
    Liberado a qualquer participante (o aluno também vê o gráfico na etapa 'Mostrar Gráfico')."""
    cls = await _get_class(room_id)
    if not cls:
        return {"available": False, "reason": "class_not_started"}
    room = await pool().fetchrow("SELECT openpbl_dimensions_id FROM video_rooms WHERE id=$1", room_id)
    dims_id = ((room["openpbl_dimensions_id"] if room else None) or "").strip()
    if not dims_id:
        return {"available": False, "reason": "no_dimensions_id"}

    now = time.monotonic()
    hit = _chart_cache.get(room_id)
    if hit and (now - hit[0]) < _CHART_TTL:
        return hit[1]

    base = settings.openpbl_integration_url.rstrip("/")
    ccid = cls["class_course_id"]

    async with httpx.AsyncClient(timeout=15) as c:
        email_to_sid = await _openpbl_student_ids(c, base, ccid)
        if not email_to_sid:
            return {"available": False, "reason": "no_students"}

        groups = await pool().fetch(
            "SELECT id, name FROM video_breakout_groups WHERE parent_room_id=$1 ORDER BY position", room_id)
        assigns = await pool().fetch(
            "SELECT group_id, identity FROM video_breakout_assignments WHERE parent_room_id=$1", room_id)
        parts = await pool().fetch(
            "SELECT user_id, email FROM video_room_participants WHERE room_id=$1", room_id)
        id_to_email = {p["user_id"]: (p["email"] or "").strip().lower() for p in parts}

        group_emails: dict[str, list] = {}
        for a in assigns:
            em = id_to_email.get(a["identity"])
            if em and em in email_to_sid:
                group_emails.setdefault(str(a["group_id"]), []).append(em)

        all_emails = {em for ems in group_emails.values() for em in ems} or set(email_to_sid.keys())
        sid_list = [(em, email_to_sid[em][0]) for em in all_emails]
        perfs = await asyncio.gather(*[_student_perf(c, base, sid, dims_id) for (_, sid) in sid_list])
    perf_by_email = {em: p for (em, _), p in zip(sid_list, perfs)}

    dims = base_grades = None
    for p in perfs:
        if p and p.get("dimensions"):
            dims = p["dimensions"]; base_grades = p.get("baseGrades"); break
    if not dims:
        return {"available": False, "reason": "empty"}
    D = len(dims)

    def grade(p, i):
        g = (p or {}).get("grades") or []
        return g[i] if i < len(g) and isinstance(g[i], (int, float)) else 0

    def avg_over(emails):
        s = [0.0] * D; c = [0] * D
        for em in emails:
            p = perf_by_email.get(em)
            for i in range(D):
                v = grade(p, i)
                if v > 0:
                    s[i] += v; c[i] += 1
        return [(s[i] / c[i]) if c[i] else 0 for i in range(D)]

    # quem respondeu cada dimensão (grade > 0), no total da turma
    answered = [0] * D
    # CONCLUÍDO = aluno que respondeu TODAS as dimensões (grade > 0 em todas).
    completed = 0
    for em in all_emails:
        p = perf_by_email.get(em)
        for i in range(D):
            if grade(p, i) > 0:
                answered[i] += 1
        if D and all(grade(p, i) > 0 for i in range(D)):
            completed += 1

    out_groups = [
        {"name": g["name"], "grades": avg_over(group_emails.get(str(g["id"]), [])),
         "size": len(group_emails.get(str(g["id"]), []))}
        for g in groups if group_emails.get(str(g["id"]))
    ]

    result = {"available": True, "chart": {
        "dimensions": dims,
        "baseGrades": base_grades or [],
        "classAverage": avg_over(all_emails),
        "groups": out_groups,
        "answered": answered,
        "total": len(all_emails),
        "completed": completed,          # alunos que responderam TODAS as dimensões
    }}
    _chart_cache[room_id] = (now, result)
    return result


_STAGES = (
    "session_start", "registration_open", "amplify_code", "registration_close",
    "synopsis", "groups", "plenary", "question", "situational",
    "release_risks", "show_chart", "closing", "release_feedback", "done",
)


class StageSet(BaseModel):
    stage: str


@router.post("/{room_id}/openpbl/stage")
async def set_stage(room_id: str, body: StageSet, user: CurrentUser = Depends(get_current_user)):
    """Cursor da etapa do facilitador (botão verde ▶). Persiste + sincroniza."""
    await _require_host(user)
    stage = (body.stage or "").strip()
    if stage not in _STAGES:
        raise HTTPException(400, f"stage inválido: {stage}")
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    await pool().execute(
        "UPDATE video_room_openpbl_class SET stage=$2 WHERE room_id=$1", room_id, stage)
    row = await _get_class(room_id)
    state = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", state)
    return state


# ── roster: status dos alunos p/ as bordas dos tiles ──────────────────────
# Verde = dentro do pacote; vermelho = fora; badge = registrou presença na
# sessão (Presentation/Students). Todo cliente da sala faz polling, então o
# resultado é cacheado por sala (1 varredura LRS/attendance a cada ~8s).
_roster_cache: dict[str, tuple[float, dict]] = {}
_ROSTER_TTL = 8.0
# Status "grudento" (sticky) por sala. O verde/vermelho ao redor da webcam deve mudar
# só com um sinal REAL (eventos do pacote → verde; package_exited → vermelho). Sem isto,
# uma falha transitória do LRS ou da API de presença invertia a resposta e a borda
# piscava. Guardamos o último status conhecido de cada aluno e a última lista de
# registrados: quando uma chamada falha nesta rodada, mantemos o que já sabíamos.
_roster_sticky: dict[str, dict[str, bool]] = {}      # room_id -> {email: in_package}
_roster_registered: dict[str, set[str]] = {}         # room_id -> {emails registrados}


@router.get("/{room_id}/openpbl/roster")
async def class_roster(room_id: str, user: CurrentUser | None = Depends(optional_user)):
    now = time.monotonic()
    hit = _roster_cache.get(room_id)
    if hit and (now - hit[0]) < _ROSTER_TTL:
        return hit[1]

    room = await pool().fetchrow(
        "SELECT created_at, owner_id FROM video_rooms WHERE id=$1", room_id)
    if not room:
        raise HTTPException(404, "room not found")
    cls = await _get_class(room_id)
    parts = await pool().fetch(
        "SELECT user_id, display_name, email, is_staff FROM video_room_participants "
        "WHERE room_id=$1 AND left_at IS NULL", room_id)

    since_iso = room["created_at"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    lrs = settings.scorm_lrs_url.rstrip("/")

    # Presença registrada na sessão (lista do Presentation/Students). Se a chamada
    # falhar NESTA rodada, mantemos a última lista conhecida em vez de zerar — assim
    # a badge de registrado e o fallback do status não somem por um hiccup de rede.
    registered_emails: set[str] = set()
    reg_ok = False
    if cls and settings.openpbl_integration_apikey:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    f"{settings.openpbl_integration_url.rstrip('/')}/api/Presentation/Students/{cls['presentation_code']}",
                    headers={"Accept": "application/json", "apikey": settings.openpbl_integration_apikey})
                if r.status_code == 200:
                    reg_ok = True
                    for s in ((r.json() or {}).get("data") or []):
                        if s.get("email"):
                            registered_emails.add(s["email"].strip().lower())
        except Exception:
            pass
    if reg_ok:
        _roster_registered[room_id] = registered_emails
    else:
        registered_emails = _roster_registered.get(room_id, registered_emails)

    async def fetch_events_by_student(emails_list: list[str]) -> dict:
        """Eventos da turma INTEIRA numa única chamada ao LRS.

        Antes isto era 1 request por aluno disparado em paralelo (asyncio.gather). Numa
        aula grande, isso abria N conexões simultâneas no Scorm, esgotava o pool e
        derrubava o serviço (incidente 2026-07-24). Agora: 1 request para a turma toda.
        Em falha devolve {} → cada aluno vira None (sem sinal) e a resolução grudenta
        abaixo mantém o último status — mesmo comportamento de antes.
        """
        if not emails_list:
            return {}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{lrs}/interaction-events/by-students",
                                params={"studentEmails": ",".join(emails_list),
                                        "limitPerStudent": 60})
            return (r.json() or {}).get("data") or {}
        except Exception:
            return {}

    def in_package(evs) -> bool | None:
        """True/False pelo LRS; None = sem eventos na sessão (LRS pode atrasar)."""
        sess = sorted([e for e in (evs or []) if (e.get("createdAt") or "") >= since_iso],
                      key=lambda x: x.get("createdAt") or "", reverse=True)
        if not sess:
            return None
        if sess[0].get("eventType") == "package_exited":
            return False
        return any(e.get("eventType") in ("package_opened", "activity_accessed",
                                          "authenticated", "quiz_answered", "lesson_score",
                                          "package_completed") for e in sess)

    emails = {(p["email"] or "").strip().lower(): None for p in parts
              if p["email"] and not p["is_staff"] and p["user_id"] != room["owner_id"]}
    by_student = await fetch_events_by_student(list(emails.keys()))
    flags = [in_package(by_student.get(e)) for e in emails]
    # Resolução grudenta: `flag` só é True/False quando o LRS deu um sinal DEFINITIVO
    # (eventos do pacote / package_exited). Quando é None (LRS falhou ou ainda sem
    # eventos) NÃO invertemos o status — mantemos o último conhecido; e só no 1º contato
    # (sem histórico) o registro de presença vale como evidência de pacote aberto.
    prev = _roster_sticky.get(room_id, {})

    def _resolve(email: str, flag) -> bool:
        if flag is not None:
            return flag                       # sinal real do LRS → manda
        if email in prev:
            return prev[email]                # sem sinal: mantém o último status (anti-piscar)
        return email in registered_emails     # 1º contato: registrado ⇒ presume no pacote

    in_pkg = {e: _resolve(e, f) for e, f in zip(emails.keys(), flags)}
    _roster_sticky[room_id] = in_pkg          # store limitado aos participantes atuais

    students = []
    for p in parts:
        email = (p["email"] or "").strip().lower()
        is_staff = bool(p["is_staff"]) or p["user_id"] == room["owner_id"]
        students.append({
            "identity": p["user_id"],
            "name": p["display_name"] or p["user_id"],
            "is_staff": is_staff,
            "in_package": (in_pkg.get(email, False) if not is_staff else None),
            "registered": (email in registered_emails) if (email and not is_staff) else False,
        })

    out = {
        "code": cls["presentation_code"] if cls else None,
        "activity_id": cls["activity_id"] if cls else None,
        "facilitator_email": cls["facilitator_email"] if cls else None,
        "facilitator_name": cls["facilitator_name"] if cls else None,
        "checking_open": cls["checking_open"] if cls else None,
        "code_hidden": cls["code_hidden"] if cls else False,
        "students": students,
    }
    _roster_cache[room_id] = (now, out)
    return out


class CodeVisibility(BaseModel):
    hidden: bool


@router.post("/{room_id}/openpbl/code-visibility")
async def set_code_visibility(room_id: str, body: CodeVisibility, user: CurrentUser = Depends(get_current_user)):
    """Facilitador oculta/reexibe o card do class-code para todos."""
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    await pool().execute(
        "UPDATE video_room_openpbl_class SET code_hidden=$2 WHERE room_id=$1", room_id, body.hidden)
    _roster_cache.pop(room_id, None)   # invalida o cache p/ refletir na hora
    row = await _get_class(room_id)
    state = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", state)
    return state


# ── chat do facilitador (proxy do painel do professor) ────────────────────
@router.get("/{room_id}/openpbl/chat/conversations")
async def chat_conversations(room_id: str, user: CurrentUser = Depends(get_current_user)):
    await _require_host(user)
    async with httpx.AsyncClient(timeout=20, auth=_chat_auth()) as c:
        r = await c.get(f"{settings.openpbl_chat_url.rstrip('/')}/api/conversations")
        if r.status_code != 200:
            raise HTTPException(502, f"chat OpenPBL falhou ({r.status_code})")
        return r.json()


@router.get("/{room_id}/openpbl/chat/conversations/{conv_id}/messages")
async def chat_messages(room_id: str, conv_id: str, user: CurrentUser = Depends(get_current_user)):
    await _require_host(user)
    async with httpx.AsyncClient(timeout=20, auth=_chat_auth()) as c:
        r = await c.get(f"{settings.openpbl_chat_url.rstrip('/')}/api/conversations/{conv_id}/messages")
        if r.status_code != 200:
            raise HTTPException(502, f"chat OpenPBL falhou ({r.status_code})")
        return r.json()


@router.post("/{room_id}/openpbl/chat/conversations/{conv_id}/reply")
async def chat_reply(room_id: str, conv_id: str, body: ChatReply, user: CurrentUser = Depends(get_current_user)):
    await _require_host(user)
    text = (body.content or "").strip()
    if not text:
        raise HTTPException(400, "mensagem vazia")
    async with httpx.AsyncClient(timeout=20, auth=_chat_auth()) as c:
        r = await c.post(
            f"{settings.openpbl_chat_url.rstrip('/')}/api/conversations/{conv_id}/reply",
            json={"content": text})
        if r.status_code != 200:
            raise HTTPException(502, f"chat OpenPBL reply falhou ({r.status_code})")
        return r.json()
