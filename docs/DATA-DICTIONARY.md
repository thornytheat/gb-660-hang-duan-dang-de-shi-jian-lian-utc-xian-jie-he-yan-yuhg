# 数据字典

- run_id：规则版本与输入 SHA-256 前 12 位组成的稳定批次标识。
- batch_id：落库批次标识，通常等于 run_id；同一内容在撤销后再次导入会得到 `~N` 后缀的新批次，避免把新来源并入旧批次。
- created_seq：批次落库序号，依赖排序只按它，不按时间戳。
- generation：数据集代次。每次导入或撤销都写入一个新代次，只有切换后才成为当前代次。
- dataset_digest：某一代次全部业务键与内容哈希的摘要，用于判断预演是否过期。
- import_seq：导入代数，任何新导入都会递增并使旧预演失效。
- line_no：从 1 开始的物理来源行号，不因隔离或排序改变。
- business_key：本项目声明的业务唯一键，始终按字符串存储。
- content_hash：航段业务内容的规范化哈希，用于识别版本变化。
- reason_code：隔离原因的稳定英文编码。
- accepted：进入业务计算的记录数。
- quarantined：保留证据但不参与业务计算的记录数。
- 数值：金额、税额、用量和权重使用 Decimal；对外序列化为字符串。
- 时间：存储为带偏移的 ISO 8601，分桶使用半开区间。
- 空值：缺失键、空串和业务哨兵分别记录。
- 幂等：完整输入字节与规则版本相同则复用 run_id，不新增结果。

## 批次撤销

- 预演（preview）：针对单个 batch_id 计算动作清单，记录 base_generation、import_seq、dataset_digest。
- 预演状态：`VALID` 可执行；`STALE` 因新导入或数据变更失效；`CONSUMED` 已被一次撤销消费。
- 动作：
  - `REVOKE`：该业务键当前生效版本正是误导入版本，撤销后在新区代中移除。
  - `RESTORE`：同一业务键存在更早的有效版本，撤销后恢复那一版。
  - `RETAIN`：该来源版本当前未生效（已被后批覆盖或已不活跃），无需改动。
  - `ADJUDICATE`：后续批次改动了同一业务键，两个版本都保留为候选，不按时间顺序强选。
- 裁决（adjudication）：
  - `KEEP_SOURCE`：恢复被撤销批次的版本。
  - `KEEP_LATER`：保留后续批次版本，需给出 chosen_leg_id。
  - `DEFER`：两版都留档，但该业务键不进入新区代，等待后续裁决。
  - 存在未裁决项时执行返回 `CONFLICTS_PENDING`。
- 执行（job）：`RUNNING` 可续跑；`DONE` 已原子切换；`SUPERSEDED` 因执行期间出现新导入或批次状态变化而作废。
- 断点：每处理一条即在同一事务内推进 cursor，重试从 cursor 继续；动作是“设置/移除业务键”的幂等操作，不会重复撤销。
- 原子切换：新代次在 staging_generation 内构建，唯一可见性开关是 meta.dataset_generation 的一次 UPDATE；切换前旧代次仍可读。
- 守恒差异：
  - `balanced`：撤销只能删除或替换既有业务键，不得引入新业务键。
  - `accounted`：所有被删除/替换的键都必须可追溯到被撤销批次或某条待裁决候选版本。
  - `removed_keys` / `changed_keys` / `added_keys`：逐键回读差异。
