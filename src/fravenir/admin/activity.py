"""Read-only activity feed derived from stored facts, rather than inferred actions."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import sqlite3
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

Category = Literal["all", "board", "memory", "graph"]


class ActivityEvent(BaseModel):
    id: str
    occurred_at: str
    category: str
    action: str
    title: str
    preview: str
    context: str
    actor: str | None
    actor_kind: str | None
    target_type: str
    target_id: int
    thread_id: int | None
    space_id: int | None
    revision: int | None
    note: str | None


class ActivityPage(BaseModel):
    events: list[ActivityEvent]
    next_cursor: str | None
    has_more: bool
    as_of: str


def _utc(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat() if value.tzinfo is None else (
        value.astimezone(UTC).isoformat()
    )


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _feed_sql(conn: sqlite3.Connection) -> str:
    def alive(table: str, alias: str) -> str:
        columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        return f"{alias}.deleted_at IS NULL" if "deleted_at" in columns else "1=1"

    # A common visible-node model prevents deleted parents leaking through any event source.
    return f"""
    WITH vs AS (SELECT * FROM spaces s WHERE {alive('spaces', 's')}),
    vt AS (SELECT t.* FROM threads t JOIN vs s ON s.id=t.space_id
           WHERE {alive('threads', 't')}),
    vp AS (SELECT p.* FROM posts p JOIN vt t ON t.id=p.thread_id
           WHERE {alive('posts', 'p')}),
    nodes AS (
      SELECT 'episode' type,id,content label FROM episodes WHERE is_suppressed=0
      UNION ALL SELECT 'entity',id,canonical_name FROM entities
      UNION ALL SELECT 'thread',id,title FROM vt
      UNION ALL SELECT 'post',id,body FROM vp
    ),
    raw AS (
      SELECT 'post:'||p.id||':created' id,p.created_at occurred_at,'board' category,
        'post.created' action,t.title title,
        COALESCE((SELECT body FROM post_revisions WHERE post_id=p.id AND revision=1),
                 p.body) body,s.name||' / '||t.title context,a.display_name actor,
        a.kind actor_kind,'post' target_type,p.id target_id,p.thread_id,t.space_id,
        1 revision,CASE WHEN p.revision>1 AND NOT EXISTS(
          SELECT 1 FROM post_revisions WHERE post_id=p.id AND revision=1)
          THEN '初版の記録がないため現在の本文を表示' END note
      FROM vp p JOIN vt t ON t.id=p.thread_id JOIN vs s ON s.id=t.space_id
      LEFT JOIN actors a ON a.id=p.author_id
      UNION ALL
      SELECT 'post:'||p.id||':edit:'||(r.revision+1),r.edited_at,'board','post.edited',
        t.title,COALESCE((SELECT body FROM post_revisions
          WHERE post_id=p.id AND revision=r.revision+1),
          CASE WHEN p.revision=r.revision+1 THEN p.body END,''),
        s.name||' / '||t.title,a.display_name,a.kind,'post',p.id,p.thread_id,t.space_id,
        r.revision+1,CASE WHEN p.revision<>r.revision+1 AND NOT EXISTS(
          SELECT 1 FROM post_revisions WHERE post_id=p.id AND revision=r.revision+1)
          THEN '改訂後の本文の記録なし' END
      FROM post_revisions r JOIN vp p ON p.id=r.post_id
      JOIN vt t ON t.id=p.thread_id JOIN vs s ON s.id=t.space_id
      LEFT JOIN actors a ON a.id=r.editor_id
      UNION ALL
      SELECT 'thread:'||t.id||':created',t.created_at,'board','thread.created',t.title,
        '',s.name,a.display_name,a.kind,'thread',t.id,t.id,t.space_id,NULL,NULL
      FROM vt t JOIN vs s ON s.id=t.space_id LEFT JOIN actors a ON a.id=t.created_by
      UNION ALL
      SELECT 'space:'||s.id||':created',s.created_at,'board','space.created',s.name,
        COALESCE(s.description,''),'',NULL,NULL,'space',s.id,NULL,s.id,NULL,NULL FROM vs s
      UNION ALL
      SELECT 'episode:'||id||':created',created_at,'memory','episode.created',
        '記憶 #'||id,content,kind,NULL,NULL,'episode',id,NULL,NULL,NULL,NULL
      FROM episodes WHERE is_suppressed=0
      UNION ALL
      SELECT 'episode:'||id||':expired',valid_to,'memory','episode.expired',
        '記憶 #'||id,content,kind,NULL,NULL,'episode',id,NULL,NULL,NULL,NULL
      FROM episodes WHERE is_suppressed=0 AND valid_to IS NOT NULL
      UNION ALL
      SELECT 'entity:'||id||':created',created_at,'memory','entity.created',
        canonical_name,COALESCE(description,''),COALESCE(entity_type,''),NULL,NULL,
        'entity',id,NULL,NULL,NULL,'説明は現在の内容' FROM entities
      UNION ALL
      SELECT 'relation:'||r.id||':created',r.created_at,'graph','relation.created',
        r.predicate,COALESCE(r.description,''),
        substr(src.label,1,70)||' → '||substr(dst.label,1,70),NULL,NULL,
        'relation',r.id,NULL,NULL,NULL,
        r.src_type||':'||r.src_id||' → '||r.dst_type||':'||r.dst_id||
          ' · strength '||r.strength
      FROM relations r JOIN nodes src ON src.type=r.src_type AND src.id=r.src_id
      JOIN nodes dst ON dst.type=r.dst_type AND dst.id=r.dst_id
      UNION ALL
      SELECT 'relation:'||r.id||':expired',r.valid_to,'graph','relation.expired',
        r.predicate,COALESCE(r.description,''),
        substr(src.label,1,70)||' → '||substr(dst.label,1,70),NULL,NULL,
        'relation',r.id,NULL,NULL,NULL,
        r.src_type||':'||r.src_id||' → '||r.dst_type||':'||r.dst_id||
          ' · strength '||r.strength
      FROM relations r JOIN nodes src ON src.type=r.src_type AND src.id=r.src_id
      JOIN nodes dst ON dst.type=r.dst_type AND dst.id=r.dst_id WHERE r.valid_to IS NOT NULL
    ), events AS (SELECT *,julianday(occurred_at) stamp FROM raw)
    """


def get_activity(
    kv_path: Path, *, category: Category = "all", query: str = "",
    start: datetime | None = None, end: datetime | None = None,
    cursor: str | None = None, limit: int = 50,
) -> ActivityPage:
    if category not in ("all", "board", "memory", "graph") or not 1 <= limit <= 100:
        raise ValueError("Invalid activity category or limit")
    if len(query) > 200:
        raise ValueError("Activity query is too long")
    start_text, end_text = _utc(start) if start else None, _utc(end) if end else None
    if start_text and end_text and start_text >= end_text:
        raise ValueError("開始日時は終了日時より前にしてください")
    signature = hashlib.sha256(json.dumps(
        [category, _normalize(query).strip(), start_text, end_text]
    ).encode()).hexdigest()
    as_of = _utc(datetime.now(UTC))
    position: tuple[float, str] | None = None
    if cursor:
        try:
            if len(cursor) > 512:
                raise ValueError
            payload = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
            stamp, key = payload["stamp"], payload["id"]
            if (payload["v"] != 1 or payload["filter"] != signature
                    or not isinstance(stamp, (int, float)) or not math.isfinite(stamp)
                    or not isinstance(key, str) or not 1 <= len(key) <= 100):
                raise ValueError
            as_of = _utc(datetime.fromisoformat(payload["as_of"]))
            position = float(stamp), key
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise ValueError("無効なActivityカーソルです。更新して読み直してください") from exc

    conn = sqlite3.connect(f"{kv_path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.create_function("normalize", 1, _normalize, deterministic=True)
    try:
        conn.execute("BEGIN")
        sql = _feed_sql(conn)
        clauses = ["stamp IS NOT NULL", "stamp <= julianday(?)"]
        params: list[Any] = [as_of]
        if category != "all":
            clauses.append("category = ?")
            params.append(category)
        for boundary, op in ((start_text, ">="), (end_text, "<")):
            if boundary:
                clauses.append(f"stamp {op} julianday(?)")
                params.append(boundary)
        for token in _normalize(query).split():
            clauses.append("instr(normalize(title||' '||body||' '||context||' '||"
                           "COALESCE(actor,'')||' '||action),?) > 0")
            params.append(token)
        if position:
            clauses.append("(stamp < ? OR (stamp = ? AND id < ?))")
            params.extend((position[0], position[0], position[1]))
        rows = conn.execute(
            sql + " SELECT * FROM events WHERE " + " AND ".join(clauses)
            + " ORDER BY stamp DESC,id DESC LIMIT ?", (*params, limit + 1)
        ).fetchall()
        more = len(rows) > limit
        selected = rows[:limit]
        events = [ActivityEvent(
            **{k: row[k] for k in ActivityEvent.model_fields if k not in ("preview",)},
            preview=row["body"][:1200],
        ) for row in selected]
        # Normalize mixed legacy SQLite UTC strings and offset-bearing ISO times for browsers.
        for event in events:
            event.occurred_at = _utc(datetime.fromisoformat(event.occurred_at))
        next_cursor = None
        if more:
            last = selected[-1]
            next_cursor = base64.urlsafe_b64encode(json.dumps({
                "v": 1, "stamp": last["stamp"], "id": last["id"],
                "as_of": as_of, "filter": signature,
            }).encode()).decode()
        return ActivityPage(events=events, next_cursor=next_cursor, has_more=more, as_of=as_of)
    finally:
        conn.close()
