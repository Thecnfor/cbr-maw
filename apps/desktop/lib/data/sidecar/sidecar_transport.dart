import 'dart:async';

/// sidecar 传输层抽象：测试可注入内存实现，生产用 stdio 子进程。
abstract interface class SidecarTransport {
  /// 拉起进程（幂等）。
  Future<void> start();

  /// 发送一行（不带换行符）。
  void sendLine(String line);

  /// 收到的每一行（不含换行符）。
  Stream<String> get lines;

  /// stderr 日志行（开发日志）。
  Stream<String> get stderrLines;

  /// 进程是否存活。
  bool get isRunning;

  /// 进程退出事件（重启后应重新订阅）。
  Future<int> get exitCode;

  /// 优雅终止：发信号后等待，超时强杀。
  Future<void> terminate({Duration grace = const Duration(seconds: 2)});
}
