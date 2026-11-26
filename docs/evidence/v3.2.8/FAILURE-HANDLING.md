# 失败处理记录（Phase 13）

- 日期：2026-11-26
- 游戏版本：FM27 27.1
- Steam Build：26620374
- DLL 版本：game_plugin.dll 27.1
- Git SHA：`c3a8eb0`（修复前）
- 分支：`codex/v3.2.8-person-calibration`（未 push）

## 1. 失败 F1：真实样本哈希不一致

### 1.1 日志

- 完整日志保存在本机工作区外（含本机路径，不入库）。
- 脱敏摘要：

```text
FAILED tests/test_fmscout_real_data.py::test_real_sample_converts_cleanly[real_sample_01.json]
AssertionError: real_sample_01.json 与 manifest 记录的 sha256 不一致
expected 5dc9263c65c0...d9a98d0a1fa55
actual   8c79158972ca...dd0ad34a218b8
```

### 1.2 分类

**TEST_ERROR**（fixture 清单元数据过期），不是 CODE_ERROR。

### 1.3 根因

- 样本文件与 manifest 同时由提交 `691f754` 引入；该提交中的样本实际哈希为 `8c7915…`，manifest 却记录 `5dc926…`。
- 逐项核对样本元数据与 manifest：球员 300、职员 2、插件 1.7.3、生成时间 2026-11-18T21:49:54、游戏 FM27，均一致；只有 `sha256` 字段过期。
- 判断为 manifest 在样本最终字节确定前生成，之后样本被重写但清单未重新计算。
- 已排除换行符影响：原始文件与 LF 归一化后的哈希相同。

### 1.4 影响

- 仅影响真实数据回归用例的完整性断言；不影响读取器、后端运行时或现有稳定功能。
- 该断言在转换前执行，导致样本转换逻辑此前未被实际验证。

### 1.5 回归测试

- 既有测试 `test_real_sample_converts_cleanly` 本身就是回归守卫：先校验 manifest 哈希，再执行转换、字段报告与俱乐部名称断言。
- 未修改测试逻辑、未跳过用例、未降低断言。

### 1.6 最小修复

- 只更新 `backend/tests/fixtures/fmsuperscout/manifest.json` 中的 `sha256` 为样本实际哈希 `8c79158972caa059f2bb45fa3432686c9fc0ff30aff6c5f513add0ad34a218b8`。
- 未修改样本文件、测试代码或应用代码。

### 1.7 重新运行

| 范围 | 结果 | 状态 |
| --- | --- | --- |
| 目标文件 `tests/test_fmscout_real_data.py` | 12 项全部通过 | PASS |
| 全量后端 `pytest` | 582 项：579 通过、0 失败、3 跳过 | PASS |
| `git diff --check` | 退出码 0 | PASS |

## 2. 失败 F2：历史 CI 全部失败

- 分类：**UNKNOWN**（既有问题，未取得失败明细）。
- 最近 8 次运行均为 failure；尝试读取单次明细时 GitHub API 返回 EOF。
- 本分支未 push，因此没有本分支 CI 结果（NOT_RUN）。
- 未修改测试或 CI 配置来绕过；未反复重试无效请求。
- 处理建议：待 CI 可用时取失败 job 日志后，再按 CODE_ERROR / GITHUB_* / AGENT_CONCURRENCY_ERROR 分类。

## 3. 失败 F3：`probe` 返回未通过

- 分类：**GAME_PROCESS_UNAVAILABLE**（游戏未加载存档/布局探测失败）。
- 命令本身退出码 0、JSON 合法，属于环境状态，不是命令回归。
- 未做代码修改。

## 4. Verified 停止条件检查

| 条件 | 是否触发 |
| --- | --- |
| Person 结构不确定 | 否 |
| 姓名与出生日期冲突 | 否（3 名 Verified 均一致） |
| 多个属性记录匹配 | 否（Verified 时唯一） |
| 游戏版本不匹配 | 否 |
| 内存读取不稳定 | 否 |
| 人工核对失败 | 否 |
| 绕过 Verified 门控的路径 | 否 |

当前存档存在 1 条同名属性记录冲突，但未对该球员执行 Verified；冲突保持 `ConflictingIdentity`。

## 5. 修复轮次

- 第 1 轮：修正 manifest 哈希；目标与全量后端测试通过。
- 未进行第 2、3 轮修复（已无明确根因的失败）。

## 6. 未完成项

- 历史 CI 失败明细未取得，根因仍为 UNKNOWN。
- 本分支 CI 未运行（未 push）。
- Playwright / PostgreSQL 测试未本地运行。
