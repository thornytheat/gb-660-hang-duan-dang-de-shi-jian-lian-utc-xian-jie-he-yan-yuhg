# 航班时刻运行台

面向真实数据复核的中型数据工程工具，包含六个可独立调用的业务模块。规则、失败原因与证据字段见 docs/DATA-DICTIONARY.md，陷阱和测试映射见 docs/DEPTH.md。

## 启动

docker compose up --build

浏览器访问 http://localhost:18219。测试：docker compose exec -T app pytest -q

## 模块

- M1 航段采信：页面 /legs，接口 /api/legs/import
- M2 机场时区：页面 /airports，接口 /api/airports
- M3 当地时刻：页面 /local-time，接口 /api/local-time/resolve
- M4 UTC 航链：页面 /itineraries，接口 /api/itineraries/build
- M5 衔接判定：页面 /connections，接口 /api/connections/check
- M6 批次导出：页面 /batches，接口 /api/reconcile
- M7 批次撤销：页面 /revocations，接口 /api/revocations

## 批次撤销

误导入批次通过来源撤回，不影响后续批次确认的独立航段。

1. `POST /api/legs/import` 接受真实 CSV（`content-type: text/csv`）或 JSON `{"rows": [...]}` / `{"csv": "..."}`，按物理行号落库并保留隔离证据。
2. `POST /api/revocations/batches/{batch_id}/preview` 生成预演：逐航段判定 `REVOKE`、`RESTORE`、`RETAIN` 或 `ADJUDICATE`，并记录代次、导入代数与数据集摘要。
3. `GET /api/revocations/adjudications?batch_id=…` 查看两版并存的待裁决项；`POST /api/revocations/adjudications/{id}/resolve` 以 `KEEP_SOURCE`、`KEEP_LATER`、`DEFER` 裁决。
4. `POST /api/revocations/previews/{preview_id}/execute` 执行；中断后 `POST /api/revocations/jobs/{job_id}/retry` 从断点续跑且不重复撤销。
5. `GET /api/revocations/jobs/{job_id}` 回读撤销、恢复、保留、待裁决航段与守恒差异；`GET /api/revocations/chain?generation=…` 可读切换前的旧航链。

预演后有新导入，执行会返回 `PREVIEW_STALE` 并要求重新预演。撤销在独立代次中构建，完成后一次性原子切换并重算 UTC 航链与衔接。

## 运行规则

同一输入内容生成相同运行标识，重复执行复用已有批次。隔离记录包含原因码、原始行号与原值；业务导出只保留一份证据清单。

