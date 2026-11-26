// 版本声明的提取与比对（供 validate_contract.dart / check_version.dart 共用）。
//
// 只读源码文本，不编译、不运行任何实现；文件缺失时给出明确提示而不是崩溃。
import 'dart:io';

import 'package:path/path.dart' as p;

/// 一处版本声明。
final class VersionDecl {
  const VersionDecl({
    required this.label,
    required this.path,
    required this.version,
  });

  /// 人读标签（如 `Rust kernel`）。
  final String label;

  /// 声明所在文件（仓库相对路径）。
  final String path;

  /// 读到的版本号。
  final String version;

  @override
  String toString() => '$label @ $path = $version';
}

/// 从文本里按正则抓第一个分组；无匹配返回 null。
String? _grab(String path, String pattern) {
  final file = File(path);
  if (!file.existsSync()) {
    return null;
  }
  final match = RegExp(
    pattern,
    multiLine: true,
  ).firstMatch(file.readAsStringSync());
  return match?.group(1)?.trim();
}

/// 应用版本声明（VERSION 单一真源 → 各语言与安装包）。
List<VersionDecl> appVersionDeclarations(Directory root) {
  final decls = <VersionDecl>[];
  void add(String label, String rel, String pattern) {
    final value = _grab(p.join(root.path, rel), pattern);
    if (value != null) {
      decls.add(VersionDecl(label: label, path: rel, version: value));
    }
  }

  add('Dart 桌面端 pubspec', 'apps/desktop/pubspec.yaml', r'^version:\s*(\S+)');
  add(
    'Go collector',
    'services/collector/internal/service/service.go',
    r'^var Version = "([^"]+)"',
  );
  add(
    'Rust kernel (Cargo.toml)',
    'services/kernel/Cargo.toml',
    r'^version = "([^"]+)"',
  );
  // 安装包版本由 iscc /DAppVersion 注入；只有显式写了默认值时才核对。
  add(
    'Inno Setup 默认版本',
    'packaging/windows/CBR-MAW.iss',
    r'^#define AppVersion "([^"]+)"',
  );
  return decls;
}

/// 契约版本声明（各语言实现必须与 contracts/VERSION 一致）。
List<VersionDecl> contractVersionDeclarations(Directory root) {
  final decls = <VersionDecl>[];
  void add(String label, String rel, String pattern) {
    final value = _grab(p.join(root.path, rel), pattern);
    if (value != null) {
      decls.add(VersionDecl(label: label, path: rel, version: value));
    }
  }

  add(
    'Rust kernel CONTRACT_VERSION',
    'services/kernel/src/lib.rs',
    r'pub const CONTRACT_VERSION: &str = "([^"]+)"',
  );
  add(
    'Go collector ContractVersion',
    'services/collector/internal/service/service.go',
    r'^const ContractVersion = "([^"]+)"',
  );
  add(
    'Dart 客户端握手 contract_version',
    'apps/desktop/lib/app/app_state.dart',
    r"contractVersion: '([^']+)'",
  );
  return decls;
}

/// 契约版本不一致清单（空 = 一致）。缺实现时返回空并说明由调用方打印。
List<String> contractVersionMismatches(Directory root, String expected) {
  final mismatches = <String>[];
  for (final decl in contractVersionDeclarations(root)) {
    if (decl.version != expected) {
      mismatches.add(
        '${decl.label}（${decl.path}）声明契约版本 ${decl.version}，contracts/VERSION 为 $expected',
      );
    }
  }
  return mismatches;
}

/// 应用版本不一致清单（空 = 一致）。
///
/// [expected] 为单一真源读到的版本；[decls] 为各语言声明。
List<String> appVersionMismatches(String expected, List<VersionDecl> decls) => [
  for (final decl in decls)
    if (decl.version != expected)
      '${decl.label}（${decl.path}）为 ${decl.version}，单一真源为 $expected',
];

/// 缺失的版本声明（提示用，不算违规）。
List<String> missingAppVersionFiles(Directory root) => [
  for (final rel in [
    'apps/desktop/pubspec.yaml',
    'services/collector/internal/service/service.go',
    'services/kernel/Cargo.toml',
  ])
    if (!File(p.join(root.path, rel)).existsSync()) rel,
];
