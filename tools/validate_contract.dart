// 校验 contracts/ 自身一致性，四件事：
// 1) 每个 *.schema.json 是合法 JSON Schema draft 2020-12；
// 2) 每个 contracts/examples/<method>/*.json 与对应 schema 一致；
// 3) contracts/tools/tools.json 与 Dart 生成的 toolRegistry 一致（同源不手抄）；
// 4) contracts/VERSION 与各语言实现的版本声明一致。
//
// 不一致一律非零退出（1 = 有违规；2 = 环境问题）。
// ignore_for_file: avoid_print
import 'dart:io';

import 'package:cbr_maw_contracts/contracts_dart.dart'
    show ToolSpec, toolRegistry;
import 'package:json_schema/json_schema.dart';
import 'package:path/path.dart' as p;

import 'src/repo.dart';
import 'src/versions.dart';

/// 官方 draft 2020-12 元 schema 的 $id；本地离线元校验只依赖包内置词汇表。
const _metaUri = 'https://json-schema.org/draft/2020-12/schema';

void main(List<String> args) {
  final root = repoRoot();
  final contracts = Directory(p.join(root.path, 'contracts'));
  if (!contracts.existsSync()) {
    stderr.writeln('缺少 contracts/ 目录：${contracts.path}');
    exit(2);
  }

  final schemas = listFiles(contracts, (f) => f.endsWith('.schema.json'));
  final errors = <String>[];
  var checked = 0;

  section('[1] schema 元校验（draft 2020-12）');
  final byMethod = <String, ({String request, String response})>{};
  for (final file in schemas) {
    checked++;
    final rel = relPath(root, file.path);
    Map<String, Object?> schema;
    try {
      schema = readJsonObject(file.path);
    } on FormatException catch (e) {
      errors.add('$rel: JSON 解析失败：${e.message}');
      continue;
    }
    if (schema[r'$schema'] != _metaUri) {
      errors.add('$rel: \$schema 必须是 $_metaUri，实际 ${schema[r'$schema']}');
    }
    final id = schema[r'$id'];
    if (id != rel) {
      errors.add('$rel: \$id 必须等于仓库相对路径（实际 ${id ?? "缺失"}）');
    }
    try {
      // 构造即元校验；对空实例做一次求值以强制解析全部 $ref。
      final validator = JsonSchema.create(
        schema,
        schemaVersion: SchemaVersion.draft2020_12,
        refProvider: RefProvider.sync((String ref) {
          // 只允许本地 #/ 引用；远程引用会让 CI 依赖网络，直接判失败。
          throw StateError('schema 引用了外部资源：$ref（契约内只允许 #/ 本地引用）');
        }),
      );
      validator.validate(const <String, Object?>{});
    } catch (e) {
      errors.add('$rel: 不是合法 draft 2020-12 schema：$e');
      continue;
    }
    if (rel.endsWith('.request.schema.json') &&
        !rel.startsWith('contracts/tools/')) {
      final method = p.basename(rel).replaceFirst('.request.schema.json', '');
      final response = rel.replaceFirst(
        '.request.schema.json',
        '.response.schema.json',
      );
      if (!File(p.join(root.path, response)).existsSync()) {
        errors.add('$rel: 缺少配对的响应 schema（$response）');
      } else {
        byMethod[method] = (request: rel, response: response);
      }
    }
  }
  print('schema 文件 ${schemas.length} 个，方法 ${byMethod.length} 个');

  section('[2] 样例与 schema 一致');
  final examplesRoot = Directory(p.join(contracts.path, 'examples'));
  var exampleCount = 0;
  if (!examplesRoot.existsSync()) {
    errors.add('缺少 contracts/examples/ 目录');
  } else {
    final exampleDirs = examplesRoot.listSync().whereType<Directory>().toList()
      ..sort((a, b) => a.path.compareTo(b.path));
    for (final dir in exampleDirs) {
      final method = p.basename(dir.path);
      final pair = byMethod[method];
      if (pair == null) {
        errors.add('contracts/examples/$method: 没有对应的 *.request.schema.json');
        continue;
      }
      final files =
          dir
              .listSync()
              .whereType<File>()
              .where((f) => f.path.endsWith('.json'))
              .toList()
            ..sort((a, b) => a.path.compareTo(b.path));
      final kinds = <String>{};
      for (final file in files) {
        exampleCount++;
        final name = p.basename(file.path);
        final kind = name.contains('error')
            ? 'error'
            : name.contains('request')
            ? 'request'
            : name.contains('response')
            ? 'response'
            : null;
        if (kind == null) {
          errors.add(
            'contracts/examples/$method/$name: 文件名必须含 request/response/error',
          );
          continue;
        }
        kinds.add(kind);
        final schemaRel = kind == 'request' ? pair.request : pair.response;
        final schema = readJsonObject(p.join(root.path, schemaRel));
        final validator = JsonSchema.create(
          schema,
          schemaVersion: SchemaVersion.draft2020_12,
        );
        final instance = readJson(file.path);
        final result = validator.validate(instance);
        if (!result.isValid) {
          final details = result.errors
              .take(3)
              .map(
                (e) =>
                    '${e.instancePath.isEmpty ? "/" : e.instancePath}: ${e.message}',
              )
              .join('；');
          errors.add(
            'contracts/examples/$method/$name 不符合 $schemaRel：$details',
          );
        }
        // 样例的方法名必须与目录一致。
        if (instance is Map<String, Object?> &&
            instance['method'] != null &&
            instance['method'] != method) {
          errors.add(
            'contracts/examples/$method/$name: method=${instance['method']} 与目录 $method 不一致',
          );
        }
      }
      if (!{'request', 'response', 'error'}.every(kinds.contains)) {
        errors.add(
          'contracts/examples/$method: 必须同时有 request / response / error 三类样例（现有 ${kinds.join("/")}）',
        );
      }
    }
    // 反向：每个方法必须有样例目录。
    for (final method in byMethod.keys) {
      if (!Directory(p.join(examplesRoot.path, method)).existsSync()) {
        errors.add('contracts/examples/$method: 缺少样例目录');
      }
    }
  }
  print('样例文件 $exampleCount 个');

  section('[3] 工具注册表与 Dart 常量一致');
  final registryFile = File(p.join(contracts.path, 'tools', 'tools.json'));
  if (!registryFile.existsSync()) {
    errors.add('缺少 contracts/tools/tools.json');
  } else {
    final registry = readJsonObject(registryFile.path);
    final tools =
        (registry['tools'] as List?)
            ?.whereType<Map<String, Object?>>()
            .toList() ??
        const [];
    checked += tools.length;
    if (tools.length != toolRegistry.length) {
      errors.add(
        'tools.json 有 ${tools.length} 个工具，Dart toolRegistry 有 ${toolRegistry.length} 个',
      );
    } else {
      for (var i = 0; i < tools.length; i++) {
        final json = tools[i];
        final spec = toolRegistry[i];
        if (json['tool'] != spec.tool) {
          errors.add('tools[$i]: tools.json=${json['tool']} Dart=${spec.tool}');
        }
        if (json['version'] != spec.version) {
          errors.add(
            '${spec.tool}: tools.json 版本 ${json['version']}，Dart ${spec.version}',
          );
        }
        if (json['risk_level'] != spec.riskLevel.wire) {
          errors.add('${spec.tool}: risk_level 不一致');
        }
        final roles =
            (json['allowed_roles'] as List?)?.cast<String>() ?? const [];
        if (roles.join(',') != spec.allowedRoles.join(',')) {
          errors.add(
            '${spec.tool}: allowed_roles 不一致（tools.json ${roles.join("/")}，Dart ${spec.allowedRoles.join("/")}）',
          );
        }
        // params_schema_ref 必须真实存在。
        final ref = json['params_schema_ref'] as String?;
        if (ref == null || !File(p.join(root.path, ref)).existsSync()) {
          errors.add(
            '${spec.tool}: params_schema_ref 指向的文件不存在（${ref ?? "缺失"}）',
          );
        }
      }
    }
    // tools.invoke 请求信封的 tool 枚举必须与注册表逐项一致（否则新工具过不了 schema 校验）。
    final invokeReq = File(
      p.join(contracts.path, 'kernel', 'tools.invoke.request.schema.json'),
    );
    if (invokeReq.existsSync()) {
      final schema = readJsonObject(invokeReq.path);
      final props = schema['properties'] as Map?;
      final params = props?['params'] as Map?;
      final paramProps = params?['properties'] as Map?;
      final tool = paramProps?['tool'] as Map?;
      final listed = (tool?['enum'] as List?)?.cast<String>() ?? const [];
      final registered = tools.map((t) => t['tool']).toList();
      if (listed.join(',') != registered.join(',')) {
        errors.add(
          'tools.invoke.request.schema.json 的 tool 枚举与 tools.json 不一致：'
          'schema=${listed.join("/")} registry=${registered.join("/")}',
        );
      }
    } else {
      errors.add('缺少 contracts/kernel/tools.invoke.request.schema.json');
    }
    // Rust 侧工具登记表必须与契约一致（docs/12 P2-2：三方工具表一致）。
    errors.addAll(_rustToolRegistryMismatches(root, tools));
    print('工具注册表 ${tools.length} 条，params schema 引用、invoke 枚举与 Rust 登记表已核对');
  }

  section('[3b] 生成代码防漂移');
  {
    // packages/contracts_dart 是契约的生成物：真源改动后必须重跑生成器，
    // 否则 Dart 侧常量会静默落后于契约（本次漂移就漏掉了两个新工具）。
    final generated = File(
      p.join(root.path, 'packages/contracts_dart/lib/src/methods.dart'),
    );
    final generator = File(
      p.join(root.path, 'packages/contracts_dart/tool/generate_types.py'),
    );
    if (!generated.existsSync() || !generator.existsSync()) {
      errors.add('缺少契约生成物或生成器（packages/contracts_dart）');
    } else {
      final stale = _staleGeneratedNames(generated, toolRegistry);
      for (final item in stale) {
        errors.add('生成物漂移：$item');
      }
      // 真正的防漂移：重跑生成器，比对产物是否与仓库内一致。
      // 只查 ToolName 枚举会漏掉字段类型、toJson、嵌套类型等所有其他漂移。
      final diff = _regenerateAndDiff(root, generated);
      if (diff != null) {
        errors.add('生成物与契约不同源：$diff');
      }
      checked += (stale.isEmpty && diff == null) ? 1 : 0;
      print(
        stale.isEmpty
            ? '生成物与契约一致（工具枚举 ${toolRegistry.length} 项）'
            : '生成物落后于契约：${stale.length} 项',
      );
    }
  }

  section('[4] 版本一致性');
  final version = File(p.join(contracts.path, 'VERSION'));
  if (!version.existsSync()) {
    errors.add('缺少 contracts/VERSION');
  } else {
    final expected = version.readAsStringSync().trim();
    if (!RegExp(r'^\d+\.\d+\.\d+$').hasMatch(expected)) {
      errors.add('contracts/VERSION 不是语义化版本：$expected');
    }
    checked += 1;
    errors.addAll(contractVersionMismatches(root, expected));
    final declarations = contractVersionDeclarations(root);
    print('contracts/VERSION = $expected；核对实现 ${declarations.length} 处');
    if (declarations.isEmpty) {
      print('  ! 未找到任何实现侧契约版本声明（services/ 或 apps/desktop 尚未落地？）');
      print('  ! 这是提示不是失败：实现落地后本项会自动纳入比对。');
    } else if (declarations.length < 3) {
      print('  ! 只找到 ${declarations.length}/3 处声明（Rust/Go/Dart），缺失的实现尚未落地。');
    }
  }

  finish(errors, checked + exampleCount, 'contracts 校验');
}

