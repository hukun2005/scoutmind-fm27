# ScoutMind V3.2.5.1 Phase 0：模块定位审计

日期：2026-11-24 · 分支 `codex/v3.2.5.1-memscan-module-resolution`（基于 `d114dee`）
真实环境：FM27 27.1.0 / build 26620374 / 插件 27.1

## 1. GpBase / GaBase 是什么

- `GpBase` = `game_plugin.dll` 基址，FM 的 native C++ 数据库层，球员/俱乐部等对象在这里分类；
- `GaBase` = `GameAssembly.dll` 基址，Unity/托管层。

两者在 `MemScan` 构造函数中由 `FindModules()` 通过 `Process.Modules` 赋值，并写入 `_loMod/_hiMod` 供 `InGp/InGa` 使用。

## 2. 之前“拿不到模块边界”的真正原因

不是 `FindModules` 失败，而是我们的封装用错了来源：

- `MemScan.ScanRegions` 只包含 `MEM_PRIVATE + PAGE_READWRITE/WRITECOPY` 的**堆**区域（本次 1,617 个）；
- 模块镜像区域（`MEM_IMAGE`）**不在** `ScanRegions` 里；
- 旧代码却用 “`ScanRegions` 中 `InModule(start)` 的区域” 当模块区域 → 永远为空。

真实边界（`module-info` 实测）：

```text
game_plugin   0x7FFD55290000 .. 0x7FFD6DB08000  (411,533,312 B)
GameAssembly  0x7FFD987A0000 .. 0x7FFD9C36F000
scan regions  1617
```

## 3. 修复

- 新增 `WinMemorySource.Bounds`（暴露 `GpBase/GpEnd/GaBase/GaEnd/ScanRegionCount/PluginPath`）；
- 新增 `module-info` 诊断命令；
- `StaticDateScan` 改为**接收调用方给出的模块区域**，不再自行猜测；
- 新增 `date-read --rva --field`：按“模块基址 + RVA → 指针 → 字段”读取，重启后只需重新解析模块基址。

MemScan 本身未修改（避免动 vendored 核心）；读取仍然只读、有预算、可取消。

## 4. 审计结论

| 问题 | 回答 |
| --- | --- |
| 扫描的是哪块内存 | 仅堆（1617 个可写私有区域），不含模块镜像 |
| 模块边界能否拿到 | 能，`Process.Modules` 一直可用 |
| 之前为什么空 | 用堆区域反推模块，逻辑错 |
| 是否有现成 ModuleResolver | 没有，只有 `MemScan.FindModules` 内部实现 |
| 日期候选来源 | 只按值匹配，没有结构语义 |
| 指针链为何不跨重启 | 只有堆内引用，没有模块静态根 |

## 5. 后续

静态根扫描已在真实环境跑通（见 `SCOUTMIND-V3.2.5.1-POINTER-ANALYSIS.md`），
但找到的根指向“日历/赛程”对象，不是世界时钟；日期字段仍需继续定位。
