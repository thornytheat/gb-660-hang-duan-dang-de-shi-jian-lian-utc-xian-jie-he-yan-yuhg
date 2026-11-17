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

## 运行规则

同一输入内容生成相同运行标识，重复执行复用已有批次。隔离记录包含原因码、原始行号与原值；业务导出只保留一份证据清单。

