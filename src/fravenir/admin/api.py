"""Admin UI API routes — /api/* endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Never

from fastapi import APIRouter, Depends, HTTPException, Request

from fravenir.admin import queries, schemas
from fravenir.core import board as board_core

router = APIRouter()


def _kv_path(request: Request) -> Path:
    return request.app.state.kv_path  # type: ignore[no-any-return]


def _character_id(request: Request) -> str:
    return request.app.state.character_id  # type: ignore[no-any-return]


KvPath = Annotated[Path, Depends(_kv_path)]
CharacterId = Annotated[str, Depends(_character_id)]


@router.get("/stats", response_model=schemas.StatsResponse)
def get_stats(kv_path: KvPath) -> schemas.StatsResponse:
    return schemas.StatsResponse.model_validate(queries.get_stats(kv_path))


@router.get("/graph", response_model=schemas.GraphResponse)
def get_graph(
    kv_path: KvPath,
    scope: Literal["active", "archived", "all"] = "active",
) -> schemas.GraphResponse:
    return schemas.GraphResponse.model_validate(queries.get_graph(kv_path, scope))


@router.get("/episodes/{id}", response_model=schemas.EpisodeDetail)
def get_episode_detail(id: int, kv_path: KvPath) -> schemas.EpisodeDetail:
    result = queries.get_episode_detail(kv_path, id)
    if result is None:
        raise HTTPException(status_code=404)
    return schemas.EpisodeDetail.model_validate(result)


@router.get("/entities/{id}", response_model=schemas.EntityDetail)
def get_entity_detail(id: int, kv_path: KvPath) -> schemas.EntityDetail:
    result = queries.get_entity_detail(kv_path, id)
    if result is None:
        raise HTTPException(status_code=404)
    return schemas.EntityDetail.model_validate(result)


@router.get("/relations/{id}", response_model=schemas.RelationDetail)
def get_relation_detail(id: int, kv_path: KvPath) -> schemas.RelationDetail:
    result = queries.get_relation_detail(kv_path, id)
    if result is None:
        raise HTTPException(status_code=404)
    return schemas.RelationDetail.model_validate(result)


@router.get("/merge_candidates", response_model=schemas.MergeCandidatesResponse)
def get_merge_candidates(
    kv_path: KvPath,
    status: Literal["pending", "merged", "rejected", "all"] = "pending",
) -> schemas.MergeCandidatesResponse:
    return schemas.MergeCandidatesResponse.model_validate(
        queries.get_merge_candidates(kv_path, status)
    )


@router.get("/doc_status", response_model=schemas.DocStatusResponse)
def get_doc_status(
    kv_path: KvPath,
    status: Literal["failed", "all"] = "failed",
) -> schemas.DocStatusResponse:
    return schemas.DocStatusResponse.model_validate(queries.get_doc_status(kv_path, status))


@router.get("/orphans", response_model=schemas.OrphansResponse)
def get_orphans(
    kv_path: KvPath,
    scope: Literal["active", "archived", "all"] = "active",
) -> schemas.OrphansResponse:
    return schemas.OrphansResponse.model_validate(queries.get_orphans(kv_path, scope))


def _raise_board_error(exc: ValueError) -> Never:
    detail = str(exc)
    if "not found" in detail:
        raise HTTPException(status_code=404, detail=detail) from exc
    if detail.startswith("stale "):
        raise HTTPException(status_code=409, detail=detail) from exc
    raise HTTPException(status_code=400, detail=detail) from exc


@router.get("/board/spaces", response_model=schemas.BoardSpacesResponse)
def board_spaces(character_id: CharacterId) -> schemas.BoardSpacesResponse:
    return schemas.BoardSpacesResponse(
        spaces=board_core.list_spaces(character_id=character_id)
    )


@router.get("/board/threads", response_model=schemas.BoardThreadsResponse)
def board_threads(
    character_id: CharacterId,
    space_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
) -> schemas.BoardThreadsResponse:
    try:
        rows = board_core.list_threads(
            character_id=character_id,
            space_id=space_id,
            status=status,
            limit=limit,
        )
    except ValueError as exc:
        _raise_board_error(exc)
    return schemas.BoardThreadsResponse(threads=rows)


@router.get("/board/threads/{thread_id}", response_model=schemas.BoardThreadDetail)
def board_thread_detail(
    thread_id: int,
    character_id: CharacterId,
) -> schemas.BoardThreadDetail:
    try:
        result = board_core.get_thread(
            character_id=character_id,
            thread_id=thread_id,
        )
    except ValueError as exc:
        _raise_board_error(exc)
    return schemas.BoardThreadDetail.model_validate(result)


@router.get("/board/search", response_model=schemas.BoardSearchResponse)
def board_search(
    q: str,
    character_id: CharacterId,
    limit: int = 20,
) -> schemas.BoardSearchResponse:
    try:
        results = board_core.search_board(
            character_id=character_id,
            query=q,
            limit=limit,
        )
    except ValueError as exc:
        _raise_board_error(exc)
    return schemas.BoardSearchResponse(results=results)


@router.post("/board/spaces", response_model=schemas.BoardCreateSpaceResponse)
def board_create_space(
    payload: schemas.BoardCreateSpaceRequest,
    character_id: CharacterId,
) -> schemas.BoardCreateSpaceResponse:
    try:
        result = board_core.create_space(
            character_id=character_id,
            name=payload.name,
            description=payload.description,
        )
    except ValueError as exc:
        _raise_board_error(exc)
    return schemas.BoardCreateSpaceResponse.model_validate(result)


@router.post("/board/threads", response_model=schemas.BoardCreateThreadResponse)
def board_create_thread(
    payload: schemas.BoardCreateThreadRequest,
    character_id: CharacterId,
) -> schemas.BoardCreateThreadResponse:
    try:
        result = board_core.create_thread(
            character_id=character_id,
            space_id=payload.space_id,
            title=payload.title,
            author_kind=payload.author_kind,
            author_display_name=payload.author_display_name,
            author_external_subject=payload.author_external_subject,
            initial_post=payload.initial_post,
        )
    except ValueError as exc:
        _raise_board_error(exc)
    return schemas.BoardCreateThreadResponse.model_validate(result)


@router.post(
    "/board/threads/{thread_id}/posts",
    response_model=schemas.BoardPostResponse,
)
def board_add_post(
    thread_id: int,
    payload: schemas.BoardPostRequest,
    character_id: CharacterId,
) -> schemas.BoardPostResponse:
    try:
        result = board_core.add_post(
            character_id=character_id,
            thread_id=thread_id,
            body=payload.body,
            author_kind=payload.author_kind,
            author_display_name=payload.author_display_name,
            author_external_subject=payload.author_external_subject,
            kind=payload.kind,
            parent_post_id=payload.parent_post_id,
        )
    except ValueError as exc:
        _raise_board_error(exc)
    return schemas.BoardPostResponse.model_validate(result)


@router.patch("/board/posts/{post_id}", response_model=schemas.BoardEditPostResponse)
def board_edit_post(
    post_id: int,
    payload: schemas.BoardEditPostRequest,
    character_id: CharacterId,
) -> schemas.BoardEditPostResponse:
    try:
        result = board_core.edit_post(
            character_id=character_id,
            post_id=post_id,
            body=payload.body,
            expected_revision=payload.expected_revision,
            editor_kind=payload.editor_kind,
            editor_display_name=payload.editor_display_name,
            editor_external_subject=payload.editor_external_subject,
        )
    except ValueError as exc:
        _raise_board_error(exc)
    return schemas.BoardEditPostResponse.model_validate(result)


@router.post(
    "/board/threads/{thread_id}/organize",
    response_model=schemas.BoardOrganizeResponse,
)
def board_organize_thread(
    thread_id: int,
    payload: schemas.BoardOrganizeRequest,
    character_id: CharacterId,
) -> schemas.BoardOrganizeResponse:
    try:
        result = board_core.organize_thread(
            character_id=character_id,
            thread_id=thread_id,
            summary=payload.summary,
            source_post_ids=payload.source_post_ids,
            expected_thread_version=payload.expected_thread_version,
            author_kind=payload.author_kind,
            author_display_name=payload.author_display_name,
            author_external_subject=payload.author_external_subject,
        )
    except ValueError as exc:
        _raise_board_error(exc)
    return schemas.BoardOrganizeResponse.model_validate(result)


def _reembed_entity(request: Request, entity_id: int, name: str, description: str) -> None:
    """Description が curated 経由で更新された entity の vdb_entities を再エンベディング。

    Embedder は遅延初期化 (admin/server.py で app.state.embedder=None)。
    sentence-transformers のロード/モデルキャッシュが効くので、初回 PATCH のみ重い。
    """
    import sqlite3

    import sqlite_vec
    import structlog
    import yaml

    from fravenir.embedding import Embedder
    from fravenir.schemas.config import AppConfig
    from fravenir.storage.paths import config_yaml_path
    from fravenir.storage.vector import upsert_entity_vector

    log = structlog.get_logger(__name__)
    state = request.app.state
    embedder: Embedder | None = state.embedder
    if embedder is None:
        character_id: str = state.character_id
        cfg_path = config_yaml_path(character_id)
        if cfg_path.exists():
            with cfg_path.open(encoding="utf-8") as f:
                raw_cfg = yaml.safe_load(f) or {}
            if isinstance(raw_cfg, dict):
                raw_cfg.setdefault("character", {})["id"] = character_id
            else:
                raw_cfg = {"character": {"id": character_id}}
        else:
            raw_cfg = {"character": {"id": character_id}}
        app_cfg = AppConfig.model_validate(raw_cfg)
        embedder = Embedder(app_cfg.embedding)
        state.embedder = embedder

    text = f"{name} {description}".strip() if description else name
    vec = embedder.encode_topic(text)

    vdb_path: Path = state.vdb_entities_path
    conn = sqlite3.connect(str(vdb_path))
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        upsert_entity_vector(conn, entity_id, vec)
        conn.commit()
    finally:
        conn.close()
    log.info("admin_entity_reembedded", entity_id=entity_id)


@router.patch("/entities/{id}", response_model=schemas.EntityUpdateResponse)
def update_entity(
    id: int,
    payload: schemas.EntityUpdateRequest,
    request: Request,
    kv_path: KvPath,
) -> schemas.EntityUpdateResponse:
    """Entity の description / aliases を更新し curated_at を立てる。

    変更がない (description/aliases ともに現値と一致) 場合は changed=False を返し、
    DB は更新しない。description が変わった場合は vdb_entities も再エンベディング。
    """
    if payload.description is None and payload.aliases is None:
        raise HTTPException(
            status_code=400,
            detail="at least one of description / aliases must be provided",
        )
    try:
        result = queries.update_entity(
            kv_path,
            id,
            description=payload.description,
            aliases=payload.aliases,
        )
    except queries.EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result["changed"] and result["before"]["description"] != result["after"]["description"]:
        # description が変わったので vdb 再エンベディング
        # canonical_name は取得し直す (queries.update_entity 内で保証された active 行)
        import sqlite3 as _sqlite3

        conn = _sqlite3.connect(kv_path)
        try:
            row = conn.execute(
                "SELECT canonical_name FROM entities WHERE id = ?", (id,)
            ).fetchone()
        finally:
            conn.close()
        if row is not None:
            _reembed_entity(request, id, row[0], result["after"]["description"] or "")

    return schemas.EntityUpdateResponse.model_validate(result)


@router.get("/audit_log", response_model=schemas.AuditLogResponse)
def get_audit_log(
    kv_path: KvPath,
    target_type: str | None = None,
    target_id: int | None = None,
    limit: int = 100,
) -> schemas.AuditLogResponse:
    try:
        entries = queries.list_audit_log(
            kv_path,
            target_type=target_type,
            target_id=target_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return schemas.AuditLogResponse.model_validate({"entries": entries})
