"""度量目录导入确认链路测试：预览、提交、冲突分离、断线恢复与指标绑定。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.measure_import import import_service
from app.store import store


@pytest.fixture()
def client() -> TestClient:
    # 每个用例重置导入会话、候选清单和度量/绑定表，避免用例之间互相污染。
    import_service._sessions.clear()
    import_service._candidates.clear()
    import_service._session_seq = 0
    import_service._candidate_seq = 0
    catalog = store.rows("measure_catalog")
    bindings = store.rows("metric_bind")
    catalog_snapshot = [dict(row) for row in catalog]
    binding_snapshot = [dict(row) for row in bindings]
    yield TestClient(app)
    catalog[:] = catalog_snapshot
    bindings[:] = binding_snapshot


def make_row(code: str, name: str, expression: str) -> dict[str, str]:
    return {
        "度量编号": code, "度量名称": name, "计算表达式": expression,
        "聚合方式": "SUM", "单位声明": "元", "精度位数": "2",
        "适用粒度": "日_客户级", "目录版本": "v1",
    }


def four_rows() -> list[dict[str, str]]:
    """两行同编号不同表达式、一行缺表达式、一行稍后被同事抢先登记。"""
    return [
        make_row("MSR-T900", "净销售额A", "SUM(sale_amount - refund)"),
        make_row("MSR-T901", "毛利", "SUM(gross_profit)"),
        make_row("MSR-T900", "净销售额B", "SUM(sale_amount) - SUM(refund)"),
        make_row("MSR-T902", "待补表达式", ""),
    ]


def preview(client: TestClient, rows: list[dict[str, str]], filename: str = "四行.csv"):
    response = client.post(
        "/api/measure_catalog/imports/preview",
        json={"filename": filename, "rows": rows},
    )
    assert response.status_code == 200
    return response.json()


def commit(client: TestClient, import_id: str, decisions: dict[int, str]):
    response = client.post(
        f"/api/measure_catalog/imports/{import_id}/commit",
        json={"decisions": [
            {"row_no": row_no, "decision": decision}
            for row_no, decision in decisions.items()
        ]},
    )
    assert response.status_code == 200
    return response.json()


def test_preview_keeps_original_row_order_and_marks_duplicates(client: TestClient):
    session = preview(client, four_rows())
    rows = session["rows"]
    assert [row["row_no"] for row in rows] == [1, 2, 3, 4]
    assert [row["values"]["度量编号"] for row in rows] == [
        "MSR-T900", "MSR-T901", "MSR-T900", "MSR-T902",
    ]
    duplicate_a, duplicate_b = rows[0], rows[2]
    assert duplicate_a["duplicate_in_file"] and duplicate_b["duplicate_in_file"]
    assert duplicate_a["duplicate_positions"] == [3]
    assert duplicate_b["duplicate_positions"] == [1]
    assert duplicate_a["conflict_in_file"] and duplicate_b["conflict_in_file"]
    assert rows[3]["decision"] == "待修"
    assert any(issue["code"] == "missing" for issue in rows[3]["issues"])


def test_preview_accepts_csv_content_with_bom(client: TestClient):
    content = (
        "﻿度量编号,度量名称,计算表达式,聚合方式,单位声明,精度位数,适用粒度,目录版本\n"
        "MSR-C900,净额,\"SUM(a - b, c)\",SUM,元,2,日_客户级,v1\n"
    )
    response = client.post(
        "/api/measure_catalog/imports/preview",
        json={"filename": "bom.csv", "content": content},
    )
    assert response.status_code == 200
    row = response.json()["rows"][0]
    assert row["values"]["度量编号"] == "MSR-C900"
    assert row["values"]["计算表达式"] == "SUM(a - b, c)"


def test_commit_separates_preempted_row_from_saved_rows(client: TestClient):
    session = preview(client, four_rows())
    # 同事在预览后、提交前抢先登记同编号的不同表达式。
    from app.services.measure_catalog import MeasureCatalogService
    MeasureCatalogService().create_entry(make_row("MSR-T901", "同事的毛利", "SUM(x)"))

    result = commit(client, session["import_id"], {1: "新增", 2: "新增", 3: "新增", 4: "新增"})
    statuses = {row["row_no"]: row["result_status"] for row in result["rows"]}
    assert statuses[1] == "已保存"
    assert statuses[3] == "已保存"
    assert statuses[2] == "冲突"
    assert statuses[4] == "待修"
    assert result["verified_saved_row_nos"] == [1, 3]
    assert [row["row_no"] for row in result["conflict_rows"]] == [2]
    assert "预览后被其他登记抢先写入" in result["conflict_rows"][0]["message"]
    assert 2 in result["editable_row_nos"]


def test_recommit_is_idempotent_and_recovery_reads_saved_rows(client: TestClient):
    session = preview(client, four_rows())
    import_id = session["import_id"]
    first = commit(client, import_id, {1: "新增", 2: "新增", 3: "新增", 4: "待修"})
    before = len(store.rows("measure_catalog"))
    second = commit(client, import_id, {1: "新增", 2: "新增", 3: "新增", 4: "待修"})
    assert len(store.rows("measure_catalog")) == before
    assert second["verified_saved_row_nos"] == first["verified_saved_row_nos"] == [1, 2, 3]

    recovered = client.get(f"/api/measure_catalog/imports/{import_id}").json()
    assert recovered["import_id"] == import_id
    assert recovered["verified_saved_row_nos"] == [1, 2, 3]
    assert recovered["editable_row_nos"] == [4]
    assert recovered["counts"]["saved"] == 3


def test_duplicate_code_requires_reconfirm_then_binds(client: TestClient):
    session = preview(client, four_rows())
    import_id = session["import_id"]
    result = commit(client, import_id, {1: "新增", 2: "略过", 3: "新增", 4: "待修"})
    assert result["verified_saved_row_nos"] == [1, 3]

    board = client.get("/api/measure_catalog/binding-candidates").json()
    group = next(item for item in board["groups"] if item["度量编号"] == "MSR-T900")
    assert group["needs_reconfirm"] is True
    assert group["adoptable"] is None
    # 未确认前不暴露可选值，也不能直接绑定。
    assert all(item["度量编号"] != "MSR-T900" for item in board["selectable"])
    denied = client.post("/api/metric_bind", json={"values": {
        "绑定编号": "BND-T900", "指标名称": "净销售", "引用度量": "MSR-T900",
    }}).json()
    assert denied["ok"] is False
    assert "需导入人再次确认" in denied["message"]

    confirmed = client.post(
        f"/api/measure_catalog/imports/{import_id}/confirm", json={"row_no": 3},
    ).json()
    assert confirmed["ok"] is True

    board = client.get("/api/measure_catalog/binding-candidates").json()
    group = next(item for item in board["groups"] if item["度量编号"] == "MSR-T900")
    assert group["needs_reconfirm"] is False
    assert group["adoptable"]["候选编号"] == "MC-0002"
    assert group["adoptable"]["来源行号"] == 3
    yielded = next(item for item in group["candidates"] if item["来源行号"] == 1)
    assert yielded["状态"] == "已让位" and not yielded["可绑定"]

    options = client.get("/api/metric_bind/bindable-options").json()["items"]
    t900 = [item for item in options if item["度量编号"] == "MSR-T900"]
    assert len(t900) == 1 and t900[0]["候选编号"] == "MC-0002"

    first = client.post("/api/metric_bind", json={"values": {
        "绑定编号": "BND-T901", "指标名称": "净销售", "引用度量": "MSR-T900",
    }}).json()
    assert first["ok"] is True
    assert first["entry"]["引用度量"] == "MC-0002"

    second = client.post("/api/metric_bind", json={"values": {
        "绑定编号": "BND-T902", "指标名称": "净销售(候选)", "引用度量": "MC-0002",
    }}).json()
    assert second["ok"] is True
    assert second["entry"]["引用度量条目ID"] == first["entry"]["引用度量条目ID"]

    board = client.get("/api/measure_catalog/binding-candidates").json()
    adoptable = next(item for item in board["groups"] if item["度量编号"] == "MSR-T900")["adoptable"]
    assert adoptable["绑定次数"] == 2
    assert set(adoptable["绑定编号"]) == {"BND-T901", "BND-T902"}


def test_binding_rejects_unregistered_measure(client: TestClient):
    result = client.post("/api/metric_bind", json={"values": {
        "绑定编号": "BND-T910", "指标名称": "空引用", "引用度量": "MSR-NOPE",
    }}).json()
    assert result["ok"] is False
    assert "尚未真正登记成功" in result["message"]


def test_repair_row_can_be_fixed_and_resubmitted(client: TestClient):
    session = preview(client, four_rows())
    import_id = session["import_id"]
    commit(client, import_id, {1: "略过", 2: "略过", 3: "略过", 4: "待修"})
    fixed = commit(client, import_id, {4: "新增"})
    row_four = next(row for row in fixed["rows"] if row["row_no"] == 4)
    assert row_four["result_status"] == "待修"

    response = client.post(
        f"/api/measure_catalog/imports/{import_id}/commit",
        json={"decisions": [{
            "row_no": 4, "decision": "新增",
            "values": {"计算表达式": "SUM(repair_value)"},
        }]},
    )
    assert response.status_code == 200
    row_four = next(row for row in response.json()["rows"] if row["row_no"] == 4)
    assert row_four["result_status"] == "已保存"
    assert row_four["values"]["计算表达式"] == "SUM(repair_value)"
