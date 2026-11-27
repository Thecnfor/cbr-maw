/// 资源读取的最小接口。
///
/// 目的：`lib/agents/` 保持**零 Flutter 依赖**，使同一套编排逻辑既能跑在桌面壳里
/// （`rootBundle`），也能在纯 Dart CLI / 基准 harness 里跑（文件系统）。
/// 这不是抽象癖：bench 控制台必须能用 `dart run` 启动，才能流式看到思维链。
library;

import 'dart:io';

/// 按键读取文本资源。
abstract interface class AssetSource {
  /// 读取 [path] 的 UTF-8 文本；缺失时抛 [FileSystemException]。
  Future<String> read(String path);
}

/// 文件系统实现：`root` 为仓库根，`path` 为仓库相对路径。
final class FileAssetSource implements AssetSource {
  /// 创建文件源。
  const FileAssetSource(this.root);

  /// 仓库根目录。
  final String root;

  @override
  Future<String> read(String path) => File('$root/$path').readAsString();
}
