import 'dart:async';
import 'dart:convert';
import 'dart:io' show ProcessException;

import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../../core/errors.dart';
import 'sidecar_transport.dart';

/// sidecar 状态。
enum SidecarState {
  /// 未启动（懒启动前）。
  idle('未启动'),

  /// 正在握手。
  starting('正在启动'),

  /// 可用。
  ready('就绪'),

  /// 已重启超过上限，内核不可用。
  unavailable('内核不可用');

  const SidecarState(this.label);

  /// 中文标签。
  final String label;
}

/// sidecar 生命周期与 JSON-RPC 会话（contracts/README.md §1）。
///
/// - 懒启动：首次调用才拉起；
/// - 心跳 5s；请求默认超时 30s；
/// - 同会话最多重启 3 次（退避 1s/2s/4s），超出标记「内核不可用」；
/// - 重启后未完成请求**明确失败**，写操作不自动重放；
/// - 退出：`shutdown` → 等 2s → 强杀。
final class SidecarSupervisor implements SidecarClient {
  SidecarSupervisor({
    required this.transportFactory,
    required this.clientVersion,
    required this.contractVersion,
    required this.workspace,
    required this.dataHome,
    required this.resourceHome,
    this.requestTimeout = const Duration(seconds: 30),
    this.heartbeatInterval = const Duration(seconds: 5),
    this.maxRestarts = 3,
  });

  /// 传输工厂（每次重启新建一个传输实例）。
  final SidecarTransport Function() transportFactory;

  /// 客户端版本。
  final String clientVersion;

  /// 契约版本（contracts/VERSION）。
  final String contractVersion;

  /// 工作区路径。
  final String workspace;

  /// 可写根。
  final String dataHome;

  /// 只读资源根。
  final String resourceHome;

  /// 单次请求默认超时。
  final Duration requestTimeout;

  /// 心跳间隔。
  final Duration heartbeatInterval;

  /// 会话内最大重启次数。
  final int maxRestarts;

  SidecarTransport? _transport;
  StreamSubscription<String>? _lineSub;
  StreamSubscription<String>? _stderrSub;
  Timer? _heartbeat;
  int _nextId = 1;
  int _restarts = 0;
  int _generation = 0;
  bool _starting = false;
  bool _shuttingDown = false;
  SidecarState _state = SidecarState.idle;
  InitializeResult? _handshake;

  final _pending = <String, _PendingCall>{};
  final _stateController = StreamController<SidecarState>.broadcast();

  /// 状态变化流。
  Stream<SidecarState> get states => _stateController.stream;

  /// 当前状态。
  SidecarState get state => _state;

  /// 握手结果（未启动为 null）。
  InitializeResult? get handshake => _handshake;

  /// 确保已启动并完成握手。
  Future<void> ensureStarted() async {
    if (_state == SidecarState.unavailable) {
      throw AppError.unavailable(
        code: 'E_KERNEL_UNAVAILABLE',
        what: '本地内核不可用',
        why: '本次会话内重启已超过 $maxRestarts 次',
        next: '可退出应用后重新启动；若持续失败，请在诊断页导出日志反馈',
      );
    }
    if (_state == SidecarState.ready) {
      return;
    }
    if (_starting) {
      // 等启动完成：轮询到 ready / 抛错。
      while (_starting) {
        await Future<void>.delayed(const Duration(milliseconds: 20));
        if (_state == SidecarState.unavailable) {
          throw AppError.unavailable(
            code: 'E_KERNEL_UNAVAILABLE',
            what: '本地内核不可用',
            why: '启动过程中失败',
            next: '可退出应用后重新启动',
          );
        }
      }
      return;
    }
    _starting = true;
    try {
      await _startFresh();
    } finally {
      _starting = false;
    }
  }

  Future<void> _startFresh() async {
    final transport = transportFactory();
    _transport = transport;
    final generation = ++_generation;
    try {
      await transport.start();
    } on ProcessException catch (e) {
      _transport = null;
      _setState(SidecarState.unavailable);
      throw AppError.unavailable(
        code: 'E_KERNEL_START',
        what: '本地内核启动失败',
        why: '无法执行 ${e.executable}（${e.message}）',
        next: '可在诊断页确认内核是否随安装包分发，或重新安装应用',
        detail: {'executable': e.executable},
      );
    }
    _lineSub = transport.lines.listen((line) => _onLine(generation, line));
    _stderrSub = transport.stderrLines.listen((_) {
      // stderr 是开发日志；不进入协议处理。
    });
    unawaited(transport.exitCode.then((code) => _onExit(generation, code)));
    await _handshakeNow();
    _startHeartbeat();
  }

