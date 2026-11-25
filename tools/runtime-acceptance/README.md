# Runtime Acceptance（V3.2.7.4）

本目录是 ScoutMind 的**运行期验收工具**，面向「Agent → 后端 → 数据库」真实链路。
它只做三件事：检查环境、用真实 HTTP 驱动后端、收集脱敏证据。

## 安全边界

- 不上传完整游戏存档，不读取用户私人文件，不修改游戏文件或 FM27 内存。
- 不注入未经授权的代码；只使用仓库已有的 Read / Agent / Backend 能力。
- 默认使用**临时 SQLite 数据库与临时数据目录**，不接触 `backend/data` 的生产数据。
- 证据只保留协议字段、状态码、事件类型与哈希；不保存 game_plugin 原文与个人路径以外的敏感内容。

## 一键入口

```powershell
pwsh -File tools/runtime-acceptance/run_acceptance.ps1
```

默认行为：

1. `inspect_environment.ps1` 采集环境事实；
2. 在临时目录建库并运行 `alembic upgrade head`；
3. 启动一个只监听 `127.0.0.1` 的临时后端；
4. 依次运行 `verify_save_isolation.py`、`verify_worker_fencing.py`、`verify_operation_idempotency.py`；
5. `collect_evidence.ps1` 生成 `manifest.json` 与 SHA-256；
6. 停止临时后端，输出结果汇总。

可选参数：

```powershell
pwsh -File tools/runtime-acceptance/run_acceptance.ps1 -KeepDatabase -Port 8123 -EvidenceDir docs/evidence/v3.2.7.4/runtime
```

## 真实 FM27 A/B 验收

自动化脚本验证的是**后端协议与数据库隔离**，不代表真实游戏验收通过。
真实 FM27 A/B 切换必须由人在游戏内完成，并按 [REAL-FM27-ACCEPTANCE.md](../../docs/evidence/v3.2.7.4/REAL-FM27-ACCEPTANCE.md) 记录。

当前若没有可用的真实 FM27 环境，一键入口会输出：

```text
REAL_FM27_ACCEPTANCE_PENDING
```

并且**不会**把任何真实游戏场景写成 PASS。

## 状态口径

| 状态 | 含义 |
| --- | --- |
| PASS | 本次真实执行且断言全部通过 |
| FAIL | 本次真实执行且有断言失败 |
| PARTIAL | 部分场景执行，其余有明确原因 |
| NOT_RUN | 未执行 |
| BLOCKED_BY_ENVIRONMENT | 缺少运行环境（如本机无 PostgreSQL、无 FM27） |
| REAL_FM27_ACCEPTANCE_PENDING | 真实游戏验收尚未执行 |

## 单独运行

```powershell
python tools/runtime-acceptance/verify_save_isolation.py --api http://127.0.0.1:8123/api/v1 --output runtime-evidence
python tools/runtime-acceptance/verify_worker_fencing.py --api http://127.0.0.1:8123/api/v1 --output runtime-evidence
python tools/runtime-acceptance/verify_operation_idempotency.py --api http://127.0.0.1:8123/api/v1 --output runtime-evidence
pwsh -File tools/runtime-acceptance/inspect_environment.ps1 -OutputDir runtime-evidence
pwsh -File tools/runtime-acceptance/simulate_network_failure.ps1 -Mode Unreachable
pwsh -File tools/runtime-acceptance/collect_evidence.ps1 -EvidenceDir runtime-evidence
```

> 这些脚本会产生**合成指纹**（`si:v1:test:*`）和合成扫描报文，用于验证安全协议；
> 它们绝不会冒用真实 Reader 的身份结论。
