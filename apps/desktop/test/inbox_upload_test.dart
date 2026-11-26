import 'dart:io';

import 'package:cbr_maw/app/inbox_log.dart';
import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;

/// 屏 3：逐文件状态、被拒原因、原文件保留、两处落点共用同一链路。
InboxIngestResult _result({
  List<AcceptedFile> accepted = const [],
  List<RejectedFile> rejected = const [],
}) => InboxIngestResult(
  batchId: 'batch_1',
  accepted: accepted,
  rejected: rejected,
);

AcceptedFile _accepted(String file) => AcceptedFile(
  file: file,
  seriesId: 'market.cn_equity.csi300',
  rows: 22,
  releaseTimeRule: 'daily_close',
);

void main() {
  late Directory tmp;
  late InboxLog log;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('cbr-inbox-test-');
    log = InboxLog();
  });

  tearDown(() => tmp.deleteSync(recursive: true));

  InboxUploader uploader(
    Future<InboxIngestResult> Function({
      required String path,
      String? declaredSource,
    })
    call,
  ) => InboxUploader(
    inboxDir: p.join(tmp.path, 'inbox'),
    ingestInbox: call,
    log: log,
  );

  test('已入库 → 记录序列与行数，状态为 ingested', () async {
    final csv = File(p.join(tmp.path, 'daily_series.csv'))
      ..writeAsStringSync('d,v\n2024-01-01,1\n');
    final records = await uploader(
      ({required path, declaredSource}) async =>
          _result(accepted: [_accepted(p.basename(path))]),
    ).ingestAll([csv.path]);
    expect(records, hasLength(1));
    expect(records.single.status, IngestStatus.ingested);
    expect(records.single.seriesId, 'market.cn_equity.csi300');
    expect(records.single.rows, 22);
    expect(log.records.single.fileName, 'daily_series.csv');
    // 原文件保留。
    expect(File(csv.path).existsSync(), isTrue);
    // 已复制到投递箱。
    expect(
      File(p.join(tmp.path, 'inbox', 'daily_series.csv')).existsSync(),
      isTrue,
    );
  });

  test('被拒 → 记录原因，不静默丢弃，原文件保留', () async {
    final csv = File(p.join(tmp.path, 'bad.csv'))..writeAsStringSync('x');
    final records = await uploader(
      ({required path, declaredSource}) async => _result(
        rejected: [
          RejectedFile(file: p.basename(path), reason: '编码无法识别（GB18030）'),
        ],
      ),
    ).ingestAll([csv.path]);
    expect(records.single.status, IngestStatus.rejected);
    expect(records.single.reason, contains('编码'));
    expect(File(csv.path).existsSync(), isTrue);
    expect(log.pendingCount, 1);
  });

  test('列名映射失败 → 归为「需人工确认」而非「被拒」', () async {
    final csv = File(p.join(tmp.path, 'weird.csv'))..writeAsStringSync('x');
    final records = await uploader(
      ({required path, declaredSource}) async => _result(
        rejected: [
          RejectedFile(file: p.basename(path), reason: '列名映射失败：未命中任何序列'),
        ],
      ),
    ).ingestAll([csv.path]);
    expect(records.single.status, IngestStatus.needsConfirmation);
  });

  test('不支持的扩展名 → 被拒且不调用清洗', () async {
    final exe = File(p.join(tmp.path, 'a.exe'))..writeAsStringSync('x');
    var called = false;
    final records = await uploader(({required path, declaredSource}) async {
      called = true;
      return _result();
    }).ingestAll([exe.path]);
    expect(called, isFalse);
    expect(records.single.status, IngestStatus.rejected);
    expect(records.single.reason, contains('不支持的格式'));
  });

  test('目录递归展开，逐个文件处理', () async {
    final dir = Directory(p.join(tmp.path, 'zipped'))..createSync();
    File(p.join(dir.path, 'a.csv')).writeAsStringSync('x');
    File(p.join(dir.path, 'b.csv')).writeAsStringSync('x');
    final records = await uploader(
      ({required path, declaredSource}) async =>
          _result(accepted: [_accepted(p.basename(path))]),
    ).ingestAll([dir.path]);
    expect(records, hasLength(2));
    expect(records.every((r) => r.status == IngestStatus.ingested), isTrue);
  });

  test('清洗返回空接受也空拒绝 → 显式记为被拒，不伪造成功', () async {
    final csv = File(p.join(tmp.path, 'empty.csv'))..writeAsStringSync('x');
    final records = await uploader(
      ({required path, declaredSource}) async => _result(),
    ).ingestAll([csv.path]);
    expect(records.single.status, IngestStatus.rejected);
    expect(records.single.reason, contains('没有可入库的行'));
  });
}
