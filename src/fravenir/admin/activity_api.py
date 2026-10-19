"""Read-only timeline endpoint for the third admin surface."""

from datetime import datetime
from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, Request

from fravenir.admin.activity import ActivityPage, Category, get_activity

router = APIRouter()


@router.get("/activity", response_model=ActivityPage)
def activity(
    request: Request, category: Category = "all",
    q: Annotated[str, Query(max_length=200)] = "",
    start: datetime | None = None, end: datetime | None = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ActivityPage:
    try:
        return get_activity(cast(Path, request.app.state.kv_path), category=category,
                            query=q, start=start, end=end, cursor=cursor, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