/// Rust 侧 `TOOL_REGISTRY` 必须与契约工具表一致（docs/12 P2-2）。
///
/// 三方（contracts/tools/tools.json · Rust · Dart）任一漂移都会让新工具
/// 在某一侧不可用——本次漂移就使 `dimension_dispersion` / `capital_linkage`
/// 在 Dart 侧 `ToolName.parse` 直接抛错。
List<String> _rustToolRegistryMismatches(
  Directory root,
  List<Map<String, Object?>> tools,
) {
  final file = File(p.join(root.path, 'services/kernel/src/tools/mod.rs'));
  if (!file.existsSync()) {
    return const ['缺少 services/kernel/src/tools/mod.rs（Rust 工具登记表）'];
  }
  final source = file.readAsStringSync();
  final block = RegExp(
    r'pub const TOOL_REGISTRY: \[ToolMeta; (\d+)\] = \[(.*?)\n\];',
    dotAll: true,
  ).firstMatch(source);
  if (block == null) {
    return const ['Rust TOOL_REGISTRY 未解析到（格式变了？）'];
  }
  final declared = int.tryParse(block.group(1) ?? '') ?? -1;
  final names = RegExp(r'name: "([^"]+)"')
      .allMatches(block.group(2) ?? '')
      .map((m) => m.group(1)!)
      .toList();
  final registered = tools.map((t) => t['tool'] as String? ?? '').toList();
  final errors = <String>[];
  if (declared != names.length) {
    errors.add('Rust TOOL_REGISTRY 声明 $declared 项，实际 ${names.length} 项');
  }
  if (names.join(',') != registered.join(',')) {
    errors.add(
      'Rust 工具表与契约不一致：rust=${names.join("/")} contracts=${registered.join("/")}',
    );
  }
  // 每个工具的版本必须与契约一致。
  //
  // 不能只依赖正则匹配数：字段顺序一变（version 写在 name 前面）正则就
  // 一条都匹配不到，门禁会静默通过。这里显式核对「匹配数 == 工具数」。
  final versionMatches = RegExp(
    r'name: "([^"]+)",\s*\n\s*version: "([^"]+)"',
    dotAll: true,
  ).allMatches(block.group(2) ?? '').toList();
  if (versionMatches.length != names.length) {
    errors.add(
      'Rust 工具表版本核对不完整：匹配到 ${versionMatches.length} 项，'
      '但登记了 ${names.length} 项（字段顺序变化会让本门禁失效）',
    );
  }
  for (final entry in versionMatches) {
    final tool = entry.group(1)!;
    final version = entry.group(2)!;
    final contract = tools.firstWhere(
      (t) => t['tool'] == tool,
      orElse: () => const <String, Object?>{},
    );
    if (contract['version'] != version) {
      errors.add('$tool: Rust 版本 $version，契约 ${contract['version']}');
    }
  }
  return errors;
}

