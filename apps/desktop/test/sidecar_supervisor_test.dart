import 'dart:async';
import 'dart:convert';

import 'package:cbr_maw/data/sidecar/sidecar_supervisor.dart';
import 'package:cbr_maw/data/sidecar/sidecar_transport.dart';
import 'package:flutter_test/flutter_test.dart';

/// 内存传输：应答 initialize / ping / shutdown，并可模拟进程退出。
final class _FakeTransport implements SidecarTransport {
  _FakeTransport();

  final _lines = StreamController<String>.broadcast();
  final _stderr = StreamController<String>.broadcast();
  final _exit = Completer<int>();
  final sent = <Map<String, Object?>>[];
  bool running = false;

  /// 内核是否应答。
  bool answer = true;

  /// 请求是否被挂起（模拟崩溃前的在途请求）。
  bool hangRequests = false;

  @override
  Stream<String> get lines => _lines.stream;

  @override
  Stream<String> get stderrLines => _stderr.stream;

  @override
  bool get isRunning => running;

  @override
  Future<int> get exitCode => _exit.future;

  @override
  Future<void> start() async => running = true;

  @override
  void sendLine(String line) {
    final decoded = jsonDecode(line) as Map<String, Object?>;
    sent.add(decoded);
    if (!answer) {
      return;
    }
    if (hangRequests) {
      return;
    }
    final method = decoded['method'] as String;
    final id = decoded['id'] as String;
    final Object? result = switch (method) {
      'initialize' => {
        'sidecar': 'kernel',
        'version': '0.1.0',
        'contract_version': '1.0.0',
        'schema_version': 3,
        'capabilities': <String>['db.query'],
      },
      'ping' => {'pong': true},
      'shutdown' => {'stopped': true},
      _ => null,
    };
    _lines.add(jsonEncode({'jsonrpc': '2.0', 'id': id, 'result': result}));
  }

  /// 模拟进程崩溃。
  void crash(int code) {
    running = false;
    if (!_exit.isCompleted) {
      _exit.complete(code);
    }
  }

  @override
  Future<void> terminate({Duration grace = const Duration(seconds: 2)}) async {
    crash(0);
  }
}

SidecarSupervisor _supervisor(_FakeTransport transport) => SidecarSupervisor(
  transportFactory: () => transport,
  clientVersion: '0.1.0',
  contractVersion: '1.0.0',
  workspace: '/tmp/ws',
  dataHome: '/tmp/data',
  resourceHome: '/tmp/res',
  heartbeatInterval: const Duration(hours: 1),
);

void main() {
  test('懒启动：首次调用才拉起并完成握手', () async {
    final transport = _FakeTransport();
    final supervisor = _supervisor(transport);
    expect(supervisor.state, SidecarState.idle);
    expect(transport.sent, isEmpty);

    await supervisor.ensureStarted();

    expect(supervisor.state, SidecarState.ready);
    expect(transport.sent.first['method'], 'initialize');
    expect(supervisor.handshake?.contractVersion, '1.0.0');
    expect(supervisor.handshake?.schemaVersion, 3);
    await supervisor.shutdown();
  });

  test('契约版本不匹配 → 显式失败（不静默降级）', () async {
    final transport = _MismatchedTransport();
    final supervisor = _supervisor2(transport);
    await expectLater(supervisor.ensureStarted(), throwsA(isA<Exception>()));
    expect(supervisor.state, SidecarState.unavailable);
  });

  test('崩溃后在途请求明确失败（写操作不自动重放）', () async {
    final transport = _FakeTransport();
    final supervisor = _supervisor(transport);
    await supervisor.ensureStarted();

    transport.hangRequests = true;
    final pending = supervisor
        .sendTyped<Object?>('db.write', const {}, (payload) => payload)
        .toList();

    // 让请求挂起，然后崩溃。
    await Future<void>.delayed(const Duration(milliseconds: 20));
    transport.crash(139);

    final results = await pending;
    expect(results.single.isSuccess, isFalse);
    // 崩溃后只有 initialize 被重放（握手），业务写请求没有被重发。
    final writes = transport.sent.where((m) => m['method'] == 'db.write');
    expect(writes.length, 1);
    await supervisor.shutdown();
  });

  test('重启预算为 3 次，退避 1/2/4 秒', () async {
    var spawned = 0;
    final transports = <_FakeTransport>[];
    final supervisor = SidecarSupervisor(
      transportFactory: () {
        final transport = _FakeTransport();
        transports.add(transport);
        spawned++;
        return transport;
      },
      clientVersion: '0.1.0',
      contractVersion: '1.0.0',
      workspace: '/tmp/ws',
      dataHome: '/tmp/data',
      resourceHome: '/tmp/res',
      heartbeatInterval: const Duration(hours: 1),
    );
    await supervisor.ensureStarted();
    expect(supervisor.maxRestarts, 3);

    // 连续崩溃，直到状态落到 unavailable（预算耗尽）。
    for (var i = 0; i < 6; i++) {
      if (transports.isNotEmpty) {
        transports.last.crash(1);
      }
      await Future<void>.delayed(const Duration(milliseconds: 4500));
      if (supervisor.state == SidecarState.unavailable) {
        break;
      }
    }
    expect(supervisor.state, SidecarState.unavailable);
    // 1 次初始启动 + 最多 3 次重启。
    expect(spawned, lessThanOrEqualTo(4));
  }, timeout: const Timeout(Duration(seconds: 60)));
}

SidecarSupervisor _supervisor2(_FakeTransport transport) => SidecarSupervisor(
  transportFactory: () => transport,
  clientVersion: '0.1.0',
  contractVersion: '1.0.0',
  workspace: '/tmp/ws',
  dataHome: '/tmp/data',
  resourceHome: '/tmp/res',
  heartbeatInterval: const Duration(hours: 1),
);

/// 返回错误契约版本的传输。
final class _MismatchedTransport extends _FakeTransport {
  @override
  void sendLine(String line) {
    final decoded = jsonDecode(line) as Map<String, Object?>;
    sent.add(decoded);
    final id = decoded['id'] as String;
    _lines.add(
      jsonEncode({
        'jsonrpc': '2.0',
        'id': id,
        'result': {
          'sidecar': 'kernel',
          'version': '0.1.0',
          'contract_version': '9.9.9',
          'schema_version': 3,
          'capabilities': <String>[],
        },
      }),
    );
  }
}
