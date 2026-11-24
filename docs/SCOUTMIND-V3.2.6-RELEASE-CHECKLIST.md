# ScoutMind FM27 V3.2.6 发布检查清单

日期：2026-11-24 · 分支 `codex/v3.2.6-release-candidate` · 基线 `f8c740e`

| 验收项 | 状态 | 说明 |
| --- | --- | --- |
| 进程内日期读取 | PASS | 10-26 / 10-31 / 11-06 与界面一致（历史证据） |
| 候选日期筛选 | PASS | 5 例自动化（最新/歧义/过滤/稳定） |
| 日期语义验证 | PARTIAL | 启发式，非 Verified |
| 多候选歧义处理 | PASS | `ambiguous` 状态 |
| 跨进程重新定位 | PARTIAL | 11-06 一次成功；启发式 |
| 连续日期变化（11-07/08） | NOT_RUN | 本轮游戏已退出 |
| 真实 FM27 跨重启（多次） | NOT_RUN | — |
| 多存档身份隔离 | PASS（自动化） | 真实切换 NOT_RUN |
| 多存档真实切换 | NOT_RUN | 只有一个存档 |
| Worker 持久化 | NOT_RUN | 未实现 |
| Worker 重启恢复 | NOT_RUN | — |
| Worker 暂停/取消/重试 | NOT_RUN | — |
| 自动快照幂等 | BLOCKED | 依赖可信日期 + Worker |
| 文件 SHA-256 校验 | PASS | Agent 三件套既有实现 |
| 文件损坏隔离 | PASS | `quarantine/` 既有实现 |
| 数据库事务完整性 | PASS | 单事务导入，失败回滚 |
| Playwright 核心页面 | PARTIAL | 9 例既有；无自动采集页 |
| Windows 全新安装 | NOT_RUN | 无安装器 |
| Windows 升级/卸载 | NOT_RUN | 无安装器 |
| 数据备份恢复 | PASS（手工步骤） | 文档已给命令 |
| Backend 测试 | PASS（历史） | 494/497，本轮未改后端 |
| Reader 测试 | PASS | 156/156 + 53/53 |
| Frontend 测试 | PASS（构建） | 本轮未改前端 |
| SQLite Migration | PASS | 无新迁移 |
| PostgreSQL 16 | PASS（CI） | — |
| GitHub Actions | 待本提交 | 见 CI run |

## 阻塞发布（RC 可接受但需声明）

1. 日期定位启发式、自动快照关闭；
2. 无 Worker；
3. 无安装器；
4. 真实多存档未验证。

## 结论

`READY_FOR_BETA_WITH_LIMITATIONS`：核心分析功能可用，未验证能力默认关闭；
不满足 `READY_FOR_RC`（安装包、Worker、真实多存档、连续日期验收缺失）。
