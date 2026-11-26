# apps/desktop/integration_test · 集成测试

一条完整链路的端到端测试：**设置密钥（桩）→ 一次研判 → RunSummary →
claim 绑定 evidence → 越权被拒 → 审计事件落盘**。

## 运行

```bash
cd apps/desktop

# 推荐：flutter-tester（无窗口、无插件依赖，CI 可跑）
flutter test -d flutter-tester integration_test/full_chain_test.dart

# 桌面设备（需要系统插件依赖，见下方"已知阻塞"）
flutter test -d linux integration_test/full_chain_test.dart
```

## 覆盖点

| # | 断言 |
|---|---|
| 1 | 密钥：内存桩 + 临时目录文件存储；**不读写 `secrets/` 真实密钥**；脱敏显示 `sk-****abcd` |
| 2 | 一次研判产出 `RunSummary`；每条 `ClaimProduced` 至少绑一条证据，且证据在本次 run 的证据集合内；无证据草稿被丢弃 |
| 3 | 越权（`financing` 调 `systemic_risk`）与未登记工具都被拒，**RPC 调用数 = 0**；合法调用才发一次 `tools.invoke` |
| 4 | 审计事件按 JSONL 落盘并可回读，字段（`type/outcome/actor/tool/risk_level/reason/detail`）齐全 |

## 桩的纪律

- 桩响应一律带 `SYNTHETIC` 标记（出现在 claim 文本与 `limitations` 里），
  测试断言该标记存在，避免桩数据被误当成真实结论。
- 桩不写真实行情数值；数值只用于触发 claim 回填路径。
- 测试全程使用 `Directory.systemTemp` 下的临时目录，结束时删除。

## 已知阻塞（如实记录，不绕过）

在**本机 Linux 开发环境**上，`flutter test -d linux` 与
`flutter test integration_test/...`（默认设备）会失败，原因与本次改动无关：

1. **缺少系统插件依赖**：`audioplayers_linux` 的 CMake 需要 `gstreamer-1.0`，
   本机未安装 → `CMake Error: The following required packages were not found: gstreamer-1.0`。
2. **原生资产构建**：`cnativeapi`（`window_manager` 的传递依赖）用
   `/usr/lib/llvm-21/bin/clang` 编译 C++，本机 clang 找不到 libstdc++ 头
   （`fatal error: 'atomic' file not found`）。

因此集成测试用 `-d flutter-tester` 执行（不加载桌面插件，纯 Dart 逻辑 + 临时文件）。
桌面设备上的真机验证需要在装齐 GTK/GStreamer 与 C++ 标准库头的环境执行；
这是环境前置，不是测试本身的问题。

## 与单元测试的分工

- `test/agents/*`：编排/回填/冲突/核验的单元与契约测试（86 个用例）；
- `integration_test/full_chain_test.dart`：把「密钥 → 研判 → 证据 → 门卫 → 审计」
  串成一条可执行的验收链路。
