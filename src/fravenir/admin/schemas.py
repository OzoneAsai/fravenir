"""Pydantic v2 schemas for admin UI API responses."""

from typing import Literal

from pydantic import BaseModel, Field


class StatsEpisodes(BaseModel):
    total: int
    active: int
    suppressed: int


class StatsEntities(BaseModel):
    total: int
    active: int
    is_self: int


class StatsRelations(BaseModel):
    total: int
    active: int


class StatsMergeCandidates(BaseModel):
    pending: int
    merged: int
    rejected: int


class StatsOrphans(BaseModel):
    episodes: int
    entities: int


class StatsResponse(BaseModel):
    episodes: StatsEpisodes
    entities: StatsEntities
    relations: StatsRelations
    merge_candidates: StatsMergeCandidates
    doc_status_failed: int
    orphans: StatsOrphans


class GraphNodeEpisodeData(BaseModel):
    id: str
    label: str
    type: str
    kind: str
    importance: int
    is_active: bool
    is_suppressed: bool
    supersedes: int | None


class GraphNodeEntityData(BaseModel):
    id: str
    label: str
    type: str
    entity_type: str
    is_self: bool
    is_active: bool
    supersedes: int | None


class GraphNode(BaseModel):
    data: GraphNodeEpisodeData | GraphNodeEntityData


class GraphEdgeMentionsData(BaseModel):
    id: str
    source: str
    target: str
    type: str
    is_active: bool


class GraphEdgeRelationData(BaseModel):
    id: str
    source: str
    target: str
    type: str
    predicate: str
    strength: float
    is_active: bool


class GraphEdge(BaseModel):
    data: GraphEdgeMentionsData | GraphEdgeRelationData


