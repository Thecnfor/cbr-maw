// 黄金向量（contracts/golden-vectors/*.json）的生成与校验。
//
// 原则：**已存在则校验，不覆盖**。
//   dart run tools/gen_golden_vectors.dart            # 校验（默认）
//   dart run tools/gen_golden_vectors.dart --write    # 用旧 Python 重新生成后校验
//
// 校验三件事：
//   1. Dart 侧 EvidenceHash 对每条向量重算 canonical_json / inputs_hash /
//      evidence_id / evidence_hash，必须与文件逐字节一致；
//   2. 旧 Python 实现（cbr.tools.base）对同一输入重算，必须与文件一致
//      —— 这是"与旧版逐字节一致"的真正判据；
//   3. 向量的 contract_version 与 contracts/VERSION 一致。
//
// 退出码：0 通过；1 有不一致；2 环境缺失（旧 Python 源码或解释器不可用）。
// ignore_for_file: avoid_print
import 'dart:convert';
import 'dart:io';

import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:path/path.dart' as p;

import 'src/repo.dart';

/// 旧版源码根（只读语义参考）。
const _legacySrc = '/mnt/shared/recently/commorcial/src';

/// 黄金向量文件（其余参考向量由 data/seed/gen_tool_golden.py 在真实库上生成）。
const _hashVectors = 'contracts/golden-vectors/hash_vectors.json';

void main(List<String> args) {
  final write = args.contains('--write') || args.contains('--force');
  final root = repoRoot();
  final file = File(p.join(root.path, _hashVectors));

  if (write) {
    final generator = File(
      p.join(
        root.path,
        'packages/contracts_dart/tool/generate_golden_vectors.py',
      ),
    );
    if (!generator.existsSync()) {
      stderr.writeln('缺少生成器 ${generator.path}（契约包尚未落地？）');
      exit(2);
    }
    print('调用旧 Python 生成器：${generator.path}');
    final result = Process.runSync(
      'python3',
      [generator.path],
      environment: {
        'CBR_LEGACY_SRC': Platform.environment['CBR_LEGACY_SRC'] ?? _legacySrc,
      },
    );
    stdout.write(result.stdout);
    stderr.write(result.stderr);
    if (result.exitCode != 0) {
      stderr.writeln('生成失败（exit ${result.exitCode}）。');
      exit(2);
    }
  }

  if (!file.existsSync()) {
    stderr.writeln('缺少 $_hashVectors。先用 --write 生成。');
    exit(2);
  }

  final doc = readJsonObject(file.path);
  final contractVersion = File(p.join(root.path, 'contracts/VERSION'))
      .readAsStringSync()
      .trim();
  final errors = <String>[];

  section('[1] 版本');
  if (doc['contract_version'] != contractVersion) {
    errors.add(
      'golden-vectors 的 contract_version=${doc['contract_version']}，contracts/VERSION=$contractVersion',
    );
  } else {
    print('ok  contract_version = $contractVersion');
  }

  final vectors = (doc['vectors'] as List<Object?>? ?? const [])
      .whereType<Map<String, Object?>>()
      .toList();
  if (vectors.isEmpty) {
    stderr.writeln('hash_vectors.json 里没有 vectors。');
    exit(2);
  }

  section('[2] Dart 重算（${vectors.length} 条）');
  for (final v in vectors) {
    final name = v['name'] as String? ?? '(unnamed)';
    final tool = v['tool'] as String;
    final version = v['version'] as String;
    final asOf = v['as_of'] as String;
    final params = (v['params'] as Map).cast<String, Object?>();
    final payload = (v['evidence_payload'] as Map).cast<String, Object?>();

    final canonical = canonicalJson({
      'tool': tool,
      'version': version,
      'as_of': asOf,
      'params': params,
    });
    final inputsHash = EvidenceHash.inputsHash(
      tool: tool,
      version: version,
      asOf: asOf,
      params: params,
    );
    final evidenceId = EvidenceHash.evidenceId(
      tool: tool,
      version: version,
      inputsHash: inputsHash,
    );
    final evidenceHash = EvidenceHash.evidenceHash(payload);

    void check(String field, String actual, Object? expected) {
      if (actual != expected) {
        errors.add('[$name] $field 不一致：Dart=$actual 文件=$expected');
      }
    }

    check('canonical_json', canonical, v['canonical_json']);
    check('inputs_hash', inputsHash, v['inputs_hash']);
    check('evidence_id', evidenceId, v['evidence_id']);
    check('evidence_hash', evidenceHash, v['evidence_hash']);
  }
  print(errors.isEmpty ? 'ok  全部一致' : 'BAD ${errors.length} 处不一致');

  section('[3] 旧 Python 重算');
  final python = _pythonCheck(root, vectors);
  if (python == null) {
    stderr.writeln('无法用旧 Python 复算（解释器或旧源码不可用），本次只做 Dart 侧校验。');
    stderr.writeln('按红线要求，"与旧版逐字节一致"必须由 Python 侧确认后再放行。');
    finish(errors, vectors.length, '黄金向量校验（仅 Dart 侧）');
  }
  for (final entry in python.entries) {
    final v = vectors.firstWhere((v) => v['name'] == entry.key);
    if (entry.value['inputs_hash'] != v['inputs_hash']) {
      errors.add(
        '[${entry.key}] Python inputs_hash=${entry.value['inputs_hash']} 文件=${v['inputs_hash']}',
      );
    }
    if (entry.value['evidence_id'] != v['evidence_id']) {
      errors.add(
        '[${entry.key}] Python evidence_id=${entry.value['evidence_id']} 文件=${v['evidence_id']}',
      );
    }
    if (entry.value['evidence_hash'] != v['evidence_hash']) {
      errors.add(
        '[${entry.key}] Python evidence_hash=${entry.value['evidence_hash']} 文件=${v['evidence_hash']}',
      );
    }
  }
  print('ok  Python 复算 ${python.length} 条');

  finish(errors, vectors.length, '黄金向量校验');
}

