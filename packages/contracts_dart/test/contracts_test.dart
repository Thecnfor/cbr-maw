import 'dart:convert';
import 'dart:io';

import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:test/test.dart';

/// 契约根目录（packages/contracts_dart/test → 仓库根）。
Directory get _repoRoot {
  var dir = Directory.current;
  while (dir.parent.path != dir.path) {
    if (Directory('${dir.path}/contracts').existsSync()) {
      return dir;
    }
    dir = dir.parent;
  }
  throw StateError('未找到 contracts/ 目录');
}

File _contractFile(String relative) => File('${_repoRoot.path}/$relative');

Map<String, Object?> _readJson(String relative) {
  final decoded = jsonDecode(_contractFile(relative).readAsStringSync());
  if (decoded is! Map<String, Object?>) {
    throw StateError('$relative 顶层不是对象');
  }
  return decoded;
}

void main() {
  group('工具注册表', () {
    test('Dart 常量与 contracts/tools/tools.json 一致', () {
      final json = _readJson('contracts/tools/tools.json');
      final tools = json['tools'];
      if (tools is! List<Object?>) {
        throw StateError('tools 不是数组');
      }
      expect(toolRegistry.length, tools.length);
      for (var i = 0; i < tools.length; i++) {
        final entry = tools[i];
        if (entry is! Map<String, Object?>) {
          throw StateError('tools[$i] 不是对象');
        }
        final spec = toolRegistry[i];
        expect(spec.tool, entry['tool']);
        expect(spec.version, entry['version']);
        expect(spec.riskLevel.wire, entry['risk_level']);
        expect(spec.allowedRoles, entry['allowed_roles']);
        expect(spec.paramsSchemaRef, entry['params_schema_ref']);
        expect(spec.returns.cast<String, String?>(), entry['returns']);
        expect(spec.deterministic, entry['deterministic']);
        expect(spec.legacyRef, entry['legacy_ref']);
        expect(spec.description, entry['description']);
        expect(spec.defaultParams, entry['default_params']);
      }
    });

    test('九个工具齐备且 allowed_roles 覆盖三种角色', () {
      expect(toolRegistry.map((s) => s.tool).toList(), [
        'risk_measure',
        'systemic_risk',
        'capital_flow',
        'funding_cost',
        'scenario',
        'forecast',
        'knowledge_search',
        'dimension_dispersion',
        'capital_linkage',
      ]);
      for (final spec in toolRegistry) {
        expect(spec.deterministic, isTrue, reason: '${spec.tool} 必须是确定性工具');
        expect(spec.riskLevel, ToolRiskLevel.l0);
        expect(spec.allowedRoles, isNotEmpty);
        expect(
          spec.allowedRoles.every(
            (r) => const {'regulator', 'investor', 'financing'}.contains(r),
          ),
          isTrue,
          reason: '${spec.tool} 的角色取值必须来自 roles.yaml',
        );
      }
      final funding = toolRegistry.firstWhere((s) => s.tool == 'funding_cost');
      expect(funding.allowedRoles, ['financing']);
      expect(funding.allowsRole('regulator'), isFalse);
    });
  });

  group('黄金向量', () {
    late Map<String, Object?> doc;

    setUpAll(() {
      doc = _readJson('contracts/golden-vectors/hash_vectors.json');
    });

    test('向量条数不少于 8 条', () {
      final vectors = doc['vectors'];
      expect(vectors, isA<List<Object?>>());
      expect((vectors! as List<Object?>).length, greaterThanOrEqualTo(8));
    });

    test('Dart 规范化 JSON + sha256 与旧版 Python 逐字节一致', () {
      final vectors = doc['vectors']! as List<Object?>;
      for (final raw in vectors) {
        final vector = raw! as Map<String, Object?>;
        final name = vector['name'];
        final tool = vector['tool']! as String;
        final version = vector['version']! as String;
        final asOf = vector['as_of']! as String;
        final params = vector['params']! as Map<String, Object?>;

        // 规范化 JSON 逐字节一致。
        expect(
          canonicalJson({
            'tool': tool,
            'version': version,
            'as_of': asOf,
            'params': params,
          }),
          vector['canonical_json'],
          reason: '$name 的 canonical_json 不一致',
        );

        // inputs_hash 一致。
        final inputsHash = EvidenceHash.inputsHash(
          tool: tool,
          version: version,
          asOf: asOf,
          params: params,
        );
        expect(
          inputsHash,
          vector['inputs_hash'],
          reason: '$name 的 inputs_hash 不一致',
        );

        // evidence_id 一致。
        expect(
          EvidenceHash.evidenceId(
            tool: tool,
            version: version,
            inputsHash: inputsHash,
          ),
          vector['evidence_id'],
          reason: '$name 的 evidence_id 不一致',
        );

        // evidence_hash 一致。
        final payload = vector['evidence_payload']! as Map<String, Object?>;
        expect(
          EvidenceHash.evidenceHash(payload),
          vector['evidence_hash'],
          reason: '$name 的 evidence_hash 不一致',
        );
      }
    });

    test('浮点边界排版与 Python repr 一致', () {
      expect(pythonReprDouble(0.1), '0.1');
      expect(pythonReprDouble(1e16), '1e+16');
      expect(pythonReprDouble(1e15), '1000000000000000.0');
      expect(pythonReprDouble(1e-5), '1e-05');
      expect(pythonReprDouble(1e-4), '0.0001');
      expect(pythonReprDouble(-0.0), '-0.0');
      expect(pythonReprDouble(0.0), '0.0');
      expect(pythonReprDouble(double.nan), 'null');
      expect(pythonReprDouble(double.infinity), 'null');
      expect(pythonReprDouble(1200.0), '1200.0');
    });
  });

  group('错误码', () {
    test('错误码表与 contracts/README.md §2 一致', () {
      const expected = {
        -32700: 'E_PARSE',
        -32600: 'E_INVALID_REQUEST',
        -32601: 'E_METHOD_NOT_FOUND',
        -32602: 'E_INVALID_PARAMS',
        -32603: 'E_INTERNAL',
        -32001: 'E_PLATFORM_UNSUPPORTED',
        -32002: 'E_NOT_AUTHORIZED',
        -32003: 'E_SOURCE_UNAVAILABLE',
        -32004: 'E_DATA_MISSING',
        -32005: 'E_CONTRACT_MISMATCH',
        -32006: 'E_RATE_LIMITED',
        -32007: 'E_TIMEOUT',
        -32008: 'E_NOT_INITIALIZED',
        -32009: 'E_PERMISSION_DENIED',
      };
      expect(RpcErrorKind.values.length, expected.length);
      for (final entry in expected.entries) {
        expect(RpcErrorKind.fromCode(entry.key).kind, entry.value);
        expect(RpcErrorKind.fromKind(entry.value).code, entry.key);
      }
    });

    test('错误对象解析即校验', () {
      final error = RpcError.parse({
        'code': -32004,
        'message': '必需数据缺失',
        'data': {
          'kind': 'E_DATA_MISSING',
          'retryable': false,
          'detail': {'reason': '序列无观测'},
        },
      });
      expect(error.kind, RpcErrorKind.dataMissing);
      expect(error.retryable, isFalse);
      expect(error.detail['reason'], '序列无观测');

      expect(
        () => RpcError.parse({
          'code': -32004,
          'message': 'x',
          'data': {
            'kind': 'E_NOT_A_KIND',
            'retryable': false,
            'detail': <String, Object?>{},
          },
        }),
        throwsA(isA<ContractFormatException>()),
      );
    });
  });

  group('信封', () {
    test('请求信封解析', () {
      final request = RpcRequest.parse({
        'jsonrpc': '2.0',
        'id': '1',
        'method': 'sources.list',
        'params': {'include_disabled': false},
      });
      expect(request.id, '1');
      expect(request.method, 'sources.list');
      expect(request.params['include_disabled'], isFalse);
    });

    test('响应信封按 error 字段分流', () {
      final ok = RpcResponse.parse({
        'jsonrpc': '2.0',
        'id': '1',
        'result': {'sources': <Object?>[]},
      });
      expect(ok, isA<RpcSuccessResponse>());

      final err = RpcResponse.parse({
        'jsonrpc': '2.0',
        'id': '1',
        'error': {
          'code': -32602,
          'message': '参数不合法',
          'data': {
            'kind': 'E_INVALID_PARAMS',
            'retryable': false,
            'detail': {'reason': 'view 不在白名单内'},
          },
        },
      });
      expect(err, isA<RpcErrorResponse>());
      expect((err as RpcErrorResponse).error.kind, RpcErrorKind.invalidParams);
    });
  });

  group('方法参数与结果', () {
    test('tools.invoke 参数解析', () {
      final params = ToolsInvokeParams.parse({
        'tool': 'risk_measure',
        'params': {'series_id': 'market.cn_equity.csi300'},
        'idempotency_key': 'idem_1',
      });
      expect(params.tool, ToolName.riskMeasure);
      expect(params.idempotencyKey, 'idem_1');
      expect(params.toJson()['tool'], 'risk_measure');
    });

    test('枚举越界在解析处失败', () {
      expect(
        () => ToolsInvokeParams.parse({
          'tool': 'not_a_tool',
          'params': <String, Object?>{},
          'idempotency_key': 'idem_1',
        }),
        throwsA(isA<ContractFormatException>()),
      );
    });

    test('缺必填字段在解析处失败', () {
      expect(
        () => SourcesProbeParams.parse({'timeout_s': 20}),
        throwsA(isA<ContractFormatException>()),
      );
    });

    test('db.query 视图白名单越界失败', () {
      expect(
        () => DbQueryParams.parse({
          'view': 'raw_sql',
          'as_of': '2026-06-30T18:00:00+08:00',
        }),
        throwsA(isA<ContractFormatException>()),
      );
    });
  });

  group('样例', () {
    test('每个方法的样例文件齐备（≥2 组，含错误样例）', () {
      final examples = Directory('${_repoRoot.path}/contracts/examples');
      final methods = Directory('${_repoRoot.path}/contracts/kernel')
          .listSync()
          .whereType<File>()
          .map((f) => f.uri.pathSegments.last)
          .where((n) => n.endsWith('.request.schema.json'))
          .map((n) => n.replaceAll('.request.schema.json', ''))
          .toSet();
      final collectorMethods =
          Directory('${_repoRoot.path}/contracts/collector')
              .listSync()
              .whereType<File>()
              .map((f) => f.uri.pathSegments.last)
              .where((n) => n.endsWith('.request.schema.json'))
              .map((n) => n.replaceAll('.request.schema.json', ''))
              .toSet();
      final all = {...methods, ...collectorMethods};
      expect(all.length, greaterThanOrEqualTo(17));

      for (final method in all) {
        final dir = Directory('${examples.path}/$method');
        expect(dir.existsSync(), isTrue, reason: '$method 缺少样例目录');
        final files = dir.listSync().whereType<File>().toList();
        expect(
          files.length,
          greaterThanOrEqualTo(2),
          reason: '$method 样例不足 2 组',
        );
        final errors = files.where((f) => f.path.contains('error')).toList();
        expect(errors, isNotEmpty, reason: '$method 缺少错误样例');
      }
    });

    test('每个方法的 request/response schema 与样例目录齐备', () {
      for (final domain in const ['collector', 'kernel']) {
        final dir = Directory('${_repoRoot.path}/contracts/$domain');
        for (final file in dir.listSync().whereType<File>()) {
          final name = file.uri.pathSegments.last;
          if (!name.endsWith('.request.schema.json')) {
            continue;
          }
          final method = name.replaceAll('.request.schema.json', '');
          expect(
            File('${dir.path}/$method.response.schema.json').existsSync(),
            isTrue,
            reason: '$domain/$method 缺 response schema',
          );
          final schema = _readJson(
            'contracts/$domain/$method.request.schema.json',
          );
          expect(schema[r'$schema'], contains('2020-12'));
          final properties = schema['properties']! as Map<String, Object?>;
          final methodNode = properties['method']! as Map<String, Object?>;
          expect(methodNode['const'], method);
          expect(
            Directory('${_repoRoot.path}/contracts/examples/$method')
                .existsSync(),
            isTrue,
            reason: '$method 缺样例目录',
          );
        }
      }
    });

    test(r'核心生命周期方法在 collector/ 与 kernel/ 内容一致（仅 $id 不同）', () {
      for (final method in const ['initialize', 'shutdown', 'ping']) {
        for (final kind in const ['request', 'response']) {
          final a = _readJson('contracts/collector/$method.$kind.schema.json');
          final b = _readJson('contracts/kernel/$method.$kind.schema.json');
          expect(a.remove(r'$id'), isNotNull);
          expect(b.remove(r'$id'), isNotNull);
          expect(a, b, reason: '$method.$kind 在两域不一致');
        }
      }
    });

    test('样例 JSON 均可解析且信封结构合法', () {
      final examples = Directory('${_repoRoot.path}/contracts/examples');
      for (final dir in examples.listSync().whereType<Directory>()) {
        for (final file in dir.listSync().whereType<File>()) {
          final decoded = jsonDecode(file.readAsStringSync());
          expect(decoded, isA<Map<String, Object?>>(), reason: file.path);
          final map = decoded as Map<String, Object?>;
          expect(map['jsonrpc'], '2.0', reason: file.path);
          if (map.containsKey('error')) {
            final error = RpcError.parse(map['error']);
            expect(
              error.detail.containsKey('reason'),
              isTrue,
              reason: file.path,
            );
          }
        }
      }
    });
  });
}