  Future<void> _handshakeNow() async {
    final result = await _callRaw(
      'initialize',
      InitializeParams(
        contractVersion: contractVersion,
        clientVersion: clientVersion,
        workspace: workspace,
        dataHome: dataHome,
        resourceHome: resourceHome,
      ).toJson(),
      timeout: const Duration(seconds: 10),
    );
    final parsed = InitializeResult.parse(result);
    if (parsed.contractVersion != contractVersion) {
      _setState(SidecarState.unavailable);
      throw AppError.unavailable(
        code: 'E_CONTRACT_MISMATCH',
        what: '内核契约版本不匹配',
        why: '客户端 $contractVersion，内核 ${parsed.contractVersion}',
        next: '请重新安装与本应用配套的内核版本',
      );
    }
    _handshake = parsed;
    _setState(SidecarState.ready);
  }

  void _startHeartbeat() {
    _heartbeat?.cancel();
    _heartbeat = Timer.periodic(heartbeatInterval, (_) {
      if (_state != SidecarState.ready) {
        return;
      }
      unawaited(
        _callRaw(
          'ping',
          const PingParams().toJson(),
          timeout: heartbeatInterval,
        ).catchError((Object _) {
          _scheduleRestart('心跳超时');
          return null;
        }),
      );
    });
  }

  void _onLine(int generation, String line) {
    if (generation != _generation) {
      return;
    }
    final Object? decoded;
    try {
      decoded = jsonDecode(line);
    } on FormatException {
      return;
    }
    final RpcResponse response;
    try {
      response = RpcResponse.parse(decoded);
    } on ContractFormatException {
      return;
    }
    final pending = _pending.remove(response.id);
    if (pending == null) {
      // 迟到响应按 id 丢弃。
      return;
    }
    switch (response) {
      case RpcSuccessResponse(:final result):
        pending.complete(result);
      case RpcErrorResponse(:final error):
        pending.completeError(
          AppError.unavailable(
            code: error.kind.kind,
            what: _errorTitle(error.kind),
            why: error.message,
            next: error.retryable ? '可重试本次操作' : '可查看诊断信息定位原因',
            detail: error.detail,
          ),
        );
    }
  }

  String _errorTitle(RpcErrorKind kind) => switch (kind) {
    RpcErrorKind.parse || RpcErrorKind.invalidRequest => '请求格式错误',
    RpcErrorKind.methodNotFound => '内核不支持该方法',
    RpcErrorKind.invalidParams => '参数不合法',
    RpcErrorKind.internal => '内核内部异常',
    RpcErrorKind.platformUnsupported => '本平台不支持本地计算',
    RpcErrorKind.notAuthorized => '来源需要授权',
    RpcErrorKind.sourceUnavailable => '来源当前不可达',
    RpcErrorKind.dataMissing => '缺少必需数据',
    RpcErrorKind.contractMismatch => '契约版本不匹配',
    RpcErrorKind.rateLimited => '请求被限流',
    RpcErrorKind.timeout => '请求超时',
    RpcErrorKind.notInitialized => '内核未完成握手',
    RpcErrorKind.permissionDenied => '角色越权',
  };

  void _onExit(int generation, int code) {
    if (generation != _generation || _shuttingDown) {
      return;
    }
    _failPending(
      AppError.unavailable(
        code: 'E_KERNEL_EXIT',
        what: '本地内核意外退出',
        why: '进程以退出码 $code 结束',
        next: '正在尝试自动重启；若多次失败可在诊断页导出日志',
      ),
    );
    _scheduleRestart('进程退出（$code）');
  }

  void _scheduleRestart(String reason) {
    if (_shuttingDown) {
      return;
    }
    _heartbeat?.cancel();
    _setState(SidecarState.starting);
    if (_restarts >= maxRestarts) {
      _setState(SidecarState.unavailable);
      _failPending(
        AppError.unavailable(
          code: 'E_KERNEL_UNAVAILABLE',
          what: '本地内核不可用',
          why: '本次会话内已重启 $_restarts 次（$reason）',
          next: '可退出应用后重新启动；若持续失败，请在诊断页导出日志反馈',
        ),
      );
      return;
    }
    final delay = Duration(seconds: 1 << _restarts); // 1s / 2s / 4s
    _restarts++;
    unawaited(() async {
      await Future<void>.delayed(delay);
      if (_shuttingDown) {
        return;
      }
      await _disposeTransport();
      try {
        await _startFresh();
      } on Object {
        _scheduleRestart('重启失败');
      }
    }());
  }

