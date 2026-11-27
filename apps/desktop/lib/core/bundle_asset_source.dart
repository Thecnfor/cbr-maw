/// 把 Flutter 的 [AssetBundle] 适配成 agents 层的 [AssetSource]。
///
/// 这是**唯一**允许 agents 资源访问 Flutter 的落点（应用组合根）。
library;

import 'package:flutter/services.dart' show AssetBundle, rootBundle;

import '../agents/roles/asset_source.dart';

/// 资源包适配器。
final class BundleAssetSource implements AssetSource {
  /// 创建适配器；缺省使用根资源包。
  BundleAssetSource([AssetBundle? bundle]) : bundle = bundle ?? rootBundle;

  /// 被包装的资源包。
  final AssetBundle bundle;

  @override
  Future<String> read(String path) => bundle.loadString(path);
}
