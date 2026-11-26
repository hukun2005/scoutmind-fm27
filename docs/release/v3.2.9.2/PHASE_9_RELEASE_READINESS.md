# Phase 9：发布准备与授权检查（V3.2.9.2）

- 分支：`release/v3.2.9.2-stabilization` @ `d922a21`
- PR：<https://github.com/hukun2005/scoutmind-fm27/pull/16>
- 本阶段**不执行合并、不创建 Tag/Release、不上传资产**

## 1. 质量门禁

| 门禁 | 状态 | 证据 |
| --- | --- | --- |
| 后端全量测试 | PASS | 658 收集，0 失败 |
| Native Reader / Agent | PASS | 334 / 57 / 38 |
| 前端类型检查与构建 | PASS | `vue-tsc --noEmit` + `vite build` |
| Playwright | PASS | 9/9 |
| 数据库迁移往返 | PASS | upgrade / 重复 / downgrade / upgrade |
| 真实 FM27 扫描与导入 | PASS | 44,144 球员，重复上传 `duplicate=true` |
| 发布包干净目录验收 | PASS | 启动/停止/重启/持久化/备份/恢复 |
| 安全检查 | PASS | 无密钥入库；默认本机监听；未验证构建拒绝 |
| 发布文档 | PASS | `docs/release/v3.2.9.2/` 十份 |
| PR #16 CI | 见 §2 | — |
| PR #15 审查 | PASS | 无 BLOCKER/MAJOR，CI 6/6 |

## 2. CI（PR #16）

| 作业 | 结果 |
| --- | --- |
| `.NET readers and agent` | PASS（1m14s） |
| `Frontend (typecheck + build)` | PASS（51s） |
| `Playwright (governance)` | PASS（1m0s） |
| `PostgreSQL migration compatibility` | PASS（40s） |
| `Upload / identity / agent isolation regressions` | PASS（2m27s） |
| `Backend (pytest + migrations)` | 运行中（全量 pytest 约 20 分钟） |

最终 CI 结论以 PR 页面为准；本地对应测试已全部通过。

## 3. 待用户授权的动作

| 动作 | 当前状态 | 建议命令（授权后执行） |
| --- | --- | --- |
| 合并 PR #15（UI/UX） | 未执行 | `gh pr merge 15 --squash` |
| 合并 PR #16（发布收口） | 未执行 | `gh pr merge 16 --squash` |
| 创建 Tag | 未执行 | `git tag -a v3.2.9.2 -m "ScoutMind FM27 V3.2.9.2"` |
| 创建 Release | 未执行 | `gh release create v3.2.9.2 ...` |
| 上传 ZIP / SHA256SUMS | 未执行 | `gh release upload v3.2.9.2 <files>` |
| 标记 Latest | 未执行 | `gh release edit v3.2.9.2 --latest` |

本任务书明确要求：以上动作必须由用户明确授权，本轮一律不执行。

## 4. Release Notes 草稿

**标题**：`ScoutMind FM27 V3.2.9.2 — First Public Preview`

**正文**：

> 首个公开预览版。
>
> **本版重点**
> - 存档切换安全：切换即失效旧确认，确认绑定 generation，跨代写入拒绝；真实 FM27 A/B/A 验收通过。
> - 身份治理：Verified 生命周期账本、审核乐观锁与幂等、同名候选完整、转会证据关联。
> - 转会接口修复：`GET /transfers` 不再 500；`sort` 生效，非法字段返回 400；覆盖率按全量筛选集计算。
> - Windows 发布包：一键启动/停止/诊断/备份，单端口同时提供 API 与界面。
>
> **验证**
> - 后端 658 用例 0 失败；FMReader 334 / Reader 57 / Agent 38；前端构建 + Playwright 9/9。
> - 真实 FM27 27.1（build 26620374）：扫描 44,144 名球员，导入与重复上传去重通过。
>
> **资产**
> - `ScoutMind-FM27-V3.2.9.2-Windows-x64.zip`
> - `SHA256SUMS.txt`
>
> **要求**：Windows 10/11 x64、PowerShell 7、Python 3.11+；详见 INSTALLATION.md。
>
> **已知问题**：见 KNOWN_ISSUES.md（本机 PostgreSQL、本版 A/B/A 重跑、进程清理、axe 扫描为 NOT_RUN）。

## 5. 风险与回滚

| 风险 | 应对 |
| --- | --- |
| 发布后发现 P0 | 不删除 Release，发布 `3.2.9.3` 修复版本 |
| 用户数据库升级失败 | 升级前 `Backup-Database.ps1`；migration 未删除任何列 |
| PR #15 合并后视觉问题 | 单独回滚该 PR；本分支不依赖 #15 |
| 端口冲突 | `-Port` 参数；脚本会明确报错 |

## 6. 结论

代码、测试、安全、文档、发布包全部就绪；剩余动作均为需要用户授权的流程操作。

状态：**NEEDS_USER_APPROVAL**