class GraphElements(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GraphStats(BaseModel):
    nodes: int
    edges: int


class GraphResponse(BaseModel):
    scope: str
    stats: GraphStats
    elements: GraphElements


class DocStatus(BaseModel):
    stage: str
    error: str | None
    updated_at: str | None


class EpisodeMention(BaseModel):
    entity_id: int
    canonical_name: str
    is_self: bool


class EpisodeDetail(BaseModel):
    id: int
    content: str
    kind: str
    importance: int
    valid_from: str
    valid_to: str | None
    supersedes: int | None
    session_id: str | None
    last_activated_at: str | None
    activation_count: int
    is_suppressed: bool
    created_at: str
    doc_status: DocStatus
    mentions: list[EpisodeMention]


class EntityInRelation(BaseModel):
    id: int
    src_type: str
    src_id: int
    predicate: str


class EntityOutRelation(BaseModel):
    id: int
    dst_type: str
    dst_id: int
    predicate: str
    strength: float | None = None


class EntityDetail(BaseModel):
    id: int
    canonical_name: str
    entity_type: str
    description: str | None
    is_self: bool
    self_weight: float
    decay_rate: float
    valid_from: str
    valid_to: str | None
    supersedes: int | None
    last_activated_at: str | None
    activation_count: int
    created_at: str
    curated_at: str | None
    aliases: list[str]
    in_relations: list[EntityInRelation]
    out_relations: list[EntityOutRelation]


class EntityUpdateRequest(BaseModel):
    """AdminUI からの entity 編集リクエスト。

    description / aliases のいずれか一方だけの更新も可 (None を渡せばその項目はスキップ)。
    更新が発生した場合は entities.curated_at が現在時刻に更新され、admin_audit_log に
    before/after が記録される。
    """

    description: str | None = Field(default=None, max_length=4000)
    aliases: list[str] | None = Field(default=None, max_length=64)


class RelationDetail(BaseModel):
    id: int
    src_type: str
    src_id: int
    src_label: str
    dst_type: str
    dst_id: int
    dst_label: str
    predicate: str
    strength: float
    fan_out: int
    description: str | None
    valid_from: str
    valid_to: str | None
    supersedes: int | None
    created_at: str


class MergeCandidateEntity(BaseModel):
    id: int
    canonical_name: str


class MergeCandidate(BaseModel):
    id: int
    entity_a: MergeCandidateEntity
    entity_b: MergeCandidateEntity
    similarity: float
    detected_at: str
    resolved: int
    judge_label: str | None
    judge_confidence: str | None
    judge_reason: str | None
    judge_attempts: int
    resolved_at: str | None


class MergeCandidatesResponse(BaseModel):
    status_filter: str
    candidates: list[MergeCandidate]


class DocStatusItem(BaseModel):
    id: int
    episode_id: int
    stage: str
    error: str | None
    updated_at: str
    episode_label: str


class DocStatusResponse(BaseModel):
    status_filter: str
    items: list[DocStatusItem]


class OrphanEpisode(BaseModel):
    id: int
    label: str
    kind: str
    created_at: str


class OrphanEntity(BaseModel):
    id: int
    canonical_name: str
    is_self: bool
    created_at: str


class OrphansResponse(BaseModel):
    scope: str
    episodes: list[OrphanEpisode]
    entities: list[OrphanEntity]



class EntityUpdateResponse(BaseModel):
    """PATCH /entities/{id} の戻り値。"""

    changed: bool
    before: dict[str, object]
    after: dict[str, object]
    curated_at: str | None


class AuditLogEntry(BaseModel):
    id: int
    action: str
    target_type: str
    target_id: int
    before: dict[str, object] | None
    after: dict[str, object] | None
    actor: str | None
    created_at: str


class AuditLogResponse(BaseModel):
    entries: list[AuditLogEntry]


class BoardSpaceItem(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: str
    thread_count: int


class BoardSpacesResponse(BaseModel):
    spaces: list[BoardSpaceItem]


class BoardThreadItem(BaseModel):
    id: int
    space_id: int
    title: str
    status: str
    version: int
    created_at: str
    updated_at: str
    post_count: int


class BoardThreadsResponse(BaseModel):
    threads: list[BoardThreadItem]


class BoardThreadMeta(BaseModel):
    id: int
    space_id: int
    title: str
    status: str
    version: int
    created_at: str
    updated_at: str
    created_by_id: int | None
    created_by_kind: str | None
    created_by_name: str | None


class BoardPostItem(BaseModel):
    id: int
    parent_post_id: int | None
    kind: str
    body: str
    revision: int
    created_at: str
    edited_at: str | None
    author_id: int | None
    author_kind: str | None
    author_name: str | None


class BoardThreadDetail(BaseModel):
    thread: BoardThreadMeta
    posts: list[BoardPostItem]


class BoardCreateSpaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)


class BoardCreateSpaceResponse(BaseModel):
    space_id: int
    name: str
    description: str | None


class BoardCreateThreadRequest(BaseModel):
    space_id: int
    title: str = Field(min_length=1, max_length=300)
    author_display_name: str = Field(min_length=1, max_length=128)
    author_kind: Literal["human", "agent", "system"] = "human"
    author_external_subject: str | None = Field(default=None, max_length=512)
    initial_post: str | None = Field(default=None, max_length=20000)


class BoardCreateThreadResponse(BaseModel):
    thread_id: int
    space_id: int
    title: str
    version: int
    initial_post_id: int | None


class BoardPostRequest(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    author_display_name: str = Field(min_length=1, max_length=128)
    author_kind: Literal["human", "agent", "system"] = "human"
    author_external_subject: str | None = Field(default=None, max_length=512)
    kind: Literal["message", "summary", "decision", "note"] = "message"
    parent_post_id: int | None = None


class BoardPostResponse(BaseModel):
    post_id: int
    thread_id: int
    thread_version: int
    revision: int


class BoardEditPostRequest(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    expected_revision: int = Field(ge=1)
    editor_display_name: str = Field(min_length=1, max_length=128)
    editor_kind: Literal["human", "agent", "system"] = "human"
    editor_external_subject: str | None = Field(default=None, max_length=512)


class BoardEditPostResponse(BaseModel):
    post_id: int
    revision: int
    changed: bool
    thread_id: int | None = None
    thread_version: int | None = None


class BoardSourcePostRevision(BaseModel):
    post_id: int
    revision: int


class BoardOrganizeRequest(BaseModel):
    summary: str = Field(min_length=1, max_length=20000)
    source_post_ids: list[int] = Field(min_length=1, max_length=200)
    expected_thread_version: int = Field(ge=1)
    author_display_name: str = Field(min_length=1, max_length=128)
    author_kind: Literal["human", "agent", "system"] = "agent"
    author_external_subject: str | None = Field(default=None, max_length=512)


class BoardOrganizeResponse(BaseModel):
    thread_id: int
    summary_post_id: int
    thread_version: int
    source_posts: list[BoardSourcePostRevision]


class BoardSearchItem(BaseModel):
    result_type: str
    id: int
    thread_id: int
    title: str
    body: str | None
    timestamp: str


class BoardSearchResponse(BaseModel):
    results: list[BoardSearchItem]
