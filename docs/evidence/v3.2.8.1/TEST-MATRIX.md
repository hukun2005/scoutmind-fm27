# 测试矩阵（V3.2.8.1 Phase 7）

全部数字来自本阶段真实执行，不使用历史报告复制。

## 1. 汇总

| 套件 | 总数 | PASS | FAIL | SKIP | 备注 |
| --- | --- | --- | --- | --- | --- |
| Backend pytest | 591 | 588 | 0 | 3 | 含 9 项新 fixture 完整性测试 |
| ScoutMind.FMReader.Tests | 308 | 308 | 0 | 0 | 较 V3.2.8 的 286 增加 22 |
| ScoutMind.Reader.Tests | 57 | 57 | 0 | 0 | 无回归 |
| ScoutMind.Agent.Tests | 38 | 38 | 0 | 0 | 无回归 |
| Frontend 生产构建 | 1 | PASS | 0 | 0 | `vue-tsc --noEmit && vite build` |
| `git diff --check` | 1 | PASS | 0 | 0 | 退出码 0 |

## 2. 新增测试明细

### 2.1 Backend（9）

见 `BACKEND-TEST-INTEGRITY.md` 第 4 节。

### 2.2 FMReader 作用域/生命周期（17）

见 `VERIFIED-LIFECYCLE-TESTS.md` 第 1 节。

### 2.3 门控拒绝路径（新增 5，既有 16 全部回归）

见 `VERIFIED-LIFECYCLE-TESTS.md` 第 2 节。

## 3. 未执行 / 不可在本机执行

| 项目 | 状态 | 原因 |
| --- | --- | --- |
| 真实 FM27 A/B/A | NOT_RUN | 需要人工切换存档并识别球员；当前存档无法按姓名唯一匹配历史核对球员 |
| 真实转会/自由球员/退役生命周期 | NOT_RUN | 需要用户在游戏中制造对应状态 |
| PostgreSQL 迁移兼容（本地） | NOT_RUN | 本地无 PostgreSQL 实例；CI 已 SUCCESS |
| Playwright（本地） | NOT_RUN | 依赖 CI 环境；CI 已 SUCCESS |
| `source_sha256` 复核 | UNKNOWN | 原始 48k dump 不在仓库，无法验证 |

## 4. 与 V3.2.8 的一致性

- 未删除任何测试，未降低任何断言。
- 未新增 skip。
- 原失败用例 `test_real_sample_converts_cleanly` 通过根因修复与完整性护栏后真实 PASS。