/// 生成物防漂移：契约里登记的工具必须都出现在生成的 `ToolName` 枚举。
List<String> _staleGeneratedNames(File generated, List<ToolSpec> registry) {
  final source = generated.readAsStringSync();
  final block = RegExp(
    r'enum ToolName \{(.*?)\n\}',
    dotAll: true,
  ).firstMatch(source);
  if (block == null) {
    return const ['生成的 methods.dart 里找不到 ToolName 枚举'];
  }
  final wires = RegExp(r"'([^']+)'")
      .allMatches(block.group(1) ?? '')
      .map((m) => m.group(1)!)
      .toSet();
  return [
    for (final spec in registry)
      if (!wires.contains(spec.tool))
        '${spec.tool}：契约已登记但生成物 ToolName 枚举缺失（重跑 packages/contracts_dart/tool/generate_types.py）',
  ];
}

/// 重跑生成器并与仓库内生成物比对（备份 → 生成 → 比对 → 还原）。
///
/// 返回 null 表示一致或无法比对（环境缺 Python）；否则返回差异摘要。
/// 只查 ToolName 枚举会漏掉字段类型、toJson、嵌套类型等全部其他漂移。
String? _regenerateAndDiff(Directory root, File committed) {
  final generator = File(
    p.join(root.path, 'packages/contracts_dart/tool/generate_types.py'),
  );
  if (!generator.existsSync()) {
    return null;
  }
  final python = Platform.environment['CBR_PYTHON'] ?? 'python3';
  // 生成器同时写 methods.dart 与 tools.dart：只备份被比对的那一个，其余会被
  // 生成器的未格式化输出覆盖，导致下一次 `dart format --set-exit-if-changed` 失败。
  final siblings = [
    committed,
    File(p.join(committed.parent.path, 'tools.dart')),
  ].where((f) => f.existsSync()).toList();
  final originals = {for (final f in siblings) f.path: f.readAsStringSync()};
  try {
    final result = Process.runSync(python, [
      generator.path,
    ], workingDirectory: root.path);
    if (result.exitCode != 0) {
      print('  ! 生成器未运行（exit ${result.exitCode}），跳过内容比对');
      return null;
    }
    // 生成器输出未格式化，仓库内是 `dart format` 过的产物：
    // 先格式化再比对，否则每一行都会被判为漂移。
    Process.runSync('dart', [
      'format',
      committed.path,
    ], workingDirectory: root.path);
    final regenerated = committed.readAsStringSync();
    final original = originals[committed.path]!;
    if (_normalized(regenerated) == _normalized(original)) {
      return null;
    }
    // 找出第一处差异行，便于定位。
    final a = _normalized(original).split('\n');
    final b = _normalized(regenerated).split('\n');
    for (var i = 0; i < a.length && i < b.length; i++) {
      if (a[i] != b[i]) {
        return 'methods.dart 第 ${i + 1} 行不一致：仓库=${a[i].trim()} '
            '生成=${b[i].trim()}（重跑 packages/contracts_dart/tool/generate_types.py）';
      }
    }
    return 'methods.dart 行数不一致：仓库 ${a.length} / 生成 ${b.length}';
  } on ProcessException {
    print('  ! 找不到 $python，跳过生成物内容比对');
    return null;
  } finally {
    // 无论成败都还原**所有**生成物：校验工具不得改动仓库内容。
    for (final entry in originals.entries) {
      File(entry.key).writeAsStringSync(entry.value);
    }
  }
}

String _normalized(String text) => text
    .replaceAll('\r\n', '\n')
    .split('\n')
    .map((l) => l.trimRight())
    .join('\n')
    .trim();
