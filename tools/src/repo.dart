// 仓库定位与 JSON 读取的公共小工具（仅供 tools/ 脚本使用）。
// ignore_for_file: avoid_print
import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

/// 仓库根：优先从当前目录向上找含 contracts/ 的目录，其次从脚本路径向上找。
Directory repoRoot() {
  for (final start in [
    Directory.current,
    File.fromUri(Platform.script).parent,
  ]) {
    var dir = start;
    while (true) {
      if (Directory(p.join(dir.path, 'contracts')).existsSync()) {
        return dir;
      }
      final parent = dir.parent;
      if (parent.path == dir.path) {
        break;
      }
      dir = parent;
    }
  }
  stderr.writeln('无法定位仓库根（向上找不到 contracts/）。请在仓库内运行。');
  exit(2);
}

/// 读取 JSON 文件（UTF-8，容忍 BOM）。
Object? readJson(String path) {
  var text = File(path).readAsStringSync();
  if (text.startsWith('﻿')) {
    text = text.substring(1);
  }
  return jsonDecode(text);
}

/// 读取 JSON 对象。
Map<String, Object?> readJsonObject(String path) {
  final value = readJson(path);
  if (value is! Map<String, Object?>) {
    throw FormatException('$path 顶层不是 JSON 对象');
  }
  return value;
}

/// 相对仓库根的路径（用于报错）。
String relPath(Directory root, String path) =>
    p.relative(path, from: root.path);

/// 递归列出匹配的文件。
List<File> listFiles(Directory root, bool Function(String path) match) =>
    root
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => match(f.path))
        .toList()
      ..sort((a, b) => a.path.compareTo(b.path));

/// 打印小节标题。
void section(String title) => print('\n$title');

/// 打印违规明细并退出：0 通过，1 有违规，2 环境/依赖问题。
Never finish(List<String> errors, int checked, String what) {
  for (final error in errors) {
    print('  - $error');
  }
  if (errors.isEmpty) {
    print('PASS $what（检查 $checked 项，0 违规）');
    exit(0);
  }
  print('FAIL $what（检查 $checked 项，${errors.length} 处违规）');
  exit(1);
}
