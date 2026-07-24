import json as _json
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..auth import get_current_user, optional_user, CurrentUser
from ..config import settings
from ..db import pool
from ..models.schemas import RoomCreate, RoomOut, BookingSync, PermissionUpdate
from ..realtime.hub import hub
from ..room_roles import roles_public as _roles_public, is_host_or_mod as _is_host_or_mod, update_roles as _update_roles
from ..services.recording_service import presigned_url
from ..services.livekit_service import set_participant_sources, remove_participant, list_participant_identities
from ..tenancy import resolve_tenant_id, get_effective_limits, normalize_branding

router = APIRouter(prefix="/api/rooms", tags=["rooms"])

# Política fixa de criação de sala. O modal não expõe estes campos, mas esconder na
# UI não basta: sem forçar aqui, qualquer um os alteraria chamando POST /api/rooms
# pelo console do navegador. A licença ainda pode apertar o teto de participantes.
ROOM_MAX_PARTICIPANTS = 35


def _row_to_room(r) -> dict:
    d = dict(r)
    d["id"] = str(d["id"])
    # jsonb → asyncpg devolve str; parseia de volta para list/dict
    for campo in ("risk_dimensions", "roteiro"):
        bruto = d.get(campo)
        if isinstance(bruto, str):
            try:
                d[campo] = _json.loads(bruto)
            except Exception:
                d[campo] = None
    return d


def _roteiro_com_banner(roteiro):
    """Troca a CHAVE do banner de fundo por uma URL assinada, para a sala exibir.

    O roteiro guarda a chave do S3, não a URL: presigned URLs duram horas e o roteiro
    do episódio vive meses. A assinatura acontece a cada carga da sala — mesma
    abordagem do vídeo de fundo do saguão (`lobby_bg_video`).
    """
    if not isinstance(roteiro, dict):
        return roteiro
    campos = roteiro.get("campos")
    if not isinstance(campos, dict):
        return roteiro
    chave = campos.get("bannerFundo")
    if isinstance(chave, str) and chave and "://" not in chave:
        try:
            campos["bannerFundo"] = presigned_url(chave, expires=6 * 3600)
        except Exception:
            campos["bannerFundo"] = ""    # banner indisponível não pode quebrar a sala
    return roteiro


def _is_scorm(slug: str | None) -> bool:
    """A licença (tenant) tem a integração OpenPBL/SCORM ativa?"""
    if not slug:
        return False
    return slug in {s.strip() for s in settings.scorm_tenant_slugs.split(",") if s.strip()}


class RolesUpdate(BaseModel):
    add_moderator: str | None = None
    remove_moderator: str | None = None
    set_controller: bool = False       # aplica `controller` (aceita None p/ liberar)
    controller: str | None = None
    set_pinned: bool = False           # aplica `pinned` (aceita None p/ voltar ao host)
    pinned: str | None = None


@router.get("/{room_id}/roles")
async def get_roles(room_id: str, user: CurrentUser | None = Depends(optional_user)):
    """Papéis atuais da sessão (público — todos leem p/ renderizar câmera fixada etc.)."""
    return await _roles_public(room_id)


@router.post("/{room_id}/roles")
async def set_roles(room_id: str, body: RolesUpdate, user: CurrentUser = Depends(get_current_user)):
    """Anfitrião/moderador promove moderadores, assume o controle e fixa a câmera."""
    if not await _is_host_or_mod(room_id, user):
        raise HTTPException(403)
    payload = await _update_roles(
        room_id,
        add_moderator=body.add_moderator, remove_moderator=body.remove_moderator,
        set_controller=body.set_controller, controller=body.controller,
        set_pinned=body.set_pinned, pinned=body.pinned,
    )
    await hub.broadcast(room_id, "roles-updated", payload)
    return payload


