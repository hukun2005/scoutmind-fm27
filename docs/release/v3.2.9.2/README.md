# ScoutMind FM27 V3.2.9.2 发布文档

- 版本：`3.2.9.2`
- 类型：First Public Preview
- 基线：`main` @ `33882bc`
- 发布日期：2026-11-26（候选）

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [INSTALLATION.md](INSTALLATION.md) | 解压、诊断、启动、停止、备份、接入 FM27 |
| [SYSTEM_REQUIREMENTS.md](SYSTEM_REQUIREMENTS.md) | 运行与开发环境要求 |
| [COMPATIBILITY.md](COMPATIBILITY.md) | 已验证/未验证的 FM27 构建与判定规则 |
| [RELEASE_NOTES.md](RELEASE_NOTES.md) | 本版变更与升级说明 |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | 已知问题与 NOT_RUN 项 |
| [TEST_REPORT.md](TEST_REPORT.md) | 测试执行与结果 |
| [SECURITY_REPORT.md](SECURITY_REPORT.md) | 安全检查 |
| [BUILD_REPORT.md](BUILD_REPORT.md) | 构建产物、SHA256 与可复现步骤 |
| [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) | 发布门禁清单 |

## 阶段报告

| Phase | 文档 | 结论 |
| --- | --- | --- |
| 0 | [PHASE_0_REPOSITORY_AUDIT.md](PHASE_0_REPOSITORY_AUDIT.md) | PASS |
| 1 | [PHASE_1_UI_REVIEW.md](PHASE_1_UI_REVIEW.md) | PASS（PR #15 等待合并授权） |
| 2 | [PHASE_2_BACKEND_FIXES.md](PHASE_2_BACKEND_FIXES.md) | PASS |
| 3 | [PHASE_3_DATABASE_INTEGRITY.md](PHASE_3_DATABASE_INTEGRITY.md) | PASS（本地 PG NOT_RUN） |
| 4 | [PHASE_4_WINDOWS_PACKAGING.md](PHASE_4_WINDOWS_PACKAGING.md) | PASS |
| 5 | [PHASE_5_NATIVE_READER_VALIDATION.md](PHASE_5_NATIVE_READER_VALIDATION.md) | PASS（A/B/A、进程清理 NOT_RUN） |
| 6 | [PHASE_6_REGRESSION_SECURITY.md](PHASE_6_REGRESSION_SECURITY.md) | PASS |
| 7 | [PHASE_7_DOCUMENTATION.md](PHASE_7_DOCUMENTATION.md) | PASS |
| 8 | [PHASE_8_RELEASE_CANDIDATE.md](PHASE_8_RELEASE_CANDIDATE.md) | PASS |
| 9 | [PHASE_9_RELEASE_READINESS.md](PHASE_9_RELEASE_READINESS.md) | 等待用户授权 |

## 当前状态

- 代码质量门禁：PASS
- 真实 FM27 验收：PASS（单存档扫描/导入/去重；A/B/A 于 PR #14 真实验收）
- 发布包：`ScoutMind-FM27-V3.2.9.2-Windows-x64.zip`，66,716,790 字节，SHA256 `2d5e31fc…ee91`
- PR #16（发布收口）：已创建，未合并
- PR #15（UI/UX）：可合并，**未合并**，等待用户授权
- GitHub Release / Tag：**未创建**，等待用户授权

## 结论口径

- `PASS`：已真实执行并通过
- `NOT_RUN`：本轮未执行
- `BLOCKED_BY_ENVIRONMENT`：环境不具备（如本机 PostgreSQL）
- `NEEDS_USER_APPROVAL`：等待用户决定（合并 PR #15、创建 Release/Tag）
