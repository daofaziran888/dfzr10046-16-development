"""度量目录导入确认与指标绑定候选路由。

固定路径必须注册在通用资源路由之前，否则 `/api/{module}/{entry_id}`
会先把 `binding-candidates` 当成整数条目 ID 接走。
"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException

from app.schemas import (
    ActionResult,
    ImportCommitPayload,
    ImportConfirmPayload,
    ImportPreviewPayload,
)
from app.services.measure_import import IMPORT_FIELDS, import_service

router = APIRouter(prefix="/api", tags=["度量导入确认"])


def _parse_csv(content: str) -> list[dict[str, str]]:
    text = content.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="登记表为空，缺少表头")
    headers = [name.strip() for name in reader.fieldnames]
    missing_headers = [field for field in IMPORT_FIELDS if field not in headers]
    if "度量编号" not in headers:
        raise HTTPException(
            status_code=400, detail="登记表缺少「度量编号」列，无法识别带编号的度量行")
    rows: list[dict[str, str]] = []
    for raw in reader:
        rows.append({
            key.strip(): (raw.get(key) or "").strip()
            for key in headers
            if raw.get(key) is not None
        })
    if not rows:
        raise HTTPException(status_code=400, detail="登记表没有数据行")
    return rows


@router.post("/measure_catalog/imports/preview", response_model=dict)
def preview_import(payload: ImportPreviewPayload) -> dict[str, Any]:
    """上传带编号的度量登记表，生成逐行预览（保留原行位置）。"""
    if payload.rows:
        rows = [dict(item) for item in payload.rows]
    elif payload.content is not None:
        rows = _parse_csv(payload.content)
    else:
        raise HTTPException(status_code=400, detail="请上传登记表内容")
    return import_service.preview(payload.filename, rows)


@router.get("/measure_catalog/imports/{import_id}", response_model=dict)
def read_import(import_id: str) -> dict[str, Any]:
    """断线恢复：读取本次导入实际保存过的行与仍可修改的范围。"""
    session = import_service.session_view(import_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"导入会话 {import_id} 不存在或已过期")
    return session


@router.post("/measure_catalog/imports/{import_id}/commit", response_model=dict)
def commit_import(import_id: str, payload: ImportCommitPayload) -> dict[str, Any]:
    session, error = import_service.commit(
        import_id, [item.model_dump() for item in payload.decisions])
    if session is None:
        raise HTTPException(status_code=404, detail=error)
    return session


@router.post("/measure_catalog/imports/{import_id}/confirm", response_model=ActionResult)
def confirm_import_row(import_id: str, payload: ImportConfirmPayload) -> ActionResult:
    session, message = import_service.confirm_candidate(import_id, payload.row_no)
    if session is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message)


@router.get("/measure_catalog/binding-candidates", response_model=dict)
def binding_candidates() -> dict[str, Any]:
    """指标绑定候选清单：按编号分组，给出当前可采用的候选。"""
    return import_service.candidates_board()


@router.get("/metric_bind/bindable-options", response_model=dict)
def bindable_options() -> dict[str, Any]:
    """指标绑定表单可选的引用度量：每个编号只露出当前可采用的一条。"""
    return {"items": import_service.candidates_board()["selectable"]}