/// 用旧 Python 实现对每条向量重算；环境缺失返回 null（非数据不一致）。
Map<String, Map<String, String>>? _pythonCheck(
  Directory root,
  List<Map<String, Object?>> vectors,
) {
  final script =
      '''
import json, sys
sys.path.insert(0, ${jsonEncode(Platform.environment['CBR_LEGACY_SRC'] ?? _legacySrc)})
try:
    from cbr.tools.base import canonical_json, compute_inputs_hash, sha256_text, to_native
except Exception as exc:
    print(json.dumps({"error": str(exc)})); sys.exit(0)
from datetime import date
vectors = json.load(open(sys.argv[1], encoding="utf-8"))
out = {}
for v in vectors:
    params = to_native(v["params"])
    payload = to_native(v["evidence_payload"])
    ih = compute_inputs_hash(v["tool"], v["version"], date.fromisoformat(v["as_of"]), params)
    eid = "ev_" + sha256_text(canonical_json({"tool": v["tool"], "version": v["version"], "inputs_hash": ih}))[:16]
    out[v["name"]] = {"inputs_hash": ih, "evidence_id": eid, "evidence_hash": sha256_text(canonical_json(payload))}
print(json.dumps(out, ensure_ascii=False))
''';
  final tmp = File(p.join(Directory.systemTemp.path, 'cbr_golden_in.json'))
    ..writeAsStringSync(jsonEncode(vectors));
  try {
    final result = Process.runSync('python3', [
      '-c',
      script,
      tmp.path,
    ], stdoutEncoding: utf8);
    if (result.exitCode != 0) {
      stderr.write(result.stderr);
      return null;
    }
    final decoded = jsonDecode(result.stdout as String);
    if (decoded is Map<String, Object?> && decoded['error'] != null) {
      stderr.writeln('旧 Python 不可用：${decoded['error']}');
      return null;
    }
    if (decoded is! Map<String, Object?>) {
      return null;
    }
    return {
      for (final entry in decoded.entries)
        entry.key: (entry.value as Map).cast<String, String>(),
    };
  } finally {
    tmp.deleteSync();
  }
}