@router.post("", response_model=RoomOut)
async def create_room(
    body: RoomCreate,
    user: CurrentUser = Depends(get_current_user),
    tenant_id: str = Depends(resolve_tenant_id),
):
    # Enforce the license limits (effective = override ?? plan ?? default).
    limits = await get_effective_limits(tenant_id)
    if limits["max_rooms"] != -1:
        active = await pool().fetchval(
            "SELECT count(*) FROM video_rooms WHERE tenant_id=$1 AND status='active'", tenant_id
        )
        if active >= limits["max_rooms"]:
            raise HTTPException(403, f"limite de salas ativas da licença atingido ({limits['max_rooms']})")
    cap = limits["max_participants"]
    max_participants = min(ROOM_MAX_PARTICIPANTS, cap) if cap and cap > 0 else ROOM_MAX_PARTICIPANTS
    auto_record = body.auto_record and limits["recording_enabled"]

    room_id = f"room_{secrets.token_urlsafe(8)}"
    guest_token = secrets.token_urlsafe(16)
    row = await pool().fetchrow(
        """
        INSERT INTO video_rooms
          (tenant_id, room_id, title, description, owner_id, max_participants, is_public, auto_record,
           lobby_enabled, lobby_timer_title, lobby_timer_seconds, lobby_bg_video, lobby_auto_admit,
           guest_token, allow_camera, allow_mic, allow_screen_share, allow_whiteboard_edit,
           scheduled_at, external_ref, require_email, openpbl_activity_id, openpbl_dimensions_id,
           class_package_url, risk_dimensions, episode_id, roteiro)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25::jsonb,$26,$27::jsonb)
        RETURNING *
        """,
        tenant_id, room_id, body.title, body.description, user.id, max_participants, body.is_public,
        # Saguão (lobby) vem do corpo da requisição — o salas/CustomerApp envia
        # lobby_enabled + título/tempo/vídeo/auto-admissão. Edição de quadro segue
        # desligada por padrão (controle removido do modal).
        auto_record, body.lobby_enabled, body.lobby_timer_title, body.lobby_timer_seconds,
        body.lobby_bg_video, body.lobby_auto_admit, guest_token,
        body.allow_camera, body.allow_mic, body.allow_screen_share, False,
        body.scheduled_at, body.external_ref, body.require_email, body.openpbl_activity_id,
        body.openpbl_dimensions_id, (body.class_package_url or None),
        (_json.dumps(body.risk_dimensions) if body.risk_dimensions else None),
        (body.episode_id or None),
        (_json.dumps(body.roteiro) if body.roteiro else None),
    )
    return _row_to_room(row)


@router.get("", response_model=list[RoomOut])
async def list_rooms(
    user: CurrentUser = Depends(get_current_user),
    tenant_id: str = Depends(resolve_tenant_id),
):
    if user.is_staff:
        rows = await pool().fetch(
            "SELECT * FROM video_rooms WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT 200",
            tenant_id,
        )
    else:
        rows = await pool().fetch(
            "SELECT * FROM video_rooms WHERE tenant_id=$1 AND owner_id=$2 ORDER BY created_at DESC LIMIT 200",
            tenant_id, user.id,
        )
    return [_row_to_room(r) for r in rows]


@router.get("/by-guest-token/{token}")
async def room_by_guest_token(token: str):
    """Public: resolve a room from a guest invite token (no auth).
    Lets an invite link page show the room and prompt for a display name."""
    row = await pool().fetchrow(
        """SELECT r.id, r.title, r.status, r.lobby_enabled, r.lobby_timer_title,
                  r.lobby_timer_seconds, r.lobby_bg_video, r.lobby_auto_admit, r.require_email,
                  r.allow_whiteboard_edit, r.created_at,
                  t.branding, t.name AS tenant_name, t.slug AS tenant_slug
           FROM video_rooms r LEFT JOIN tenants t ON t.id = r.tenant_id
           WHERE r.guest_token=$1""",
        token,
    )
    if not row or row["status"] == "ended":
        raise HTTPException(404, "invite not valid")
    # lobby_bg_video stores an S3 key for uploaded videos — presign it for playback.
    bg = row["lobby_bg_video"]
    if bg and "://" not in bg:
        try:
            bg = presigned_url(bg, expires=6 * 3600)
        except Exception:
            bg = None
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "status": row["status"],
        "lobby_enabled": row["lobby_enabled"],
        "lobby_timer_title": row["lobby_timer_title"],
        "lobby_timer_seconds": row["lobby_timer_seconds"],
        "lobby_bg_video": bg,
        "lobby_auto_admit": row["lobby_auto_admit"],
        "require_email": row["require_email"],
        "allow_whiteboard_edit": row["allow_whiteboard_edit"],
        "created_at": row["created_at"],   # âncora do countdown do saguão (compartilhado)
        "branding": normalize_branding(row["branding"]),
        "tenant_name": row["tenant_name"],
        "scorm": _is_scorm(row["tenant_slug"]),
    }


