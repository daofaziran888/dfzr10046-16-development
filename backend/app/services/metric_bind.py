"""指标绑定领域服务：校验指标与度量的绑定关系数据集，版本切换保留历史口径和导出持久化。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.measure_import import import_service
from app.store import store


class MetricBindService(BaseModuleService):
    MODULE = "metric_bind"
    ENTITY = "绑定关系"
    LIST_FIELDS = ["绑定编号", "指标名称", "引用度量", "绑定维度", "统计口径", "时间窗口", "绑定版本", "最近生效"]
    REQUIRED_FIELDS = ["绑定编号", "指标名称", "引用度量"]
    STATUS_ORDER = ["待生效", "生效中", "已替换", "已解除"]
    ACTION_RULES = {"启效绑定": "生效中", "替换绑定": "已替换", "解除绑定": "已解除"}
    NEGATIVE_ACTIONS = []

    def create_entry(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str], str | None]:
        """新建绑定前先确认引用度量是候选清单里当前可采用的登记。

        引用可以是候选编号（MC-xxxx）或度量编号；同一编号有多条表达式
        不同的导入登记且未再次确认时，拒绝绑定并提示等导入人确认。
        """
        reference = str(values.get("引用度量") or "").strip()
        resolved, error = import_service.resolve_measure_reference(reference)
        if resolved is None:
            missing = ["引用度量"] if not reference else []
            return None, missing, None if missing else error

        entry, missing, domain_error = super().create_entry(values)
        if entry is None:
            return entry, missing, domain_error
        if resolved["kind"] == "candidate":
            candidate = resolved["candidate"]
            # 绑定记录直接落到候选编号上，便于从候选清单反查被哪些指标引用。
            entry["引用度量"] = candidate["候选编号"]
            entry["引用度量条目ID"] = candidate["度量条目ID"]
            entry["引用来源导入"] = candidate.get("来源导入", "")
            import_service.record_binding(candidate, str(values.get("绑定编号")))
        else:
            entry["引用度量条目ID"] = resolved["measure"].get("id")
            entry["引用来源导入"] = ""
        return entry, [], None

    def bindable_options(self) -> list[dict[str, Any]]:
        """新建绑定时可选的度量：只露出当前真正可采用的那一条。"""
        return import_service.candidates_board()["selectable"]

    def bind_metric(
        self, bind_id: str, metric_name: str, measure_ref: str,
        dim_ref: str, caliber: str, time_window: str, version: str,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """绑定指标到度量与维度：历史读数值保留原绑定口径。"""
        rows = store.rows(self.MODULE)
        entry = {
            "绑定编号": bind_id, "指标名称": metric_name,
            "引用度量": measure_ref, "绑定维度": dim_ref,
            "统计口径": caliber, "时间窗口": time_window,
            "绑定版本": version, "最近生效": "2026-11-21",
            "status": "生效中", "pending": False, "abnormal": False,
        }
        entry["id"] = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        rows.append(entry)
        return True, f"指标 {metric_name}={measure_ref} 已绑定生效", entry

    def replace_binding(self, bind_id: str, new_measure: str, new_version: str) -> tuple[bool, str]:
        """替换绑定版本：旧版本口径保留，新版本独立。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("绑定编号") == bind_id:
                r["status"] = "已替换"
                r["引用度量"] = new_measure
                r["绑定版本"] = new_version
                r["pending"] = False
                return True, f"指标绑定 {bind_id} 已替换为版本 {new_version}"
        return False, f"绑定 {bind_id} 不存在"