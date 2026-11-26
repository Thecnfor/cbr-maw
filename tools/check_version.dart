// 单一真源版本一致性（docs/11 §7.3）：
// VERSION 文件 → Dart(pubspec) / Go / Rust(CARGO_PKG_VERSION) / 安装包名。
//
// 真源解析顺序（打印实际用了哪个）：
//   1. 根 `VERSION`（docs/11 §7.3 约定的单一真源）；
//   2. 缺失时退回 `apps/desktop/pubspec.yaml` 的 version，并显著告警
//      （当前 packaging/build.sh 注入的是 contracts/VERSION，属另一概念：
//       契约版本 ≠ 应用版本，两者不互相比较）。
//
// 退出码：0 = 各语言声明一致（允许"真源缺失"降级并告警）；
//         1 = 版本不一致；2 = 无任何可比对的版本声明。
// ignore_for_file: avoid_print
import 'dart:io';

import 'package:path/path.dart' as p;

import 'src/repo.dart';
import 'src/versions.dart';

void main() {
  final root = repoRoot();
  final errors = <String>[];
  var checked = 0;

  section('[1] 单一真源');
  final rootVersion = File(p.join(root.path, 'VERSION'));
  final pubspec = File(p.join(root.path, 'apps', 'desktop', 'pubspec.yaml'));
  String? expected;
  if (rootVersion.existsSync()) {
    expected = rootVersion.readAsStringSync().trim();
    print('真源：VERSION = $expected');
  } else if (pubspec.existsSync()) {
    expected = RegExp(
      r'^version:\s*(\S+)',
      multiLine: true,
    ).firstMatch(pubspec.readAsStringSync())?.group(1)?.trim();
    print('WARN 根 VERSION 缺失（docs/11 §7.3 要求它是单一真源）。');
    print('WARN 降级为 apps/desktop/pubspec.yaml 的 version = $expected 作比对基准。');
    print('WARN 注意：packaging/build.sh 目前读取 contracts/VERSION（契约版本，另一概念）。');
  }
  if (expected == null) {
    stderr.writeln('没有任何可用的版本真源（根 VERSION 与 apps/desktop/pubspec.yaml 都不存在）。');
    exit(2);
  }
  checked++;
  if (!RegExp(r'^\d+\.\d+\.\d+$').hasMatch(expected)) {
    errors.add('版本真源不是语义化版本（X.Y.Z）：$expected');
  }

  section('[2] 各语言实现声明');
  for (final rel in missingAppVersionFiles(root)) {
    print('  ! 缺少 $rel（该实现尚未落地，跳过比对）');
  }
  final decls = appVersionDeclarations(root);
  for (final decl in decls) {
    print(
      '  ${decl.version == expected ? "ok " : "BAD"} ${decl.label} = ${decl.version}',
    );
  }
  checked += decls.length;
  errors.addAll(appVersionMismatches(expected, decls));
  if (decls.isEmpty) {
    stderr.writeln('没有找到任何版本声明文件（期望至少 apps/desktop/pubspec.yaml）。');
    exit(2);
  }

  section('[3] 安装包命名');
  final iss = File(p.join(root.path, 'packaging', 'windows', 'CBR-MAW.iss'));
  if (!iss.existsSync()) {
    print('  ! 缺少 packaging/windows/CBR-MAW.iss（打包脚本尚未落地，跳过）');
  } else {
    checked++;
    final text = iss.readAsStringSync();
    if (RegExp(
      r'^#define\s+AppVersion\s+"([^"]+)"',
      multiLine: true,
    ).hasMatch(text)) {
      print('  BAD 安装器把版本写死在脚本里；应由 /DAppVersion 注入');
      errors.add('packaging/windows/CBR-MAW.iss 写死了 AppVersion，应由构建脚本注入');
    } else {
      print('  ok  安装器版本由 /DAppVersion 注入');
    }
  }

  finish(errors, checked, '版本一致性');
}