@router.get("/{room_id}/public")
async def room_public(room_id: str):
    """Public, minimal room info (title + license branding) for the iframe embed.
    Inclui os campos do saguão (lobby) para o embed poder reter os alunos antes de
    entrar — o embed do cliente OpenPBL também respeita o lobby."""
    r = await pool().fetchrow(
        """SELECT r.title, r.require_email, r.allow_whiteboard_edit,
                  r.lobby_enabled, r.lobby_timer_title, r.lobby_timer_seconds,
                  r.lobby_bg_video, r.lobby_auto_admit, r.class_package_url, r.risk_dimensions,
                  r.roteiro, r.created_at,
                  t.branding, t.name AS tenant_name, t.slug AS tenant_slug
           FROM video_rooms r LEFT JOIN tenants t ON t.id = r.tenant_id WHERE r.id=$1""",
        room_id,
    )
    if not r:
        raise HTTPException(404)
    # lobby_bg_video guarda uma chave S3 — presigna para o <video> tocar.
    bg = r["lobby_bg_video"]
    if bg and "://" not in bg:
        try:
            bg = presigned_url(bg, expires=6 * 3600)
        except Exception:
            bg = None
    return {"title": r["title"], "branding": normalize_branding(r["branding"]),
            "tenant_name": r["tenant_name"], "require_email": r["require_email"],
            "allow_whiteboard_edit": r["allow_whiteboard_edit"],
            "lobby_enabled": r["lobby_enabled"],
            "lobby_timer_title": r["lobby_timer_title"],
            "lobby_timer_seconds": r["lobby_timer_seconds"],
            "lobby_bg_video": bg,
            "lobby_auto_admit": r["lobby_auto_admit"],
            "class_package_url": r["class_package_url"],
            "risk_dimensions": (_json.loads(r["risk_dimensions"]) if isinstance(r["risk_dimensions"], str) else r["risk_dimensions"]),
            # Roteiro do episódio: é o conteúdo do encontro (sinopse, questões, riscos),
            # renderizado nativamente pela sala. Vale para o aluno também.
            "roteiro": _roteiro_com_banner(
                _json.loads(r["roteiro"]) if isinstance(r["roteiro"], str) else r["roteiro"]
            ),
            "created_at": r["created_at"],   # âncora do countdown do saguão (compartilhado)
            "scorm": _is_scorm(r["tenant_slug"])}


@router.get("/branding/{slug}")
async def tenant_branding(slug: str):
    """Public branding for a license (logo/cores/nome) to white-label the app."""
    r = await pool().fetchrow(
        "SELECT name, branding FROM tenants WHERE slug=$1 AND status='active'", slug
    )
    if not r:
        return {"name": None, "branding": {}}
    return {"name": r["name"], "branding": normalize_branding(r["branding"])}


@router.get("/{room_id}", response_model=RoomOut)
async def get_room(room_id: str, user: CurrentUser = Depends(get_current_user)):
    row = await pool().fetchrow("SELECT * FROM video_rooms WHERE id=$1", room_id)
    if not row:
        raise HTTPException(404, "Room not found")
    return _row_to_room(row)


