// 依赖方向检查（docs/09 §3）。
//
// 规则：
// 1. lib/core 不得 import 其它 lib 子目录；
// 2. lib/data 不得 import agents/ui/app/features；
// 3. lib/ui 不得 import data/agents/features；
// 4. lib/agents 不得 import features/app；
// 5. 只有 lib/genui/adapter/ 允许 import package:genui；
// 6. 只有 lib/agents/ 允许 import package:genkit。
//
// 违规非零退出（1 = 有违规；2 = 环境问题）。
// ignore_for_file: avoid_print
import 'dart:io';

import 'package:path/path.dart' as p;

import 'src/repo.dart';

/// 每层禁止依赖的层（docs/09 §3）。
const _forbidden = <String, Set<String>>{
  'core': {'agents', 'app', 'data', 'features', 'genui', 'ui'},
  'data': {'agents', 'app', 'features', 'ui'},
  'ui': {'agents', 'data', 'features'},
  'agents': {'app', 'features'},
};

/// 只有这些目录允许 import 指定外部包。
const _packageAllow = <String, String>{
  'package:genui/': 'lib/genui/adapter/',
  'package:genkit/': 'lib/agents/',
};

final _importRe = RegExp(r'''^\s*(?:import|export)\s+['"]([^'"]+)['"]''');

void main() {
  final root = repoRoot();
  final lib = Directory(p.join(root.path, 'apps', 'desktop', 'lib'));
  if (!lib.existsSync()) {
    stderr.writeln('缺少 ${lib.path}');
    exit(2);
  }

  final files = listFiles(lib, (path) => path.endsWith('.dart'));
  final errors = <String>[];
  var checked = 0;

  for (final file in files) {
    final rel = relPath(root, file.path);
    final libRel = 'lib/${p.relative(file.path, from: lib.path)}';
    final segments = p.split(p.relative(file.path, from: lib.path));
    final layer = segments.first;
    for (final line in file.readAsLinesSync()) {
      final match = _importRe.firstMatch(line);
      if (match == null) {
        continue;
      }
      final import = match.group(1)!;
      checked++;

      // 外部包白名单。
      for (final entry in _packageAllow.entries) {
        if (import.startsWith(entry.key) && !libRel.startsWith(entry.value)) {
          errors.add(
            '$rel: 只有 ${entry.value} 允许 import ${entry.key}（实际 import $import）',
          );
        }
      }

      final target = _resolve(libRel, import);
      if (target == null) {
        continue;
      }
      final targetSegments = p.split(target);
      if (targetSegments.length < 2 || targetSegments.first != 'lib') {
        continue;
      }
      final targetLayer = targetSegments[1];
      if (targetLayer == layer) {
        continue;
      }
      final banned = _forbidden[layer];
      if (banned != null && banned.contains(targetLayer)) {
        errors.add('$rel: lib/$layer 不得依赖 lib/$targetLayer（import $import）');
      }
    }
  }

  print('扫描 ${files.length} 个 dart 文件、$checked 条 import');
  finish(errors, checked, '分层依赖检查');
}

/// 把 import 解析成仓库相对路径（`lib/...`）；非本项目 import 返回 null。
String? _resolve(String fromRel, String import) {
  if (import.startsWith('dart:') || import.startsWith('package:')) {
    if (import.startsWith('package:cbr_maw/')) {
      return p.normalize(
        p.join('lib', import.substring('package:cbr_maw/'.length)),
      );
    }
    return null;
  }
  final joined = p.normalize(p.join(p.dirname(fromRel), import));
  return joined.startsWith('lib/') ? joined : null;
}
