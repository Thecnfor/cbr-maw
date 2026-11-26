import 'dart:convert';

import 'package:crypto/crypto.dart';

import 'canonical_json.dart';

/// 三级证据哈希（contracts/README.md §6），与旧版 Python 逐字节一致。
///
/// - [inputsHash]：工具入参（含 series/参数/时点）的 sha256，64 位小写 hex；
/// - [evidenceId]：`ev_` + `sha256({tool, version, inputs_hash})` 前 16 位 hex；
/// - [evidenceHash]：证据载荷的 sha256，64 位小写 hex。
abstract final class EvidenceHash {
  /// 工具入参哈希。
  ///
  /// 载荷结构与旧版 `cbr.tools.base.compute_inputs_hash` 一致：
  /// `{tool, version, as_of, params}`，`as_of` 为 `YYYY-MM-DD`。
  static String inputsHash({
    required String tool,
    required String version,
    required String asOf,
    required Map<String, Object?> params,
  }) => sha256Hex(
    canonicalJson({
      'tool': tool,
      'version': version,
      'as_of': asOf,
      'params': params,
    }),
  );

  /// 证据 ID。
  static String evidenceId({
    required String tool,
    required String version,
    required String inputsHash,
  }) {
    final digest = sha256Hex(
      canonicalJson({
        'tool': tool,
        'version': version,
        'inputs_hash': inputsHash,
      }),
    );
    return 'ev_${digest.substring(0, 16)}';
  }

  /// 证据载荷哈希。
  static String evidenceHash(Map<String, Object?> payload) =>
      sha256Hex(canonicalJson(payload));

  /// 规范化 JSON 的 sha256（64 位小写 hex）。
  static String sha256Hex(String text) =>
      sha256.convert(utf8.encode(text)).toString();
}