@router.post("/{room_id}/end")
async def end_room(
    room_id: str,
    user: CurrentUser = Depends(get_current_user),
    tenant_id: str = Depends(resolve_tenant_id),
):
    row = await pool().fetchrow("SELECT owner_id, tenant_id FROM video_rooms WHERE id=$1", room_id)
    if not row:
        raise HTTPException(404)
    if str(row["tenant_id"]) != tenant_id:
        raise HTTPException(403, "room does not belong to this tenant")
    if not await _is_host_or_mod(room_id, user) and row["owner_id"] != user.id:
        raise HTTPException(403)
    await pool().execute(
        "UPDATE video_rooms SET status='ended', ended_at=now(), updated_at=now() WHERE id=$1",
        room_id,
    )
    await hub.broadcast(room_id, "room-ended", {"room_id": room_id})
    return {"ok": True}


@router.post("/{room_id}/participants/{target}/permissions")
async def update_permissions(
    room_id: str,
    target: str,
    body: PermissionUpdate,
    user: CurrentUser = Depends(get_current_user),
):
    if not await _is_host_or_mod(room_id, user):
        raise HTTPException(403)
    fields, values = [], []
    for i, (k, v) in enumerate([(f, getattr(body, f)) for f in
        ("allow_camera", "allow_mic", "allow_screen_share", "allow_whiteboard_edit")]):
        if v is not None:
            fields.append(f"{k}=${len(values)+3}")
            values.append(v)
    if not fields:
        return {"ok": True}
    await pool().execute(
        f"""
        INSERT INTO video_room_participant_permissions
          (room_id, user_id, allow_camera, allow_mic, allow_screen_share, allow_whiteboard_edit)
        VALUES ($1,$2,
          COALESCE($3,true),COALESCE($4,true),COALESCE($5,true),COALESCE($6,false))
        ON CONFLICT (room_id, user_id) DO UPDATE
          SET allow_camera=COALESCE(EXCLUDED.allow_camera, video_room_participant_permissions.allow_camera),
              allow_mic=COALESCE(EXCLUDED.allow_mic, video_room_participant_permissions.allow_mic),
              allow_screen_share=COALESCE(EXCLUDED.allow_screen_share, video_room_participant_permissions.allow_screen_share),
              allow_whiteboard_edit=COALESCE(EXCLUDED.allow_whiteboard_edit, video_room_participant_permissions.allow_whiteboard_edit),
              updated_at=now()
        """,
        room_id, target,
        body.allow_camera, body.allow_mic, body.allow_screen_share, body.allow_whiteboard_edit,
    )
    # Estado final + aplica no SFU (autoritativo: concede/revoga de verdade).
    perm = await pool().fetchrow(
        "SELECT allow_camera, allow_mic, allow_screen_share, allow_whiteboard_edit "
        "FROM video_room_participant_permissions WHERE room_id=$1 AND user_id=$2", room_id, target)
    room = await pool().fetchrow("SELECT room_id FROM video_rooms WHERE id=$1", room_id)
    if perm and room:
        try:
            await set_participant_sources(room["room_id"], target,
                camera=perm["allow_camera"], mic=perm["allow_mic"], screen=perm["allow_screen_share"])
        except Exception:
            pass  # melhor-esforço; o enforcer client-side cobre o caso
    await hub.broadcast(room_id, "permissions-updated",
                        {"user_id": target, **(dict(perm) if perm else body.model_dump(exclude_none=True))})
    return {"ok": True}


@router.post("/{room_id}/moderation/{action}")
async def moderation(room_id: str, action: str, target: dict, user: CurrentUser = Depends(get_current_user)):
    """action ∈ force-mute | force-unmute | force-camera-off | force-kick"""
    if not await _is_host_or_mod(room_id, user):
        raise HTTPException(403)
    if action not in {"force-mute", "force-unmute", "force-camera-off", "force-kick"}:
        raise HTTPException(400, "bad action")
    if action == "force-kick" and target.get("user_id"):
        room = await pool().fetchrow("SELECT room_id FROM video_rooms WHERE id=$1", room_id)
        if room:
            try:
                await remove_participant(room["room_id"], target["user_id"])
            except Exception:
                pass
    await hub.broadcast(room_id, action, target)
    return {"ok": True}


