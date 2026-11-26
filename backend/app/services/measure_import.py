"""度量目录 · 浏览器导入确认领域服务。

业务管理员把带编号的外部度量登记表从浏览器上传后，先在这里生成一份
逐行预览（保留文件里的原行位置），再按行选择「新增 / 略过 / 保留待修」提交。

导入结果分两层落库：
1. 真正新增成功的行写入 `measure_catalog`，度量条目可以马上被指标绑定引用；
2. 每一行登记结果同时写入「指标绑定候选清单」，记录来源导入、来源行号、
   度量条目 ID 和可绑定状态。指标绑定只认候选清单里当前可采用的条目，
   同一编号被重复登记且表达式不同时，必须由导入人再次确认，不能靠猜。

页面断线重连后通过会话读取「实际保存过哪些行」，而不是重放本地决策。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.measure_catalog import MeasureCatalogService
from app.store import store

IMPORT_FIELDS: list[str] = list(MeasureCatalogService.LIST_FIELDS)
REQUIRED_FIELDS: list[str] = list(MeasureCatalogService.REQUIRED_FIELDS)
DECISIONS = ("新增", "略过", "待修")

STATUS_PENDING = "待确认"
STATUS_SAVED = "已保存"
STATUS_CONFLICT = "冲突"
STATUS_SKIPPED = "略过"
STATUS_REPAIR = "待修"

CANDIDATE_ADOPTABLE = "可绑定"
CANDIDATE_CONFIRMED = "已确认"
CANDIDATE_REVIEW = "需复核"
CANDIDATE_YIELDED = "已让位"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm(expression: Any) -> str:
    return " ".join(str(expression or "").split()).casefold()


class MeasureImportService:
    """维护导入会话和指标绑定候选清单。"""

    MODULE = "measure_catalog"

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._candidates: list[dict[str, Any]] = []
        self._session_seq = 0
        self._candidate_seq = 0

    # ------------------------------------------------------------------ 预览
    def preview(self, filename: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """生成导入预览：行顺序即文件顺序，重复编号留在原行位置。"""
        self._session_seq += 1
        import_id = f"IMP-{datetime.now():%Y%m%d}-{self._session_seq:03d}"
        clean_rows: list[dict[str, Any]] = []
        for index, raw in enumerate(rows, start=1):
            raw_values = raw.get("values") if isinstance(raw, dict) else None
            raw_values = raw_values or raw or {}
            values = {
                field: str(raw_values.get(field, "") or "").strip()
                for field in IMPORT_FIELDS
            }
            clean_rows.append({
                "row_no": index,
                "source_line": index,
                "values": values,
                "issues": [],
                "duplicate_in_file": False,
                "duplicate_positions": [],
                "conflict_in_file": False,
                "duplicate_existing": False,
                "existing_count": 0,
                "existing_ids_at_preview": [],
                "decision": "新增",
                "result_status": STATUS_PENDING,
                "editable": True,
                "message": "",
                "measure_id": None,
                "candidate_id": None,
                "decided_at": "",
                "saved_at": "",
            })

        # 同文件重复：按编号分组，保留每行原行号，组内互相记录对方位置。
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in clean_rows:
            code = row["values"]["度量编号"]
            if code:
                groups.setdefault(code, []).append(row)
        for code, members in groups.items():
            if len(members) > 1:
                expressions = {_norm(member["values"]["计算表达式"]) for member in members}
                for member in members:
                    member["duplicate_in_file"] = True
                    member["duplicate_positions"] = [
                        other["row_no"] for other in members if other is not member
                    ]
                    member["conflict_in_file"] = len(expressions) > 1
                    if len(expressions) > 1:
                        member["issues"].append({
                            "field": "计算表达式",
                            "code": "duplicate_conflict",
                            "message": (
                                f"编号 {code} 在文件第 "
                                f"{'、'.join(str(n) for n in [m['row_no'] for m in members])} "
                                "行重复登记且计算表达式不同"
                            ),
                        })

        for row in clean_rows:
            missing = [
                field for field in REQUIRED_FIELDS
                if not row["values"].get(field, "").strip()
            ]
            for field in missing:
                row["issues"].append({
                    "field": field,
                    "code": "missing",
                    "message": f"缺少必填字段：{field}",
                })
            if missing:
                row["decision"] = "待修"
            code = row["values"]["度量编号"]
            if code:
                existing = [
                    item for item in store.rows("measure_catalog")
                    if item.get("度量编号") == code
                ]
                row["existing_count"] = len(existing)
                row["existing_ids_at_preview"] = [int(item.get("id", 0)) for item in existing]
                if existing:
                    row["duplicate_existing"] = True
                    row["issues"].append({
                        "field": "度量编号",
                        "code": "duplicate_existing",
                        "message": (
                            f"编号 {code} 在预览时已有 "
                            f"{len(existing)} 条登记记录"
                        ),
                    })

        session = {
            "import_id": import_id,
            "filename": filename or "未命名登记表",
            "created_at": _now(),
            "updated_at": _now(),
            "rows": clean_rows,
        }
        self._sessions[import_id] = session
        return self.session_view(import_id) or {}

    # ------------------------------------------------------------------ 提交
    def commit(
        self, import_id: str, decisions: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """按行提交导入决策；已保存的行不会重复登记，可安全重试。"""
        session = self._sessions.get(import_id)
        if session is None:
            return None, f"导入会话 {import_id} 不存在或已过期"

        by_row = {int(item["row_no"]): item for item in session["rows"]}
        decision_map: dict[int, dict[str, Any]] = {}
        for item in decisions or []:
            row_no = int(item.get("row_no") or 0)
            decision = str(item.get("decision") or "").strip()
            if row_no not in by_row:
                return None, f"导入会话中没有第 {row_no} 行"
            if decision and decision not in DECISIONS:
                return None, f"第 {row_no} 行的决策「{decision}」不可用"
            decision_map[row_no] = item

        for row in session["rows"]:
            override = decision_map.get(row["row_no"])
            if row["result_status"] == STATUS_SAVED:
                # 已真正写进度量目录的行，重复提交不会再登记一次。
                continue
            if override is not None:
                values = override.get("values") or {}
                for field in IMPORT_FIELDS:
                    if field in values:
                        row["values"][field] = str(values.get(field) or "").strip()
                decision = str(override.get("decision") or row["decision"]).strip()
                if decision:
                    row["decision"] = decision
            self._apply_row(session, row)
            row["decided_at"] = _now()

        session["updated_at"] = _now()
        self._refresh_candidates()
        return self.session_view(import_id), ""

    def _apply_row(self, session: dict[str, Any], row: dict[str, Any]) -> None:
        """执行单行决策；异常留成可继续修改的行，不打断整批导入。"""
        decision = row["decision"] or "新增"
        values = row["values"]
        missing = [
            field for field in REQUIRED_FIELDS
            if not str(values.get(field, "")).strip()
        ]
        if decision == "略过":
            row["result_status"] = STATUS_SKIPPED
            row["editable"] = False
            row["message"] = "本行按略过处理，未写入度量目录"
            return
        if decision == "待修" or missing:
            row["result_status"] = STATUS_REPAIR
            row["editable"] = True
            row["message"] = (
                f"保留待修：缺少必填字段 {'、'.join(missing)}"
                if missing else "本行保留待修，修改后可再次提交"
            )
            return

        code = values["度量编号"]
        own_measure_ids = {
            int(item["measure_id"])
            for item in session["rows"]
            if item.get("measure_id")
        }
        external = [
            item for item in store.rows("measure_catalog")
            if item.get("度量编号") == code
            and int(item.get("id", 0)) not in own_measure_ids
        ]
        if external:
            row["result_status"] = STATUS_CONFLICT
            row["editable"] = True
            snapshot = set(row.get("existing_ids_at_preview") or [])
            preview_before = any(int(item.get("id", 0)) in snapshot for item in external)
            if preview_before:
                row["message"] = (
                    f"编号 {code} 在预览前已有登记记录，未覆盖，请修改编号后重试"
                )
            else:
                row["message"] = (
                    f"编号 {code} 在预览后被其他登记抢先写入"
                    f"（度量条目 {external[0].get('id')}），本行未保存"
                )
            return

        # 写入度量目录：与手工登记使用同一张表，指标绑定才能引用。
        catalog_rows = store.rows("measure_catalog")
        entry: dict[str, Any] = {
            "id": max((int(item.get("id", 0)) for item in catalog_rows), default=0) + 1,
        }
        entry.update({field: values[field] for field in IMPORT_FIELDS})
        entry["status"] = "已收录"
        entry["pending"] = False
        entry["abnormal"] = False
        entry["来源导入"] = session["import_id"]
        entry["导入行号"] = row["row_no"]
        catalog_rows.append(entry)

        candidate = self._new_candidate(session, row, entry)
        row["measure_id"] = entry["id"]
        row["candidate_id"] = candidate["候选编号"]
        row["result_status"] = STATUS_SAVED
        row["editable"] = False
        row["saved_at"] = _now()
        row["message"] = (
            f"已登记为度量条目 {entry['id']}，写入指标绑定候选 {candidate['候选编号']}"
        )

    def _new_candidate(
        self, session: dict[str, Any], row: dict[str, Any], entry: dict[str, Any],
    ) -> dict[str, Any]:
        self._candidate_seq += 1
        candidate = {
            "候选编号": f"MC-{self._candidate_seq:04d}",
            "度量编号": entry.get("度量编号"),
            "度量名称": entry.get("度量名称"),
            "计算表达式": entry.get("计算表达式"),
            "聚合方式": entry.get("聚合方式"),
            "单位声明": entry.get("单位声明"),
            "精度位数": entry.get("精度位数"),
            "适用粒度": entry.get("适用粒度"),
            "目录版本": entry.get("目录版本") or "v1",
            "来源导入": session["import_id"],
            "来源文件": session["filename"],
            "来源行号": row["row_no"],
            "度量条目ID": entry["id"],
            "状态": CANDIDATE_REVIEW,
            "确认采用": False,
            "绑定次数": 0,
            "绑定编号": [],
            "创建时间": _now(),
        }
        self._candidates.append(candidate)
        return candidate

    # ------------------------------------------------------------- 候选清单
    def _measure_alive(self, candidate: dict[str, Any]) -> bool:
        entry = store.find("measure_catalog", int(candidate.get("度量条目ID", 0)))
        if entry is None:
            return False
        return entry.get("status") != "已下线"

    def _group_registrations(self, code: str) -> list[dict[str, Any]]:
        """把某编号的有效登记合并成候选 + 未关联候选的直接登记。"""
        candidates = [
            item for item in self._candidates
            if item.get("度量编号") == code and self._measure_alive(item)
        ]
        candidate_measure_ids = {
            int(item.get("度量条目ID", 0)) for item in self._candidates
            if item.get("度量编号") == code
        }
        direct = [
            item for item in store.rows("measure_catalog")
            if item.get("度量编号") == code
            and item.get("status") != "已下线"
            and int(item.get("id", 0)) not in candidate_measure_ids
        ]
        return candidates, direct

    def _resolve_code(self, code: str) -> tuple[dict[str, Any] | None, str]:
        """解析某编号当前能采用的登记；多义时返回需要再次确认的说明。"""
        candidates, direct = self._group_registrations(code)
        live_candidates = [
            item for item in candidates if item.get("状态") != CANDIDATE_YIELDED
        ]
        registrations: list[dict[str, Any]] = []
        for item in live_candidates:
            registrations.append({"kind": "candidate", "candidate": item})
        for item in direct:
            registrations.append({"kind": "catalog", "measure": item})

        if not registrations:
            return None, f"度量编号 {code} 尚未真正登记成功，不能绑定"

        confirmed = [
            item for item in live_candidates if item.get("确认采用")
        ]
        if len(confirmed) == 1:
            return {"kind": "candidate", "candidate": confirmed[0]}, ""
        if len(confirmed) > 1:
            return None, f"度量编号 {code} 有多条已确认登记，请导入人只保留一条"

        if len(registrations) == 1:
            return registrations[0], ""

        expressions = {
            _norm(item.get("计算表达式"))
            for item in live_candidates
        } | {_norm(item.get("计算表达式")) for item in direct}
        if len(expressions) == 1:
            # 表达式相同的重复登记按最早行登记为准，其余标记让位。
            registrations.sort(
                key=lambda item: (
                    item["candidate"]["来源行号"] if item["kind"] == "candidate" else 10 ** 6
                )
            )
            return registrations[0], ""

        rows = [
            str(item["candidate"]["来源行号"])
            for item in registrations if item["kind"] == "candidate"
        ]
        where = f"（导入行 {'、'.join(rows)}）" if rows else ""
        return None, (
            f"度量编号 {code} 有 {len(registrations)} 条表达式不同的登记{where}，"
            "需导入人再次确认后才能绑定"
        )

    def resolve_measure_reference(
        self, reference: str,
    ) -> tuple[dict[str, Any] | None, str]:
        """把绑定表单里的引用（候选编号或度量编号）解析成唯一可采用的登记。"""
        reference = str(reference or "").strip()
        if not reference:
            return None, "缺少必填字段：引用度量"
        self._refresh_candidates()
        if reference.upper().startswith("MC-"):
            candidate = next(
                (item for item in self._candidates
                 if item.get("候选编号", "").upper() == reference.upper()),
                None,
            )
            if candidate is None:
                return None, f"候选编号 {reference} 不在指标绑定候选清单中"
            if not self._measure_alive(candidate):
                return None, f"候选 {reference} 对应的度量条目已不可用"
            if not candidate.get("可绑定"):
                return None, (
                    f"候选 {reference} 当前状态为「{candidate.get('状态')}」，"
                    f"{candidate.get('状态说明') or '不能用于指标绑定'}"
                )
            return {"kind": "candidate", "candidate": candidate}, ""
        return self._resolve_code(reference)

    def _refresh_candidates(self) -> None:
        """重算候选状态：确认优先、唯一可直接采用、其余进入复核或让位。"""
        codes = sorted({item.get("度量编号") for item in self._candidates if item.get("度量编号")})
        for code in codes:
            candidates, direct = self._group_registrations(code)
            live = [
                item for item in candidates if item.get("状态") != CANDIDATE_YIELDED
            ]
            confirmed = [item for item in live if item.get("确认采用")]
            expressions = {_norm(item.get("计算表达式")) for item in live} | {
                _norm(item.get("计算表达式")) for item in direct
            }
            winner: dict[str, Any] | None = None
            if len(confirmed) == 1:
                # 导入人再次确认的候选优先，哪怕目录里还有其他直登记录。
                winner = confirmed[0]
            elif confirmed:
                winner = None
            elif not direct and len(live) == 1:
                winner = live[0]
            elif not direct and len(live) > 1 and len(expressions) == 1:
                winner = sorted(live, key=lambda item: int(item.get("来源行号", 0)))[0]

            for item in candidates:
                if not self._measure_alive(item):
                    item["可绑定"] = False
                    item["状态"] = CANDIDATE_YIELDED
                    item["状态说明"] = "对应度量条目已下线或缺失"
                    continue
                if not confirmed and item.get("状态") == CANDIDATE_YIELDED:
                    # 之前因同编号更早登记而让位的行保持让位，不因重算又冒出来。
                    item["可绑定"] = False
                    continue
                if winner is item:
                    item["可绑定"] = True
                    item["状态"] = CANDIDATE_CONFIRMED if item.get("确认采用") else CANDIDATE_ADOPTABLE
                    item["状态说明"] = (
                        "导入人已再次确认，指标绑定可引用"
                        if item.get("确认采用")
                        else "当前编号唯一有效登记，指标绑定可引用"
                    )
                elif confirmed:
                    item["可绑定"] = False
                    item["状态"] = CANDIDATE_YIELDED
                    item["状态说明"] = f"导入人已确认同编号的其他候选，本条让位"
                elif len(expressions) > 1:
                    item["可绑定"] = False
                    item["状态"] = CANDIDATE_REVIEW
                    item["状态说明"] = "同一编号存在多条表达式不同的登记，等待导入人再次确认"
                else:
                    item["可绑定"] = False
                    item["状态"] = CANDIDATE_YIELDED
                    item["状态说明"] = "同编号已有更早的有效登记，本条让位"

    def confirm_candidate(
        self, import_id: str, row_no: int,
    ) -> tuple[dict[str, Any] | None, str]:
        """导入人再次确认：指定该行候选为唯一可采用登记，其余同编号让位。"""
        session = self._sessions.get(import_id)
        if session is None:
            return None, f"导入会话 {import_id} 不存在或已过期"
        row = next(
            (item for item in session["rows"] if item["row_no"] == row_no), None,
        )
        if row is None:
            return None, f"导入会话中没有第 {row_no} 行"
        if row["result_status"] != STATUS_SAVED or not row.get("candidate_id"):
            return None, f"第 {row_no} 行尚未登记成功，没有可确认的候选"
        candidate = next(
            (item for item in self._candidates
             if item["候选编号"] == row["candidate_id"]),
            None,
        )
        if candidate is None:
            return None, f"第 {row_no} 行的候选 {row['candidate_id']} 不存在"
        for item in self._candidates:
            if item.get("度量编号") != candidate.get("度量编号"):
                continue
            if item is candidate:
                item["确认采用"] = True
                continue
            # 让位而来的候选不能仅凭「未被确认」就恢复可选，要显式清掉让位标记。
            item["确认采用"] = False
            item["状态"] = CANDIDATE_REVIEW
            item["可绑定"] = False
            item["状态说明"] = "导入人已确认同编号的其他候选，本条让位"
        self._refresh_candidates()
        return self.session_view(import_id), (
            f"已确认第 {row_no} 行候选 {candidate['候选编号']} 为可绑定条目"
        )

    def candidates_board(self) -> dict[str, Any]:
        """指标绑定候选清单：按度量编号分组，给出当前可采用的候选。"""
        self._refresh_candidates()
        candidate_codes = sorted({
            item.get("度量编号") for item in self._candidates if item.get("度量编号")
        })
        groups: list[dict[str, Any]] = []
        for code in candidate_codes:
            resolved, error = self._resolve_code(code)
            members = [
                item for item in self._candidates if item.get("度量编号") == code
            ]
            members.sort(key=lambda item: (int(item.get("来源行号", 0)), item["候选编号"]))
            groups.append({
                "度量编号": code,
                "needs_reconfirm": resolved is None and bool(error),
                "message": error,
                "adoptable": self._candidate_view(resolved["candidate"])
                if resolved and resolved["kind"] == "candidate" else None,
                "candidates": [self._candidate_view(item) for item in members],
            })

        selectable: list[dict[str, Any]] = []
        all_codes = sorted({
            *(item.get("度量编号") for item in self._candidates if item.get("度量编号")),
            *(row.get("度量编号") for row in store.rows("measure_catalog")
              if row.get("status") != "已下线" and row.get("度量编号")),
        })
        for code in all_codes:
            resolved, _ = self._resolve_code(code)
            if resolved is None:
                continue
            if resolved["kind"] == "candidate":
                candidate = resolved["candidate"]
                selectable.append({
                    "value": candidate["候选编号"],
                    "候选编号": candidate["候选编号"],
                    "度量编号": code,
                    "label": (
                        f"{candidate['候选编号']} · {code} · "
                        f"{candidate.get('计算表达式', '')}"
                    ),
                    "计算表达式": candidate.get("计算表达式", ""),
                    "来源导入": candidate.get("来源导入", ""),
                })
            else:
                measure = resolved["measure"]
                selectable.append({
                    "value": code,
                    "候选编号": "",
                    "度量编号": code,
                    "label": f"{code} · {measure.get('计算表达式', '')}（目录直登）",
                    "计算表达式": measure.get("计算表达式", ""),
                    "来源导入": "",
                })

        return {
            "total": len(groups),
            "groups": groups,
            "selectable": selectable,
            "candidate_count": len(self._candidates),
        }

    def _candidate_view(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "候选编号": candidate["候选编号"],
            "度量编号": candidate.get("度量编号"),
            "度量名称": candidate.get("度量名称"),
            "计算表达式": candidate.get("计算表达式"),
            "来源导入": candidate.get("来源导入"),
            "来源文件": candidate.get("来源文件"),
            "来源行号": candidate.get("来源行号"),
            "度量条目ID": candidate.get("度量条目ID"),
            "状态": candidate.get("状态"),
            "状态说明": candidate.get("状态说明", ""),
            "可绑定": bool(candidate.get("可绑定")),
            "确认采用": bool(candidate.get("确认采用")),
            "绑定次数": candidate.get("绑定次数", 0),
            "绑定编号": list(candidate.get("绑定编号", [])),
        }

    def record_binding(self, candidate: dict[str, Any], binding_code: str) -> None:
        """指标绑定成功引用后回写候选来源，便于核对绑定与导入的对应关系。"""
        bindings = candidate.setdefault("绑定编号", [])
        if binding_code not in bindings:
            bindings.append(binding_code)
        candidate["绑定次数"] = len(bindings)

    # ------------------------------------------------------------- 会话恢复
    def session_view(self, import_id: str) -> dict[str, Any] | None:
        session = self._sessions.get(import_id)
        if session is None:
            return None
        self._refresh_candidates()
        rows: list[dict[str, Any]] = []
        for row in session["rows"]:
            view = {
                **row,
                "values": dict(row["values"]),
                "issues": list(row["issues"]),
                "candidate_status": "",
                "candidate_adoptable": False,
                "candidate_status_text": "",
            }
            if row.get("candidate_id"):
                candidate = next(
                    (item for item in self._candidates
                     if item["候选编号"] == row["candidate_id"]),
                    None,
                )
                if candidate is None:
                    view["result_status"] = STATUS_REPAIR
                    view["editable"] = True
                    view["message"] = "候选记录缺失，请重新提交本行"
                else:
                    view["candidate_status"] = candidate.get("状态", "")
                    view["candidate_adoptable"] = bool(candidate.get("可绑定"))
                    view["candidate_status_text"] = candidate.get("状态说明", "")
                    if row["result_status"] == STATUS_SAVED and not self._measure_alive(candidate):
                        view["result_status"] = STATUS_REPAIR
                        view["editable"] = True
                        view["message"] = "度量条目已下线或缺失，本行回到待修"
            rows.append(view)

        def group(status: str) -> list[dict[str, Any]]:
            return [row for row in rows if row["result_status"] == status]

        saved_rows = group(STATUS_SAVED)
        conflict_rows = group(STATUS_CONFLICT)
        skipped_rows = group(STATUS_SKIPPED)
        pending_rows = group(STATUS_REPAIR) + group(STATUS_PENDING)
        pending_rows.sort(key=lambda row: row["row_no"])
        editable_rows = [row for row in rows if row["editable"]]
        return {
            "import_id": session["import_id"],
            "filename": session["filename"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "rows": rows,
            "saved_rows": saved_rows,
            "conflict_rows": conflict_rows,
            "skipped_rows": skipped_rows,
            "pending_rows": pending_rows,
            "editable_row_nos": [row["row_no"] for row in editable_rows],
            "verified_saved_row_nos": [row["row_no"] for row in saved_rows],
            "counts": {
                "total": len(rows),
                "saved": len(saved_rows),
                "conflict": len(conflict_rows),
                "skipped": len(skipped_rows),
                "pending": len(pending_rows),
                "editable": len(editable_rows),
            },
        }


import_service = MeasureImportService()
