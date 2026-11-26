/// 证据黑板：三级去重 + 别名解析（对齐 docs/03 §1.6.4 与旧 `orchestration/blackboard.py`）。
library;

import 'dart:convert';

import 'package:crypto/crypto.dart';

import '../models/domain.dart';

/// 规范化 JSON（键排序、紧凑分隔符、保留中文），保证哈希可复现。
String canonicalJson(Object? value) {
  final buffer = StringBuffer();
  void write(Object? v) {
    if (v == null) {
      buffer.write('null');
    } else if (v is bool || v is num) {
      buffer.write(v);
    } else if (v is String) {
      buffer.write(jsonEncode(v));
    } else if (v is List<Object?>) {
      buffer.write('[');
      for (var i = 0; i < v.length; i++) {
        if (i > 0) {
          buffer.write(',');
        }
        write(v[i]);
      }
      buffer.write(']');
    } else if (v is Map<Object?, Object?>) {
      final keys = v.keys.map((k) => k.toString()).toList()..sort();
      buffer.write('{');
      for (var i = 0; i < keys.length; i++) {
        if (i > 0) {
          buffer.write(',');
        }
        buffer.write(jsonEncode(keys[i]));
        buffer.write(':');
        write(v[keys[i]]);
      }
      buffer.write('}');
    } else {
      buffer.write(jsonEncode(v.toString()));
    }
  }

  write(value);
  return buffer.toString();
}

/// sha256 hex。
String sha256Hex(String text) => sha256.convert(utf8.encode(text)).toString();

/// 黑板：只存 [Evidence]，去重后保留最早 id 为规范 id。
final class EvidenceBlackboard {
  final Map<String, Evidence> _byCanonical = {};
  final Map<String, String> _aliases = {};
  final Map<String, String> _keyById = {};
  var _duplicates = 0;

  /// 规范去重键 → 证据。
  Map<String, Evidence> get index => Map.unmodifiable(_byCanonical);

  /// evidenceId → 证据（含别名，供核验与 UI 引用）。
  Map<String, Evidence> get evidenceById => {
    for (final entry in _keyById.entries)
      if (_byCanonical[entry.value] != null)
        entry.key: _byCanonical[entry.value]!,
  };

  /// 去重命中次数。
  int get duplicateCount => _duplicates;

  /// 全部证据。
  List<Evidence> get items => _byCanonical.values.toList();

  /// 入板；返回规范 id（同内容不同 id 归一）。
  String add(Evidence evidence) {
    final key = _canonicalKey(evidence);
    final existing = _byCanonical[key];
    if (existing != null) {
      _duplicates++;
      _aliases[evidence.evidenceId] = existing.evidenceId;
      _keyById[evidence.evidenceId] = key;
      return existing.evidenceId;
    }
    _byCanonical[key] = evidence;
    _aliases[evidence.evidenceId] = evidence.evidenceId;
    _keyById[evidence.evidenceId] = key;
    return evidence.evidenceId;
  }

  /// 批量入板。
  void addAll(Iterable<Evidence> evidence) => evidence.forEach(add);

  /// 把任意 id 解析到规范 id（未登记返回原值）。
  String resolveId(String evidenceId) => _aliases[evidenceId] ?? evidenceId;

  /// 按 id 取证据（自动经别名解析）。
  Evidence? lookup(String evidenceId) {
    final key = _keyById[evidenceId];
    return key == null ? null : _byCanonical[key];
  }

  /// 三级去重键：hash > tool.inputs_hash > 内容哈希。
  String _canonicalKey(Evidence evidence) {
    if (evidence.hash.isNotEmpty) {
      return 'hash:${evidence.hash}';
    }
    final inputsHash = evidence.tool?.inputsHash;
    if (inputsHash != null && inputsHash.isNotEmpty) {
      return 'tool:${evidence.tool!.name}@${evidence.tool!.version}:$inputsHash';
    }
    return 'content:${sha256Hex(canonicalJson(_contentPayload(evidence)))}';
  }

  Map<String, Object?> _contentPayload(Evidence e) => {
    'kind': e.kind.wire,
    'as_of': _date(e.asOf),
    'title': e.title,
    'summary': e.summary,
    'value': e.value,
    'unit': e.unit,
    'payload': e.payload,
    'source': e.source.toJson(),
    'tool': e.tool?.toJson(),
  };
}

/// `YYYY-MM-DD`。
String _date(DateTime value) => value.toIso8601String().substring(0, 10);