@router.put("/{room_id}/permissions")
async def update_room_permissions(room_id: str, body: PermissionUpdate, user: CurrentUser = Depends(get_current_user)):
    """Permissões globais da sala durante a chamada (aba de configurações do host).
    Atualiza o padrão (novos participantes) e aplica aos atuais, exceto o próprio host."""
    if not await _is_host_or_mod(room_id, user):
        raise HTTPException(403)
    sets, args = [], []
    for f in ("allow_camera", "allow_mic", "allow_screen_share", "allow_whiteboard_edit"):
        v = getattr(body, f)
        if v is not None:
            args.append(v); sets.append(f"{f}=${len(args)}")
    if not sets:
        return {"ok": True}
    args.append(room_id)
    await pool().execute(
        f"UPDATE video_rooms SET {', '.join(sets)}, updated_at=now() WHERE id=${len(args)}", *args)
    room = await pool().fetchrow(
        "SELECT room_id, allow_camera, allow_mic, allow_screen_share, allow_whiteboard_edit "
        "FROM video_rooms WHERE id=$1", room_id)
    if room:
        try:
            for ident in await list_participant_identities(room["room_id"]):
                if ident == user.id:
                    continue  # nunca rebaixa o próprio host
                await set_participant_sources(room["room_id"], ident,
                    camera=room["allow_camera"], mic=room["allow_mic"], screen=room["allow_screen_share"])
        except Exception:
            pass
    perms = {k: room[k] for k in ("allow_camera", "allow_mic", "allow_screen_share", "allow_whiteboard_edit")} if room else {}
    await hub.broadcast(room_id, "room-permissions", perms)              # UI dos hosts
    await hub.broadcast(room_id, "permissions-updated", perms)           # enforcer (host é isento)
    return {"ok": True, **perms}