  void _failPending(AppError error) {
    for (final pending in _pending.values) {
      pending.completeError(error);
    }
    _pending.clear();
  }

  void _setState(SidecarState next) {
    if (_state == next) {
      return;
    }
    _state = next;
    _stateController.add(next);
  }

  Future<Object?> _callRaw(
    String method,
    Map<String, Object?> params, {
    Duration? timeout,
  }) {
    final transport = _transport;
    if (transport == null || !transport.isRunning) {
      throw AppError.unavailable(
        code: 'E_KERNEL_NOT_RUNNING',
        what: '本地内核未运行',
        why: 'sidecar 进程尚未启动',
        next: '可重试本次操作',
      );
    }
    final id = '${_nextId++}';
    final pending = _PendingCall();
    _pending[id] = pending;
    final request = RpcRequest(id: id, method: method, params: params);
    try {
      transport.sendLine(jsonEncode(request.toJson()));
    } on Object {
      _pending.remove(id);
      rethrow;
    }
    final effective = timeout ?? requestTimeout;
    return pending.future.timeout(
      effective,
      onTimeout: () {
        _pending.remove(id);
        throw AppError.unavailable(
          code: 'E_TIMEOUT',
          what: '内核调用超时',
          why: '$method 超过 ${effective.inSeconds} 秒未返回',
          next: '可重试；若反复超时，请在诊断页导出日志',
        );
      },
    );
  }

  @override
  Stream<Result<Object?>> send(String method, Map<String, Object?> params) =>
      _oneShot(method, params, (payload) => payload);

  @override
  Stream<Result<T>> sendTyped<T>(
    String method,
    Map<String, Object?> params,
    T Function(Object? payload) parse,
  ) => _oneShot(method, params, parse);

  Stream<Result<T>> _oneShot<T>(
    String method,
    Map<String, Object?> params,
    T Function(Object? payload) parse,
  ) {
    final controller = StreamController<Result<T>>();
    unawaited(() async {
      try {
        await ensureStarted();
        final payload = await _callRaw(method, params);
        controller.add(Success<T>(parse(payload)));
      } on AppError catch (e) {
        controller.add(
          Failure<T>(
            RpcError(
              code: RpcErrorKind.internal.code,
              message: e.message,
              kind: RpcErrorKind.internal,
              retryable: e.layer == ErrorLayer.external,
              detail: {'reason': e.why, ...e.detail},
            ),
          ),
        );
      } on Object catch (e) {
        controller.add(
          Failure<T>(
            RpcError(
              code: RpcErrorKind.internal.code,
              message: '$e',
              kind: RpcErrorKind.internal,
              retryable: false,
              detail: const {},
            ),
          ),
        );
      } finally {
        await controller.close();
      }
    }());
    return controller.stream;
  }

  /// 直接调用并解析（供 UI 层读取真实数据）。
  Future<T> callTyped<T>(
    String method,
    Map<String, Object?> params,
    T Function(Object? payload) parse,
  ) async {
    await ensureStarted();
    return parse(await _callRaw(method, params));
  }

  /// 优雅退出：`shutdown` → 等 2s → 强杀。
  Future<void> shutdown() async {
    _shuttingDown = true;
    _heartbeat?.cancel();
    final transport = _transport;
    if (transport != null && transport.isRunning) {
      try {
        await _callRaw(
          'shutdown',
          const ShutdownParams().toJson(),
          timeout: const Duration(seconds: 2),
        ).catchError((Object _) => null);
      } on Object {
        // 已尽力通知，继续强制终止。
      }
    }
    await _disposeTransport();
    _setState(SidecarState.idle);
  }

  Future<void> _disposeTransport() async {
    final transport = _transport;
    _transport = null;
    await _lineSub?.cancel();
    await _stderrSub?.cancel();
    _lineSub = null;
    _stderrSub = null;
    if (transport != null) {
      await transport.terminate();
    }
  }
}

final class _PendingCall {
  final _completer = Completer<Object?>();

  Future<Object?> get future => _completer.future;

  void complete(Object? value) {
    if (!_completer.isCompleted) {
      _completer.complete(value);
    }
  }

  void completeError(Object error) {
    if (!_completer.isCompleted) {
      _completer.completeError(error);
    }
  }
}
