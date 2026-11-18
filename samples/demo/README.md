# 演示扫描样本

本目录的文件由 `scripts/seed_demo.py` 生成，用来在没有真实 FM27 扫描结果时验证导入、统计与界面。

- `scan-01.json` / `scan-02.json` / `scan-03.json`：同一存档在三个游戏日的快照（2026-08-01、2026-11-15、2027-03-01），
  其中第一份包含 150 笔历史交易。
- 所有记录 `source=synthetic_fixture`，`game.build=synthetic`，API 会返回 `demo_mode=true`。
- 俱乐部、球员、交易都是虚构的，与真实世界无关，**不可用于任何真实决策**。

重新生成：

```powershell
python scripts/seed_demo.py --force
```

导入单份样本：

```powershell
.\scripts\import-scan.ps1 -Path .\samples\demo\scan-01.json
```
