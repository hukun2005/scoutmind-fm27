# Phase 7：文档与发布说明（V3.2.9.2）

## 1. 仓库根文档更新

| 文件 | 变更 |
| --- | --- |
| `README.md` | 状态块更新为 V3.2.9.2（658 用例、真实 44,144 球员、A/B/A PASS）；快速开始新增「普通用户：发布包」路径；开发者步骤保留 |
| `CHANGELOG.md` | 新增 `[V3.2.9.2]` 条目：修复、新增、迁移、测试四节 |
| `docs/ROADMAP.md` | 新增「V3.2.9.2 完成情况」，明确 NOT_RUN 项 |

## 2. `docs/release/v3.2.9.2/` 发布文档

| 文件 | 用途 |
| --- | --- |
| `README.md` | 文档索引与总体状态 |
| `INSTALLATION.md` | 解压、诊断、启动、停止、备份、接入 FM27、常见问题 |
| `SYSTEM_REQUIREMENTS.md` | 运行/开发环境要求、已验证游戏组合 |
| `COMPATIBILITY.md` | 已验证/未验证构建、判定规则、数据边界 |
| `RELEASE_NOTES.md` | 本版变更、升级说明 |
| `KNOWN_ISSUES.md` | 功能边界、环境限制、体验问题、安全说明 |
| `TEST_REPORT.md` | 全部测试命令与结果、NOT_RUN 清单 |
| `SECURITY_REPORT.md` | 密钥、暴露面、路径、数据、依赖 |
| `BUILD_REPORT.md` | 构建环境、产物、SHA256（Phase 8 最终值） |
| `RELEASE_CHECKLIST.md` | A–E 门禁清单，发布动作等待授权 |

## 3. 阶段报告

`PHASE_0` 至 `PHASE_9` 共 10 份，逐阶段记录真实执行结果与未执行项。

## 4. 一致性检查

| 检查 | 结果 |
| --- | --- |
| 文档中的测试数字与真实输出一致 | 是（658 / 334 / 57 / 38 / 9） |
| NOT_RUN 项未被写成 PASS | 是（PG、本版 A/B/A、进程清理、axe、依赖审计均标 NOT_RUN） |
| 发布包内文档路径与构建脚本一致 | 是（`INSTALLATION/RELEASE_NOTES/COMPATIBILITY/KNOWN_ISSUES` 随包复制） |
| README 中的链接存在 | 是 |

状态：**PASS**
