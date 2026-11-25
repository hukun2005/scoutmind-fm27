# 真实 FM27 A/B 验收（人工执行）

- 状态：**REAL_FM27_ACCEPTANCE_PENDING**
- 原因：本次交付环境没有可验证的真实 FM27 游戏会话与两份真实存档。
- 原则：**没有人工执行与证据，不得写 PASS**；自动化脚本只能验证后端协议，不能替代本文件。

## 1. 环境记录（执行时填写）

| 项目 | 值 |
| --- | --- |
| 日期 | 待填 |
| 执行人 | 待填 |
| FM27 版本（来自 Reader `--diagnostics`） | 待填 |
| game_plugin.dll 版本 | 待填 |
| Reader 版本 | 待填 |
| Agent 版本 | 待填 |
| 后端 commit | 待填 |
| 数据库 | SQLite / PostgreSQL（待填） |
| 存档 A 指纹 | 待填 |
| 存档 B 指纹 | 待填 |

禁止猜测版本号；版本必须来自 Reader 的真实诊断输出。

## 2. 前置检查

```powershell
# 后端与 Agent 均可运行
python tools/runtime-acceptance/inspect_environment.ps1 -OutputDir docs/evidence/v3.2.7.4/runtime-manual
ScoutMind.Agent diagnostics --json
ScoutMind.Agent network status
ScoutMind.Agent status --json
```

要求：

- `diagnostics` 显示队列、上下文、最近任务均正常；
- `status` 显示 Reader 连接正常；
- `environment.json` 的 `fm27.process_detected=false` 时**停止**，不要继续伪造。

## 3. 场景 A：单存档正常采集

1. 进入存档 A，触发 `ScoutMind.Agent scan --sync` 或 `auto --interval-minutes 5`；
2. 预期：
   - 后端返回 `status=succeeded/partial`；
   - 审计出现 `session_created`、`write_accepted`、`worker_started`；
   - `SaveIdentityView` 的 Worker 卡片显示任务成功、`attempt_count=1`；
3. 截图与 `ScoutMind.Agent jobs inspect <scan_id>` 输出保存到 `runtime-manual/`。

## 4. 场景 B：A → B → A 切换

1. 在 A 中完成一次成功导入；
2. 关闭游戏，切换到存档 B，启动 Agent：
   - 预期旧会话 `invalidated`，审计 `save_switched` / `session_invalidated` / `session_created`；
   - B 的指纹与 A 不同，不得复用 A 的身份；
3. 在 B 中导入一次，预期 `succeeded`；
4. 切回 A，再导入：
   - 预期生成新代次，A 的旧会话不可写；
   - 审计出现新的 `session_created` 与 `write_accepted`；
5. 全程不得出现跨存档球员污染：用 `GET /saves/{id}/summary` 对比 A/B 的球员数。

判定：A/B 数据互不污染、旧会话写入 409、切换后新会话可写 → PASS；任一不满足 → FAIL。

## 5. 场景 C：断网恢复

1. 在 Agent 运行中临时断网（拔网线或禁用网卡）；
2. 观察 Agent：不崩溃、不刷屏，任务留在队列；
3. 恢复网络，等待下一次心跳：
   - 预期后端审计 `network_reconnected`；
   - 任务以**原 operation_id** 上传；
   - 若服务端其实已导入，返回 `duplicate=true`，不产生重复数据；
4. `SaveIdentityView` 的「断网重连」计数增加。

## 6. 场景 D：取消

1. 在 Agent 执行 `auto` 期间，通过 `POST /imports/{job_id}/cancel` 取消下一个任务；
2. 预期：
   - 排队任务直接 `cancelled`；
   - 运行中任务在检查点后 `cancelled`，无部分数据；
   - 审计 `worker_cancel_requested`、`worker_cancelled`；
3. 对已完成任务取消 → 409。

## 7. 场景 E：重启恢复

1. 导入进行中强制关闭 Agent；
2. 重新启动 Agent：
   - 预期 `.context.json` 存在时以原 operation_id 恢复；
   - 上下文缺失/损坏 → 隔离，不伪装成功；
3. 后端重启后：
   - 预期 `backend_restarted` 审计；
   - 中断任务 `failed` 或 `cancelled`，可重试。

## 8. 证据清单

- 每个场景的 `diagnostics --json`、`jobs inspect` 输出；
- 截图（`SaveIdentityView` Worker/网络卡片、审计列表）；
- 后端审计导出（按 `save_id`）；
- 执行人与时间签名。

## 9. 结论口径

| 结果 | 含义 |
| --- | --- |
| PASS | 五个场景全部人工执行且符合预期 |
| PARTIAL | 至少一个场景因环境原因未执行 |
| FAIL | 任一场景出现跨存档污染、旧会话写入成功、半提交或重复写入 |

在完成本文件前，V3.2.7.4 的真实运行闭环只能标记 **REAL_FM27_ACCEPTANCE_PENDING**。
