"""Breakout rooms ("grupos") — sub-salas LiveKit por sala-pai.

Plano de mídia: cada grupo é uma sala LiveKit própria (`<sala>__boN`); mover um
participante = trocar o token/sala dele no cliente. Plano de controle: o WS hub
da sala-pai transporta os eventos breakout-open/close/message + timer, então o
anfitrião comanda todos os grupos de um único lugar.
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..auth import get_current_user, optional_user, CurrentUser
from ..db import pool, tem_coluna
from ..realtime.hub import hub
from ..services.livekit_service import create_token
from ..config import settings

router = APIRouter(prefix="/api/rooms", tags=["breakouts"])


# ── schemas ───────────────────────────────────────────────────────────────
class BreakoutCreate(BaseModel):
    count: int = 2
    names: list[str] | None = None
    mode: str = "auto"            # auto | manual | self


class BreakoutAssign(BaseModel):
    identity: str
    display_name: str | None = None
    group_id: str | None = None   # None = remove do grupo


class BreakoutOpen(BaseModel):
    duration_seconds: int | None = None


class BreakoutMessage(BaseModel):
    text: str


class BreakoutTokenReq(BaseModel):
    group_id: str
    identity: str
    display_name: str | None = None


# ── helpers ───────────────────────────────────────────────────────────────
async def _room_or_404(room_id: str):
    room = await pool().fetchrow("SELECT * FROM video_rooms WHERE id=$1", room_id)
    if not room:
        raise HTTPException(404, "room not found")
    return room


async def _state(room) -> dict:
    """Estado completo dos grupos (usado pelo GET e nos broadcasts)."""
    # `leader_identity` entra na projeção só quando existe: publicar não aplica
    # migration, e esta função alimenta a tela de grupos inteira — pedir uma
    # coluna ausente aqui apagaria os grupos da tela para entregar um líder.
    tem_lider = await tem_coluna("video_breakout_groups", "leader_identity")
    colunas = "id, name, room_name, position" + (", leader_identity" if tem_lider else "")
    groups = await pool().fetch(
        f"SELECT {colunas} FROM video_breakout_groups "
        "WHERE parent_room_id=$1 ORDER BY position", room["id"])
    assigns = await pool().fetch(
        "SELECT group_id, identity, display_name FROM video_breakout_assignments "
        "WHERE parent_room_id=$1", room["id"])
    by_group: dict[str, list] = {}
    nome_de: dict[str, str] = {}
    for a in assigns:
        by_group.setdefault(str(a["group_id"]), []).append(
            {"identity": a["identity"], "display_name": a["display_name"]})
        nome_de[a["identity"]] = a["display_name"] or ""
    return {
        "open": room["breakout_open"],
        "ends_at": room["breakout_ends_at"].isoformat() if room["breakout_ends_at"] else None,
        "mode": room["breakout_mode"],
        "groups": [
            {
                "id": str(g["id"]),
                "name": g["name"],
                "room_name": g["room_name"],
                "position": g["position"],
                "members": by_group.get(str(g["id"]), []),
                # Identidade E nome: a tela marca o líder na lista pela
                # identidade, e o cartão do grupo mostra o nome sem precisar
                # procurar entre os membros.
                "leader_identity": (g["leader_identity"] if tem_lider else None),
                "leader_name": (nome_de.get(g["leader_identity"] or "", "")
                                if tem_lider else ""),
            }
            for g in groups
        ],
    }


async def _broadcast_state(room_id: str):
    room = await pool().fetchrow("SELECT * FROM video_rooms WHERE id=$1", room_id)
    await hub.broadcast(room_id, "breakout-state", await _state(room))


# ── endpoints ─────────────────────────────────────────────────────────────
@router.post("/{room_id}/breakouts")
async def create_breakouts(room_id: str, body: BreakoutCreate, user: CurrentUser = Depends(get_current_user)):
    if not user.is_staff:
        raise HTTPException(403)
    room = await _room_or_404(room_id)
    count = max(1, min(int(body.count or 1), 50))
    mode = body.mode if body.mode in ("auto", "manual", "self") else "auto"

    # Recria do zero (substitui qualquer configuração anterior). Se havia grupos
    # abertos, puxa todos de volta à sala principal antes de recriar.
    if room["breakout_open"]:
        await hub.broadcast(room_id, "breakout-close", {"room_id": room_id})
    await pool().execute("DELETE FROM video_breakout_groups WHERE parent_room_id=$1", room_id)
    await pool().execute(
        "UPDATE video_rooms SET breakout_open=false, breakout_ends_at=NULL, breakout_mode=$2 WHERE id=$1",
        room_id, mode)

    group_ids = []
    for i in range(count):
        name = (body.names[i] if body.names and i < len(body.names) and body.names[i] else f"Grupo {i + 1}")
        rn = f"{room['room_id']}__bo{i + 1}"
        gid = await pool().fetchval(
            "INSERT INTO video_breakout_groups (parent_room_id, name, room_name, position) "
            "VALUES ($1,$2,$3,$4) RETURNING id", room_id, name, rn, i)
        group_ids.append(str(gid))

    # Atribuição automática: distribui os participantes atuais (exceto staff) em
    # round-robin pelos grupos.
    if mode == "auto":
        parts = await pool().fetch(
            "SELECT user_id, display_name FROM video_room_participants "
            "WHERE room_id=$1 AND left_at IS NULL AND is_staff=false ORDER BY joined_at", room_id)
        for idx, p in enumerate(parts):
            gid = group_ids[idx % len(group_ids)]
            await pool().execute(
                "INSERT INTO video_breakout_assignments (parent_room_id, group_id, identity, display_name) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT (parent_room_id, identity) DO UPDATE "
                "SET group_id=EXCLUDED.group_id, display_name=EXCLUDED.display_name",
                room_id, gid, p["user_id"], p["display_name"] or "")

    await _broadcast_state(room_id)
    room = await _room_or_404(room_id)
    return await _state(room)


@router.get("/{room_id}/breakouts")
async def get_breakouts(room_id: str, user: CurrentUser | None = Depends(optional_user)):
    room = await _room_or_404(room_id)
    return await _state(room)


@router.post("/{room_id}/breakouts/assign")
async def assign_breakout(room_id: str, body: BreakoutAssign, user: CurrentUser = Depends(get_current_user)):
    if not user.is_staff:
        raise HTTPException(403)
    await _room_or_404(room_id)
    if body.group_id:
        grp = await pool().fetchrow(
            "SELECT id FROM video_breakout_groups WHERE id=$1 AND parent_room_id=$2", body.group_id, room_id)
        if not grp:
            raise HTTPException(404, "group not found")
        await pool().execute(
            "INSERT INTO video_breakout_assignments (parent_room_id, group_id, identity, display_name) "
            "VALUES ($1,$2,$3,$4) ON CONFLICT (parent_room_id, identity) DO UPDATE "
            "SET group_id=EXCLUDED.group_id, display_name=EXCLUDED.display_name",
            room_id, body.group_id, body.identity, body.display_name or "")
    else:
        await pool().execute(
            "DELETE FROM video_breakout_assignments WHERE parent_room_id=$1 AND identity=$2",
            room_id, body.identity)
    await _broadcast_state(room_id)
    return {"ok": True}


async def abrir_grupos(room_id: str, duration_seconds: int | None) -> dict:
    """Abre os grupos. Fora do endpoint porque a cadência também abre, sem usuário."""
    room = await _room_or_404(room_id)
    n = await pool().fetchval("SELECT count(*) FROM video_breakout_groups WHERE parent_room_id=$1", room_id)
    if not n:
        raise HTTPException(400, "nenhum grupo configurado")
    ends_at = None
    if duration_seconds and duration_seconds > 0:
        ends_at = datetime.now(timezone.utc) + timedelta(seconds=int(duration_seconds))
    await pool().execute(
        "UPDATE video_rooms SET breakout_open=true, breakout_ends_at=$2 WHERE id=$1", room_id, ends_at)
    room = await _room_or_404(room_id)
    state = await _state(room)
    await hub.broadcast(room_id, "breakout-open", state)
    return state


async def fechar_grupos(room_id: str) -> None:
    await pool().execute(
        "UPDATE video_rooms SET breakout_open=false, breakout_ends_at=NULL WHERE id=$1", room_id)
    await hub.broadcast(room_id, "breakout-close", {"room_id": room_id})
    await _broadcast_state(room_id)


@router.post("/{room_id}/breakouts/open")
async def open_breakouts(room_id: str, body: BreakoutOpen, user: CurrentUser = Depends(get_current_user)):
    if not user.is_staff:
        raise HTTPException(403)
    return await abrir_grupos(room_id, body.duration_seconds)


@router.post("/{room_id}/breakouts/close")
async def close_breakouts(room_id: str, user: CurrentUser = Depends(get_current_user)):
    if not user.is_staff:
        raise HTTPException(403)
    await _room_or_404(room_id)
    await fechar_grupos(room_id)
    return {"ok": True}


@router.post("/{room_id}/breakouts/message")
async def message_breakouts(room_id: str, body: BreakoutMessage, user: CurrentUser = Depends(get_current_user)):
    if not user.is_staff:
        raise HTTPException(403)
    await _room_or_404(room_id)
    text = (body.text or "").strip()[:500]
    if text:
        await hub.broadcast(room_id, "breakout-message", {"text": text, "from": user.name})
    return {"ok": True}


@router.post("/{room_id}/breakouts/token")
async def breakout_token(room_id: str, body: BreakoutTokenReq, user: CurrentUser | None = Depends(optional_user)):
    """Mint de token para a sala LiveKit de um grupo. Host visita qualquer grupo;
    participante só entra no grupo ao qual foi atribuído."""
    room = await _room_or_404(room_id)
    grp = await pool().fetchrow(
        "SELECT id, room_name, name FROM video_breakout_groups WHERE id=$1 AND parent_room_id=$2",
        body.group_id, room_id)
    if not grp:
        raise HTTPException(404, "group not found")
    is_host = bool(user and user.is_staff)
    if not is_host:
        if room["breakout_mode"] == "self":
            # Auto-seleção: registra a escolha do participante e segue.
            await pool().execute(
                "INSERT INTO video_breakout_assignments (parent_room_id, group_id, identity, display_name) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT (parent_room_id, identity) DO UPDATE "
                "SET group_id=EXCLUDED.group_id, display_name=EXCLUDED.display_name",
                room_id, body.group_id, body.identity, body.display_name or "")
            await _broadcast_state(room_id)
        else:
            assigned = await pool().fetchrow(
                "SELECT 1 FROM video_breakout_assignments WHERE parent_room_id=$1 AND identity=$2 AND group_id=$3",
                room_id, body.identity, body.group_id)
            if not assigned:
                raise HTTPException(403, "não atribuído a este grupo")
    tok = create_token(
        room_name=grp["room_name"], identity=body.identity,
        display_name=body.display_name or (user.name if user else "Participante"),
        is_admin=is_host, allow_screen_share=True,
    )
    url = settings.livekit_url
    if not url.startswith(("ws://", "wss://")):
        url = f"wss://{url}"
    return {"token": tok, "livekit_url": url, "identity": body.identity,
            "room_name": grp["room_name"], "group_name": grp["name"]}
