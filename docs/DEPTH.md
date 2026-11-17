# 深度登记 航班时刻运行台

- 规模：中型
- 核心规则：用机场 IANA 时区解析 DST 重叠与跳时，所有航链在 UTC 上校验先后和衔接。
- 使用者与工作流：运行数据员导入航段，确认机场时区，处理当地时刻歧义，构建 UTC 航链并核对转机。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 航段采信 | 导入航段并隔离重复冲突 | POST /api/legs/import | `app/modules/m1_legs/parser.py` `app/modules/m1_legs/keys.py` | `tests/test_m1_legs.py` |
| M2 机场时区 | 查询日期对应的时区版本 | POST /api/airports | `app/modules/m2_airports/registry.py` `app/modules/m2_airports/contracts.py` | `tests/test_m2_airports.py` |
| M3 当地时刻 | 解析偏移、重叠与跳时 | POST /api/local-time/resolve | `app/modules/m3_localtime/resolve.py` `app/modules/m3_localtime/evidence.py` | `tests/test_m3_localtime.py` |
| M4 UTC 航链 | 换算航段并校验先后顺序 | POST /api/itineraries/build | `app/modules/m4_itinerary/builder.py` `app/modules/m4_itinerary/validate.py` | `tests/test_m4_itinerary.py` |
| M5 衔接判定 | 核对航站楼换乘与等待 | POST /api/connections/check | `app/modules/m5_connections/rules.py` `app/modules/m5_connections/windows.py` | `tests/test_m5_connections.py` |
| M6 批次导出 | 核对航段守恒并导出时刻 | POST /api/reconcile | `app/modules/m6_batches/compare.py` `app/modules/m6_batches/exporter.py` | `tests/test_m6_batches.py` |
| M7 批次撤销 | 预演、裁决、断点执行并按航段来源切换 | POST /api/revocations/batches/{id}/preview | `app/modules/m7_revocation/preview.py` `app/modules/m7_revocation/executor.py` `app/modules/m7_revocation/ledger.py` | `tests/test_m7_revocation.py` `tests/test_revocation_http.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-03 | 尾行记录不完整 | 半条航段进入换算 | 完整边界检查后隔离 | `app/modules/m1_legs/parser.py` | `tests/test_m1_legs.py::test_truncated_tail_detected` |
| TRAP-05 | 必填时刻缺失 | 空时间在深层报错 | 采信阶段给原因码和行号 | `app/modules/m1_legs/parser.py` | `tests/test_m1_legs.py::test_missing_time_quarantined` |
| TRAP-07 | 空当地时刻 | 被转换成午夜 | 空值不参与航链 | `app/modules/m1_legs/parser.py` | `tests/test_m1_legs.py::test_missing_time_quarantined` |
| TRAP-09 | 超大外部行程号 | JSON 数字往返丢精度 | 始终按字符串保形 | `app/modules/m1_legs/keys.py` | `tests/test_m1_legs.py::test_external_id_keeps_large_digits` |
| TRAP-11 | 偏移与 Z 混用 | 同一时刻先后次序错误 | 统一到 UTC 后输出 Z | `app/modules/m3_localtime/resolve.py` | `tests/test_m3_localtime.py::test_utc_serializes_with_z` |
| TRAP-12 | DST 重叠与跳时 | 重复小时覆盖或虚构时刻 | 往返验证并显式 fold | `app/modules/m3_localtime/resolve.py` | `tests/test_m3_localtime.py::test_dst_overlap_has_two_candidates` |
| TRAP-13 | 航段乱序 | 输入顺序被当成航程顺序 | 按 UTC 起飞时刻稳定排序 | `app/modules/m4_itinerary/builder.py` | `tests/test_m4_itinerary.py::test_order_by_utc_is_stable` |
| TRAP-14 | 同航段时刻冲突 | 后写覆盖原计划 | 冲突版本进入隔离区 | `app/modules/m1_legs/parser.py` | `tests/test_m1_legs.py::test_conflicting_duplicate_detected` |
| TRAP-23 | 衔接窗口端点 | 结束时刻被重复计入 | 使用半开区间 | `app/modules/m5_connections/windows.py` | `tests/test_m5_connections.py::test_half_open_window_excludes_end` |
| TRAP-25 | 时区版本重叠 | 随机选中一版偏移 | 多个生效版本立即拒绝 | `app/modules/m2_airports/registry.py` | `tests/test_m2_airports.py::test_overlapping_timezone_versions_rejected` |
| TRAP-26 | 误导入批次需要撤销 | 整库回退丢新数据，全部重放带回污染 | 按来源撤销并保留后续独立航段 | `app/modules/m7_revocation/preview.py` | `tests/test_m7_revocation.py::test_execute_removes_source_and_keeps_later_independent_leg` |
| TRAP-27 | 后批改过同一航段 | 按时间戳强选一版 | 两版待裁决，未裁决拒绝执行 | `app/modules/m7_revocation/executor.py` | `tests/test_m7_revocation.py::test_execute_blocked_until_adjudicated` |
| TRAP-28 | 预演后又有新导入 | 用过期预演覆盖新数据 | 预演带代次与摘要，失配即拒绝 | `app/modules/m7_revocation/preview.py` | `tests/test_revocation_http.py::test_stale_preview_error_shape` |
| TRAP-29 | 执行中途中断 | 重跑重复撤销或漏撤销 | 游标随每条动作提交，重试幂等续跑 | `app/modules/m7_revocation/executor.py` | `tests/test_m7_revocation.py::test_interrupted_job_resumes_without_double_revoke` |
| TRAP-30 | 恢复期间旧航链仍要用 | 直接覆盖当前代次 | staging 代次构建后原子切换 | `app/modules/m7_revocation/executor.py` | `tests/test_revocation_http.py::test_chain_readable_for_base_generation_during_recovery` |

## 对账规则

- 输入航段 = 有效航段 + 冲突航段 + 隔离航段。
- 行程航段 = 可衔接航段 + 不可衔接航段。
- 到达 UTC 必须晚于起飞 UTC，飞行时长不得超过 18 小时。
- 撤销对账：撤销后 = 撤销前 − 移除 + 恢复；不得新增业务键，且每个改动键可追溯到被撤销批次或待裁决候选。

## 已知不覆盖

- 不计算天气和空管延误，输入只描述计划时刻。
- 不扩展出票与赔付；撤销只影响航段与航链，不改时区解析规则。

