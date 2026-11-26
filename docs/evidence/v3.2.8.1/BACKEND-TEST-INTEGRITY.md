# Backend 测试完整性与 fixture SHA-256 根因（V3.2.8.1 Phase 2）

## 1. 现象

V3.2.8 的历史报告出现两套互相矛盾的统计：

- 「582 项，0 失败，3 skipped」。
- 「581 PASS、1 FAIL、3 skipped」。

失败项固定为 `test_real_sample_converts_cleanly`：
`real_sample_01.json` 与 manifest 记录的 SHA-256 不一致。

## 2. 根因（可复现的事实）

### 2.1 样本从未变过

```text
git show 691f754:backend/tests/fixtures/fmsuperscout/real_sample_01.json | sha256
→ 8c79158972caa059f2bb45fa3432686c9fc0ff30aff6c5f513add0ad34a218b8（415016 字节，无 CRLF）
```

`691f754`（样本首次加入）、`89fdaf2`、当前 HEAD 三处 blob 的 SHA-256 完全相同。

### 2.2 manifest 从登记起就是错的

- `691f754` 的 manifest 记录 `5dc9263c…`，与同一次提交里的样本字节（`8c7915…`）不一致。
- `89fdaf2` 只把 manifest 改成 `8c7915…`，样本没有任何变化；这是**手改 manifest 让测试通过**，
  不是根因修复，也没有留下护栏。

结论：`5dc926…` 不对应仓库里任何版本的样本 blob。登记时「被哈希的内容」和「最终提交的字节」不是同一份。

### 2.3 登记脚本缺少护栏

`scripts/register_fixture.py` 原来的做法：

1. `json.dumps(...)` 得到字符串；
2. `Path.write_text(...)` 写盘（Windows 文本模式会把 `\n` 转成 `\r\n`）；
3. 对**内存字符串**算 SHA-256 写入 manifest；
4. 从不读回磁盘字节复核。

因此只要写盘字节与字符串有任何差异（换行翻译、编码、二次裁剪后忘记重算），manifest 就会静默错位，
而测试只在运行时才发现，且当时没有完整性用例保护。

`source_sha256` 对应的原始 48k dump 不在仓库内，无法复核 → 该字段状态为 **UNKNOWN**，本阶段不宣称其正确。

## 3. 修复

| 文件 | 修改 |
| --- | --- |
| `scripts/register_fixture.py` | 改为 `write_bytes`；写盘后**读回字节**再算 SHA-256；登记完成立即校验；新增 `--verify` 只读校验模式 |
| `backend/tests/fixture_integrity.py` | 新增独立的「读字节 → 算哈希 → 比对 manifest」判定，脚本与测试共用 |
| `backend/tests/test_fixture_integrity.py` | 新增 9 项完整性回归 |
| `.gitattributes` | `backend/tests/fixtures/fmsuperscout/real_sample_*.json -text`，禁止换行转换 |

manifest 当前值 `8c7915…` 已由 `python scripts/register_fixture.py --verify` 复核通过；没有再手改数值。

## 4. 完整性回归（9 项，全部 PASS）

| 用例 | 覆盖 |
| --- | --- |
| `test_committed_fixture_matches_manifest` | 原始样本哈希正确 |
| `test_modified_fixture_is_rejected` | 样本被追加字节 → `hash_mismatch` |
| `test_missing_manifest_is_rejected` | manifest 缺失 → `manifest_missing` |
| `test_malformed_manifest_is_rejected` | manifest 损坏 → `manifest_invalid` |
| `test_manifest_without_samples_is_rejected` | 空样本列表 → `no_samples` |
| `test_missing_fixture_is_rejected` | 样本缺失 → `fixture_missing` |
| `test_swapped_fixture_is_rejected` | 同名但整体替换 → `hash_mismatch` |
| `test_entry_without_hash_is_rejected` | 条目缺 sha256 → `entry_invalid` |
| `test_sha256_is_computed_over_raw_bytes` | LF 与 CRLF 不可互相顶替 |

## 5. 统一统计（同一批次真实执行）

执行：`python -m pytest -q`（backend，Windows，Python 3.13.15，pytest 9.2.0）

| 指标 | 数值 |
| --- | --- |
| 收集 | 591 |
| PASS | 588 |
| FAIL | 0 |
| ERROR | 0 |
| SKIPPED | 3 |
| NOT_RUN | 0 |

与 V3.2.8 基线的关系：582 + 9 项新完整性测试 = 591；没有删除或跳过任何既有测试。

3 项 skipped 的原因由既有用例自带（依赖外部数据库/环境），本阶段未新增 skip。
