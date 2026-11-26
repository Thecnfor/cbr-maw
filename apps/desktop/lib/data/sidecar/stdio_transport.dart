import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'sidecar_transport.dart';

/// stdio 子进程传输：stdin/stdout 上 NDJSON，stderr 是 JSONL 日志。
final class StdioSidecarTransport implements SidecarTransport {
  StdioSidecarTransport({required this.executable, required this.arguments});

  /// 可执行文件路径。
  final String executable;

  /// 启动参数（`--workspace` 等）。
  final List<String> arguments;

  Process? _process;
  final _lines = StreamController<String>.broadcast();
  final _stderr = StreamController<String>.broadcast();
  Completer<int>? _exit;
  StreamSubscription<String>? _stdoutSub;
  StreamSubscription<String>? _stderrSub;

  @override
  Stream<String> get lines => _lines.stream;

  @override
  Stream<String> get stderrLines => _stderr.stream;

  @override
  bool get isRunning => _process != null;

  @override
  Future<int> get exitCode => (_exit ??= Completer<int>()).future;

  @override
  Future<void> start() async {
    if (_process != null) {
      return;
    }
    final process = await Process.start(executable, arguments);
    _process = process;
    _exit = Completer<int>();
    _stdoutSub = process.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen(_lines.add, onError: _lines.addError);
    _stderrSub = process.stderr
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen(_stderr.add, onError: _stderr.addError);
    unawaited(
      process.exitCode.then((code) {
        _process = null;
        _exit?.complete(code);
      }),
    );
  }

  @override
  void sendLine(String line) {
    final process = _process;
    if (process == null) {
      throw StateError('sidecar 未启动');
    }
    process.stdin.writeln(line);
  }

  @override
  Future<void> terminate({Duration grace = const Duration(seconds: 2)}) async {
    final process = _process;
    if (process == null) {
      return;
    }
    process.kill(ProcessSignal.sigterm);
    final exited = await process.exitCode.timeout(
      grace,
      onTimeout: () {
        process.kill(ProcessSignal.sigkill);
        return -1;
      },
    );
    await _stdoutSub?.cancel();
    await _stderrSub?.cancel();
    _process = null;
    if (_exit != null && !_exit!.isCompleted) {
      _exit!.complete(exited);
    }
  }
}
