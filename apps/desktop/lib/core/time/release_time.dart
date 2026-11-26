/// 发布时点规则（contracts/README.md §5、docs/05 PIT 纪律）。
///
/// 口径与 Rust 内核一致：
/// - 境内 A 股 / 中债 / 港股：观测日**当日 18:00 (+08:00)**；
/// - 隔夜海外因子（VIX / SP500 / US10Y）：观测日**次日 09:00 (+08:00)**；
/// - 月频：按**发布日**；
/// - 无发布列：**保守规则**（观测日当日 18:00），且必须记录依据（[ReleaseTimePolicy.basis]）。
///
/// `release_time ≠ obs_date`；本文件只做纯函数推导，不读数据、不落库。
library;

/// 发布时点规则（跨语言字面量保持一致）。
enum ReleaseTimeRule {
  /// 境内市场收盘后发布：观测日当日 18:00 (+08:00)。
  domesticClose('domestic_close_1800'),

  /// 隔夜海外因子：观测日次日 09:00 (+08:00)。
  overseasOvernight('overseas_next_day_0900'),

  /// 月频：按发布日。
  monthlyPublishDay('monthly_publish_day'),

  /// 无发布列时的保守规则：观测日当日 18:00 (+08:00)，依据必须记录。
  conservativeSameDay('conservative_same_day_1800');

  const ReleaseTimeRule(this.wire);

  /// JSON 字面量。
  final String wire;
}

/// 一条发布时点策略：规则 + 发布时刻 + 滞后天数 + 依据。
///
/// [basis] 是**可查的依据**：写进 `release_time_rule` 后，审计方能回答
/// "这个 release_time 是按哪条规则推出来的"。
final class ReleaseTimePolicy {
  /// 创建策略。
  const ReleaseTimePolicy({
    required this.rule,
    required this.publishHour,
    required this.publishMinute,
    required this.lagDays,
    required this.basis,
  });

  /// 规则。
  final ReleaseTimeRule rule;

  /// 发布小时（本地时区 +08:00）。
  final int publishHour;

  /// 发布分钟。
  final int publishMinute;

  /// 相对观测日的滞后天数（隔夜海外为 1）。
  final int lagDays;

  /// 依据（可写入 `release_time_rule`）。
  final String basis;

  /// 境内 A 股 / 中债 / 港股：观测日当日 18:00。
  static const ReleaseTimePolicy domestic = ReleaseTimePolicy(
    rule: ReleaseTimeRule.domesticClose,
    publishHour: 18,
    publishMinute: 0,
    lagDays: 0,
    basis: '境内市场收盘后发布（观测日当日 18:00 +08:00）',
  );

  /// 隔夜海外因子：观测日次日 09:00。
  static const ReleaseTimePolicy overseas = ReleaseTimePolicy(
    rule: ReleaseTimeRule.overseasOvernight,
    publishHour: 9,
    publishMinute: 0,
    lagDays: 1,
    basis: '隔夜海外因子，次日 09:00 (+08:00) 才可得（release_lag_days=1）',
  );

  /// 月频：按发布日（默认发布日 09:00）。
  static const ReleaseTimePolicy monthly = ReleaseTimePolicy(
    rule: ReleaseTimeRule.monthlyPublishDay,
    publishHour: 9,
    publishMinute: 0,
    lagDays: 0,
    basis: '月频指标，按发布日推算（发布日 09:00 +08:00）',
  );

  /// 无发布列时的保守规则：观测日当日 18:00，依据必须记录。
  static const ReleaseTimePolicy conservative = ReleaseTimePolicy(
    rule: ReleaseTimeRule.conservativeSameDay,
    publishHour: 18,
    publishMinute: 0,
    lagDays: 0,
    basis: '无发布列，按保守规则取观测日当日 18:00 (+08:00)（口径偏保守，可能偏晚）',
  );

  /// 写进 `release_time_rule` 的可读文本。
  String get ruleLabel =>
      '${rule.wire}@${publishHour.toString().padLeft(2, '0')}:'
      '${publishMinute.toString().padLeft(2, '0')}+lag$lagDays';

  /// 按策略推导 release_time（返回 UTC 时刻）。
  ///
  /// [obsDate] 为观测日（只取日历日，时分秒忽略）。
  /// [publishDate] 仅月频使用：给出时按该日发布，否则退化为 [obsDate] 当日。
  DateTime releaseTime(DateTime obsDate, {DateTime? publishDate}) {
    final base = switch (rule) {
      ReleaseTimeRule.monthlyPublishDay => publishDate ?? obsDate,
      _ => obsDate,
    };
    final shifted = base.add(Duration(days: lagDays));
    // 本产品统一 UTC+08:00 且无夏令时（Asia/Shanghai 自 1991 年起不再使用夏令时）。
    final local = DateTime.utc(
      shifted.year,
      shifted.month,
      shifted.day,
      publishHour,
      publishMinute,
    ).subtract(const Duration(hours: 8));
    return local;
  }
}
