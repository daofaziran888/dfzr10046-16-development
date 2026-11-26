# 维链工坊 · 维度建模与缓慢变化维加工平台

面向维度注册、缓慢变化维拉链、一致性维度核对、事实表装配、代理键生成、维度退化、迟到事实回补、汇总层派生、指标口径绑定与维度快照发布的数仓维度建模加工平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8003/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5176/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8003`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 维度建档 | `dim_entry` | 维度条目 | 维度编号、维度名称、业务主键 |
| 拉链加工 | `scd_chain` | 拉链记录 | 拉链编号、所属维度、代理键 |
| 代理键生成 | `surrogate_key` | 代理键段 | 键段编号、所属维度、键段起点 |
| 一致性核对 | `conform_check` | 核对条目 | 核对编号、基准维度、对照维度 |
| 事实装配 | `fact_assemble` | 事实批次 | 批次编号、所属事实表、度量列集合 |
| 退化维度 | `degenerate_dim` | 退化维条目 | 条目编号、所属事实表、退化字段 |
| 迟到事实 | `late_fact` | 迟到记录 | 记录编号、所属事实表、业务发生日 |
| 汇总层派生 | `summary_layer` | 汇总条目 | 汇总编号、来源事实表、汇总粒度 |
| 粒度声明 | `grain_declare` | 粒度声明 | 声明编号、所属事实表、一行代表 |
| 度量目录 | `measure_catalog` | 度量条目 | 度量编号、度量名称、计算表达式 |
| 指标绑定 | `metric_bind` | 绑定关系 | 绑定编号、指标名称、引用度量 |
| 维度快照 | `dim_snapshot` | 快照版本 | 快照编号、所属维度、快照日期 |
| 层级路径 | `hier_path` | 层级路径 | 路径编号、所属维度、层级名称 |
| 多值桥接 | `bridge_link` | 桥接条目 | 桥接编号、所属事实表、关联维度 |
| 属性失效 | `attr_decay` | 失效条目 | 失效编号、所属维度、属性名称 |
| 装载窗口 | `load_window` | 装载窗口 | 窗口编号、所属事实表、窗口起点 |
| 重跑任务 | `reprocess_task` | 重跑任务 | 重跑编号、触发原因、影响事实表 |
| 装配质量闸 | `quality_gate` | 质量闸条目 | 闸口编号、所属事实表、校验项 |
| 血缘关系 | `lineage_edge` | 血缘边 | 血缘编号、上游对象、下游对象 |
| 维度发布 | `dim_publish` | 发布版本 | 发布编号、所属维度、发布版本 |
| 建模审计 | `model_audit` | 审计条目 | 条目编号、操作类型、操作对象 |
| 源端抽取 | `src_extract` | 抽取批次 | 抽取编号、来源系统、抽取范围 |

## 度量目录导入确认

度量目录多了一个「导入度量登记表」入口，把外部带编号的度量表从浏览器导进来；
指标绑定页多了一个「查看指标绑定候选」入口，用来选真正登记成功的度量。

- 上传 CSV（或直接粘贴）后先生成逐行预览，行号沿用文件原顺序；同一编号在
  文件里重复出现时，两行都留在原位并互相标注对方行号。表达式不同的重复行会
  标记为「需再次确认」。
- 每行可选择「新增 / 略过 / 待修」。缺必填字段或选「待修」的行留在待修区，
  可以改完再提交；已保存的行重复提交不会二次登记。
- 提交时如果某编号在预览后被同事抢先登记，该行进入「冲突」分组，不写入度量
  目录，与已保存的行分开展示。
- 真正保存成功的行同时写入指标绑定候选清单（`MC-xxxx`），记录来源导入、来源
  文件、来源行号和度量条目 ID。断线重连后打开导入弹窗会按导入会话恢复，
  只读实际保存过的行，不依赖本地选择。
- 同一编号有多条表达式不同的候选时，指标绑定列表不会露出其中任何一条，接口
  也会拒绝直接绑定；导入人在候选清单里点一行「确认采用」后，该候选成为唯一可
  绑定项，其余同编号候选转为「已让位」。绑定记录里保留候选编号、度量条目 ID
  和来源导入，可反查被哪些指标引用。

接口：

```text
POST /api/measure_catalog/imports/preview      预览（content 为 CSV 原文，或 rows 结构化行）
GET  /api/measure_catalog/imports/{id}         断线恢复 / 核对已保存行
POST /api/measure_catalog/imports/{id}/commit  提交逐行决策
POST /api/measure_catalog/imports/{id}/confirm 导入人再次确认某行候选
GET  /api/measure_catalog/binding-candidates   指标绑定候选清单
GET  /api/metric_bind/bindable-options         新建绑定可选的引用度量
```

`backend/tests/test_measure_import.py` 用四行数据覆盖整条链路（两条同编号不同
表达式的行、一条缺字段、一条预览后被抢先登记）。

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数仓与数据湖