@router.get("/{room_id}/scorm/progress")
async def scorm_progress(room_id: str, user: CurrentUser = Depends(get_current_user)):
    """Progresso dos alunos da chamada no pacote OpenPBL (SCORM).
    Casa os participantes (por e-mail) com os eventos do LRS de interações,
    escopado à sessão atual (eventos desde a criação da sala)."""
    import asyncio as _asyncio
    from datetime import timezone as _tz
    import httpx
    if not user.is_staff:
        raise HTTPException(403)
    room = await pool().fetchrow(
        "SELECT r.created_at, r.owner_id, t.slug AS tenant_slug FROM video_rooms r "
        "LEFT JOIN tenants t ON t.id=r.tenant_id WHERE r.id=$1", room_id)
    if not room:
        raise HTTPException(404)
    if not _is_scorm(room["tenant_slug"]):
        return {"scorm": False, "students": []}

    since_iso = room["created_at"].astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%S")
    # Apenas alunos: nunca o anfitrião/staff nem o dono da sala (que entra como host
    # e tem o próprio e-mail, senão apareceria como "aluno" em toda sessão).
    parts = await pool().fetch(
        "SELECT DISTINCT ON (lower(email)) email, display_name FROM video_room_participants "
        "WHERE room_id=$1 AND email IS NOT NULL AND email <> '' "
        "AND is_staff = false AND user_id <> $2 "
        "ORDER BY lower(email), joined_at DESC", room_id, room["owner_id"])
    base = settings.scorm_lrs_url.rstrip("/")

    async def fetch_events_by_student(emails_list: list[str]) -> tuple[dict, bool]:
        """Eventos de TODOS os alunos numa ÚNICA chamada ao LRS.

        Antes era 1 request por aluno disparado em paralelo (asyncio.gather): numa aula
        grande abria N conexões simultâneas no Scorm, esgotava o pool e derrubava o
        serviço (incidente 2026-07-24). Retorna (mapa email->eventos, ok); ok=False marca
        todos como "erro" — mesmo comportamento do try/except por aluno de antes.
        """
        if not emails_list:
            return {}, True
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                resp = await c.get(f"{base}/interaction-events/by-students",
                                   params={"studentEmails": ",".join(emails_list),
                                           "limitPerStudent": 300})
            return ((resp.json() or {}).get("data") or {}), True
        except Exception:
            return {}, False

    def one(email: str, name: str | None, evs, lrs_ok: bool) -> dict:
        out = {"email": email, "name": name or email, "status": "nao-abriu",
               "done_lessons": [], "lessons_done": 0, "completed": False,
               "tipo": None, "last_activity": None, "events": 0, "_lesson_first": {}}
        if not lrs_ok:
            out["status"] = "erro"
            return out
        sess = [e for e in (evs or []) if (e.get("createdAt") or "") >= since_iso]
        if not sess:
            return out
        sess.sort(key=lambda x: x.get("createdAt") or "", reverse=True)
        out["events"] = len(sess)
        out["last_activity"] = sess[0].get("createdAt")
        out["tipo"] = next((e.get("tipoScorm") for e in sess if e.get("tipoScorm")), None)
        if not name or name == email:
            out["name"] = next((e.get("studentName") for e in sess if e.get("studentName")), out["name"])

        # Lições: cada lessonId é uma bolinha. Concluída (verde) = houve lesson_score.
        lessons: dict = {}
        for e in sess:
            pl = e.get("payload") or {}
            et = e.get("eventType")
            if et not in ("quiz_answered", "lesson_score"):
                continue
            lid = pl.get("lessonId") or e.get("object")
            if not lid:
                continue
            t = e.get("createdAt") or ""
            L = lessons.setdefault(lid, {"done": False, "first": t})
            if t and (not L["first"] or t < L["first"]):
                L["first"] = t
            if et == "lesson_score":
                L["done"] = True
        out["done_lessons"] = [lid for lid, L in lessons.items() if L["done"]]
        out["lessons_done"] = len(out["done_lessons"])
        out["_lesson_first"] = {lid: L["first"] for lid, L in lessons.items()}
        out["completed"] = any(e.get("eventType") == "package_completed" or e.get("verb") == "completed" for e in sess)
        opened = any(e.get("eventType") in ("package_opened", "activity_accessed", "authenticated") for e in sess)
        if out["completed"]:
            out["status"] = "concluido"
        elif sess[0].get("eventType") == "package_exited":
            out["status"] = "saiu"
        elif opened:
            out["status"] = "ativo"
        return out

    _by_student, _lrs_ok = await fetch_events_by_student([p["email"] for p in parts])
    students = [one(p["email"], p["display_name"], _by_student.get(p["email"]), _lrs_ok)
                for p in parts]
    # Universo de lições da sessão (união de todos os alunos), ordenado pela 1ª aparição.
    firsts: dict = {}
    for s in students:
        for lid, t in (s.pop("_lesson_first", {}) or {}).items():
            if lid not in firsts or (t and t < (firsts[lid] or "")):
                firsts[lid] = t
    lesson_order = sorted(firsts.keys(), key=lambda lid: firsts.get(lid) or "")
    students = sorted(students, key=lambda s: (s["name"] or "").lower())
    return {"scorm": True, "since": since_iso, "count": len(students),
            "lessons": lesson_order, "lessons_total": len(lesson_order), "students": students}


@router.post("/bookings/sync", response_model=RoomOut)
async def booking_sync(body: BookingSync, user: CurrentUser = Depends(get_current_user)):
    """Idempotent: returns the existing room if external_ref is already linked."""
    existing = await pool().fetchrow(
        "SELECT * FROM video_rooms WHERE external_ref=$1", body.external_ref
    )
    if existing:
        return _row_to_room(existing)
    room_id = f"room_{secrets.token_urlsafe(8)}"
    guest_token = secrets.token_urlsafe(16)
    row = await pool().fetchrow(
        """
        INSERT INTO video_rooms
          (room_id, title, owner_id, lobby_enabled, guest_token, scheduled_at, external_ref)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        RETURNING *
        """,
        room_id, body.title, body.owner_id, body.lobby_enabled, guest_token,
        body.scheduled_at, body.external_ref,
    )
    return _row_to_room(row)
