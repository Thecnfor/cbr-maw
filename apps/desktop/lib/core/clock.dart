import 'package:intl/intl.dart';

/// 时区与 `as_of` 工具（docs/05 PIT 纪律）。
///
/// 只做展示与规范化；PIT 过滤本身由 kernel 强制注入，Dart 不参与判断。
final class Clock {
  /// 固定时区偏移（本产品界面统一 +08:00）。
  static const Duration chinaOffset = Duration(hours: 8);

  /// 当前时刻（UTC）。
  static DateTime nowUtc() => DateTime.now().toUtc();

  /// 当前时刻的 `as_of` 字符串（+08:00，秒精度）。
  static String asOfNow() => formatAsOf(nowUtc());

  /// 把时刻格式化为 `2026-11-25T18:00:00+08:00`。
  static String formatAsOf(DateTime instant) {
    final local = instant.toUtc().add(chinaOffset);
    return '${DateFormat("yyyy-MM-dd'T'HH:mm:ss").format(local)}+08:00';
  }

  /// 解析 ISO 8601（容忍仅日期的 `YYYY-MM-DD`，按当日 18:00 +08:00 解释）。
  static DateTime? parseAsOf(String raw) {
    final direct = DateTime.tryParse(raw);
    if (direct != null) {
      return direct.toUtc();
    }
    final dateOnly = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(raw);
    if (dateOnly != null) {
      return DateTime.utc(
        int.parse(dateOnly.group(1)!),
        int.parse(dateOnly.group(2)!),
        int.parse(dateOnly.group(3)!),
        10, // 18:00 +08:00 = 10:00 UTC
      );
    }
    return null;
  }

  /// 相对时间中文文案（docs/08 §7.4）。
  static String relative(String? isoInstant, {DateTime? now}) {
    if (isoInstant == null || isoInstant.isEmpty) {
      return '从未成功';
    }
    final instant = DateTime.tryParse(isoInstant);
    if (instant == null) {
      return isoInstant;
    }
    final reference = (now ?? nowUtc()).toUtc();
    final diff = reference.difference(instant.toUtc());
    if (diff.isNegative) {
      return '刚刚';
    }
    if (diff.inMinutes < 1) {
      return '刚刚';
    }
    if (diff.inMinutes < 60) {
      return '${diff.inMinutes} 分钟前';
    }
    if (diff.inHours < 24) {
      return '${diff.inHours} 小时前';
    }
    return '${diff.inDays} 天前';
  }

  /// 本地展示时刻（+08:00）。
  static String display(String? isoInstant) {
    if (isoInstant == null || isoInstant.isEmpty) {
      return '—';
    }
    final instant = DateTime.tryParse(isoInstant);
    if (instant == null) {
      return isoInstant;
    }
    final local = instant.toUtc().add(chinaOffset);
    return DateFormat('yyyy-MM-dd HH:mm').format(local);
  }
}
