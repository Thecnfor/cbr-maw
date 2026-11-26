// 端到端集成测试：真实 sidecar 子进程 + 真实文件（docs/23 §7 的链路）。
//
// 运行：cd apps/desktop && flutter test integration_test/e2e_sidecar_test.dart
// 依赖环境变量：
//   CBR_COLLECTOR_BIN  collector 可执行体路径（缺失则跳过，不伪造）
//   CBR_E2E_DIR        工作目录（默认 /tmp/cbre2e）
//   CBR_E2E_ZIP        真实 ZIP 路径（缺失则跳过该用例）
import 'dart:io';

import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:cbr_maw/data/sidecar/sidecar_supervisor.dart';
import 'package:cbr_maw/data/sidecar/stdio_transport.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final bin = Platform.environment['CBR_COLLECTOR_BIN'];
  final root = Platform.environment['CBR_E2E_DIR'] ?? '/tmp/cbre2e';
  final zipPath = Platform.environment['CBR_E2E_ZIP'];

  // 自备环境：创建工作区目录并复制来源台账，避免依赖外部 /tmp 状态
  setUpAll(() async {
    if (bin == null) return;
    for (final d in ['$root/ws', '$root/data', '$root/res/configs']) {
      await Directory(d).create(recursive: true);
    }
    final ledger = File('../services/collector/configs/sources.json');
    if (ledger.existsSync()) {
      await ledger.copy('$root/res/configs/sources.json');
    }
  });

  SidecarSupervisor buildSupervisor() => SidecarSupervisor(
    transportFactory: () => StdioSidecarTransport(
      executable: bin!,
      arguments: [
        '--workspace',
        '$root/ws',
        '--data-home',
        '$root/data',
        '--resource-home',
        '$root/res',
        '--log-level',
        'warn',
      ],
    ),
    clientVersion: '0.1.0',
    contractVersion: '1.0.0',
    workspace: '$root/ws',
    dataHome: '$root/data',
    resourceHome: '$root/res',
  );

  test('sidecar 握手并返回来源台账', () async {
    // ignore: avoid_print
    print('E2E env: bin=$bin root=$root zip=$zipPath');
    if (bin == null) {
      markTestSkipped('CBR_COLLECTOR_BIN 未设置');
      return;
    }
    final sup = buildSupervisor();
    addTearDown(sup.shutdown);
    final init = await sup.sendTyped('initialize', {
      'contract_version': '1.0.0',
      'client_version': '0.1.0',
      'workspace': '$root/ws',
      'data_home': '$root/data',
      'resource_home': '$root/res',
      'capabilities': <String>[],
    }, (p) => p as Map<String, Object?>).first;
    expect(
      init.isSuccess,
      isTrue,
      reason: init is Failure<Map<String, Object?>>
          ? 'kind=${init.error.kind.kind} msg=${init.error.message} detail=${init.error.detail}'
          : 'ok (bin=$bin zip=$zipPath root=$root)',
    );
    final payload = init.valueOrThrow;
    expect(payload['sidecar'], 'collector');
    expect(payload['contract_version'], '1.0.0');

    final listed = await sup.sendTyped('sources.list', {
      'include_disabled': false,
    }, (p) => (p! as Map<String, Object?>)['sources']! as List).first;
    expect(listed.isSuccess, isTrue, reason: '$listed');
    expect(listed.valueOrThrow, isNotEmpty);
  }, timeout: const Timeout(Duration(minutes: 3)));

  test('真实 CSV 清洗：22 条序列全部接受，缺失不填 0', () async {
    const csv = '/mnt/shared/recently/commorcial/data/custom/daily_series.csv';
    if (bin == null || !File(csv).existsSync()) {
      markTestSkipped('缺少 CBR_COLLECTOR_BIN 或真实 CSV');
      return;
    }
    final sup = buildSupervisor();
    addTearDown(sup.shutdown);
    await sup.sendTyped('initialize', {
      'contract_version': '1.0.0',
      'client_version': '0.1.0',
      'workspace': '$root/ws',
      'data_home': '$root/data',
      'resource_home': '$root/res',
      'capabilities': <String>[],
    }, (p) => p).first;
    final res = await sup.sendTyped('inbox.ingest', {
      'path': csv,
    }, InboxIngestResult.parse).first;
    expect(
      res.isSuccess,
      isTrue,
      reason: res is Failure<InboxIngestResult>
          ? 'kind=${res.error.kind.kind} msg=${res.error.message} detail=${res.error.detail}'
          : 'ok',
    );
    final r = res.valueOrThrow;
    expect(r.accepted.length, 22, reason: '真实宽面板应有 22 条序列');
    // 北向自 2024-08-16 停更 → 行数必须少于 2615，且不得被填 0
    final north = r.accepted
        .where((f) => f.seriesId.contains('northbound_net'))
        .toList();
    expect(north, isNotEmpty);
    expect(north.first.rows, lessThan(2615), reason: '缺失行不得被补成观测');
  }, timeout: const Timeout(Duration(minutes: 3)));

  test('真实 ZIP 清洗：接受的入库、被拒的给出原因', () async {
    if (bin == null || zipPath == null || !File(zipPath).existsSync()) {
      markTestSkipped('缺少 CBR_COLLECTOR_BIN 或 CBR_E2E_ZIP');
      return;
    }
    final sup = buildSupervisor();
    addTearDown(sup.shutdown);
    await sup.sendTyped('initialize', {
      'contract_version': '1.0.0',
      'client_version': '0.1.0',
      'workspace': '$root/ws',
      'data_home': '$root/data',
      'resource_home': '$root/res',
      'capabilities': <String>[],
    }, (p) => p).first;
    final res = await sup.sendTyped('inbox.ingest', {
      'path': zipPath,
    }, InboxIngestResult.parse).first;
    expect(
      res.isSuccess,
      isTrue,
      reason: res is Failure<InboxIngestResult>
          ? 'kind=${res.error.kind.kind} msg=${res.error.message} detail=${res.error.detail}'
          : 'ok',
    );
    final r = res.valueOrThrow;
    expect(r.accepted, isNotEmpty, reason: '真实 ZIP 应至少有一个序列被接受');
    for (final rej in r.rejected) {
      expect(rej.reason.trim(), isNotEmpty, reason: '被拒文件必须给出原因，不得静默丢弃');
    }
  }, timeout: const Timeout(Duration(minutes: 5)));
}
