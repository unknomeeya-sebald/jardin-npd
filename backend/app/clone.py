"""일정관리 화면: jardin-npd.pages.dev/nb 원본 HTML을 그대로 내려준다.

원본은 Cloudflare Access 뒤에 있던 내부 자료라, 정적 파일(public)로 두지 않고
로그인한 사람에게만 이 API로 준다. 파일: data/clone/npd_schedule.html (2026-11-10 복제)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .auth import current_user

CLONE_DIR = Path(__file__).resolve().parent.parent / "data" / "clone"
NPD_SCHEDULE = CLONE_DIR / "npd_schedule.html"

router = APIRouter(prefix="/api/clone", tags=["clone"], dependencies=[Depends(current_user)])


@router.get("/npd-schedule")
def npd_schedule():
    if not NPD_SCHEDULE.is_file():
        raise HTTPException(404, "일정관리 원본 파일이 없습니다 (backend/data/clone/npd_schedule.html)")
    return FileResponse(NPD_SCHEDULE, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})
