// GENERATED-DO-NOT-EDIT: 由 contracts/ 下的 JSON Schema 同源生成。
// 真源：contracts/<domain>/<method>.{request,response}.schema.json。
// 重新生成：python3 packages/contracts_dart/tool/generate_types.py

part of 'rpc.dart';

/// 契约枚举 SourceState（字面量与 JSON 一致）。
enum SourceState {
  reachable('reachable'),
  needAuth('need_auth'),
  needLogin('need_login'),
  restricted('restricted'),
  unreachable('unreachable');

  const SourceState(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从 JSON 字面量解析（解析即校验）。
  static SourceState parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ContractFormatException('非法枚举取值：$raw');
  }
}

/// 契约枚举 LedgerTier（字面量与 JSON 一致）。
enum LedgerTier {
  t1Public('t1Public'),
  t2Credentialed('t2Credentialed'),
  t3Terminal('t3Terminal'),
  t4NotAllowed('t4NotAllowed');

  const LedgerTier(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从 JSON 字面量解析（解析即校验）。
  static LedgerTier parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ContractFormatException('非法枚举取值：$raw');
  }
}

/// 契约枚举 EndpointStatus（字面量与 JSON 一致）。
enum EndpointStatus {
  known('known'),
  toVerify('toVerify'),
  notApplicable('notApplicable');

  const EndpointStatus(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从 JSON 字面量解析（解析即校验）。
  static EndpointStatus parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ContractFormatException('非法枚举取值：$raw');
  }
}

/// 契约枚举 CollectStatus（字面量与 JSON 一致）。
enum CollectStatus {
  ok('ok'),
  partial('partial'),
  failed('failed'),
  skipped('skipped');

  const CollectStatus(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从 JSON 字面量解析（解析即校验）。
  static CollectStatus parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ContractFormatException('非法枚举取值：$raw');
  }
}

/// 契约枚举 SidecarId（字面量与 JSON 一致）。
enum SidecarId {
  collector('collector'),
  kernel('kernel');

  const SidecarId(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从 JSON 字面量解析（解析即校验）。
  static SidecarId parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ContractFormatException('非法枚举取值：$raw');
  }
}

/// 契约枚举 RiskLevel（字面量与 JSON 一致）。
enum RiskLevel {
  low('low'),
  medium('medium'),
  high('high'),
  critical('critical');

  const RiskLevel(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从 JSON 字面量解析（解析即校验）。
  static RiskLevel parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ContractFormatException('非法枚举取值：$raw');
  }
}

/// 契约枚举 DbView（字面量与 JSON 一致）。
enum DbView {
  marketDaily('market_daily'),
  macroMonthly('macro_monthly'),
  pitObservations('pit_observations'),
  dataCards('data_cards'),
  documents('documents'),
  signals('signals'),
  cfsiHistory('cfsi_history'),
  seriesCatalog('series_catalog'),
  ingestBatches('ingest_batches'),
  auditEvents('audit_events');

  const DbView(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从 JSON 字面量解析（解析即校验）。
  static DbView parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ContractFormatException('非法枚举取值：$raw');
  }
}

/// 契约枚举 SortOrder（字面量与 JSON 一致）。
enum SortOrder {
  asc('asc'),
  desc('desc');

  const SortOrder(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从 JSON 字面量解析（解析即校验）。
  static SortOrder parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ContractFormatException('非法枚举取值：$raw');
  }
}

/// 契约枚举 HashKind（字面量与 JSON 一致）。
enum HashKind {
  inputsHash('inputs_hash'),
  evidenceId('evidence_id'),
  evidenceHash('evidence_hash');

  const HashKind(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从 JSON 字面量解析（解析即校验）。
  static HashKind parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ContractFormatException('非法枚举取值：$raw');
  }
}

/// 契约枚举 ToolName（字面量与 JSON 一致）。
enum ToolName {
  riskMeasure('risk_measure'),
  systemicRisk('systemic_risk'),
  capitalFlow('capital_flow'),
  fundingCost('funding_cost'),
  scenario('scenario'),
  forecast('forecast'),
  knowledgeSearch('knowledge_search'),
  dimensionDispersion('dimension_dispersion'),
  capitalLinkage('capital_linkage');

  const ToolName(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从 JSON 字面量解析（解析即校验）。
  static ToolName parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ContractFormatException('非法枚举取值：$raw');
  }
}

/// DateRange —— 契约嵌套对象。
final class DateRange {
  const DateRange({this.start, this.end});

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory DateRange.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return DateRange(start: r.strOpt('start'), end: r.strOpt('end'));
  }

  /// 起始日（YYYY-MM-DD）
  final String? start;

  /// 结束日（YYYY-MM-DD）
  final String? end;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {'start': start, 'end': end};
}

/// CollectEvidence —— 契约嵌套对象。
final class CollectEvidence {
  const CollectEvidence({
    required this.evidenceId,
    required this.sourceId,
    required this.seriesId,
    required this.rows,
    required this.releaseTimeRule,
    this.file,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory CollectEvidence.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return CollectEvidence(
      evidenceId: r.str('evidence_id'),
      sourceId: r.str('source_id'),
      seriesId: r.str('series_id'),
      rows: r.integer('rows'),
      releaseTimeRule: r.str('release_time_rule'),
      file: r.strOpt('file'),
    );
  }

  /// 证据 ID
  final String evidenceId;

  /// 台账条目 ID
  final String sourceId;

  /// 关联序列 ID
  final String seriesId;

  /// 观测条数
  final int rows;

  /// release_time 推导规则（可查）
  final String releaseTimeRule;

  /// 产出文件相对路径
  final String? file;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'evidence_id': evidenceId,
    'source_id': sourceId,
    'series_id': seriesId,
    'rows': rows,
    'release_time_rule': releaseTimeRule,
    'file': file,
  };
}

/// CollectEvent —— 契约嵌套对象。
final class CollectEvent {
  const CollectEvent({
    required this.ts,
    required this.type,
    required this.jobId,
    this.payload,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory CollectEvent.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return CollectEvent(
      ts: r.str('ts'),
      type: r.str('type'),
      jobId: r.str('job_id'),
      payload: r.objOpt('payload'),
    );
  }

  /// 事件时刻（ISO 8601）
  final String ts;

  /// 事件类型（started/progress/succeeded/failed）
  final String type;

  /// 任务 ID
  final String jobId;

  /// 事件负载
  final Map<String, Object?>? payload;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'ts': ts,
    'type': type,
    'job_id': jobId,
    'payload': payload,
  };
}

/// AcceptedFile —— 契约嵌套对象。
final class AcceptedFile {
  const AcceptedFile({
    required this.file,
    required this.seriesId,
    required this.rows,
    required this.releaseTimeRule,
    this.evidence,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory AcceptedFile.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return AcceptedFile(
      file: r.str('file'),
      seriesId: r.str('series_id'),
      rows: r.integer('rows'),
      releaseTimeRule: r.str('release_time_rule'),
      evidence: switch (r.objOpt('evidence')) {
        null => null,
        final v => InboxEvidence.parse(v),
      },
    );
  }

  /// 文件名
  final String file;

  /// 解析出的规范序列 ID
  final String seriesId;

  /// 有效行数
  final int rows;

  /// release_time 推导规则
  final String releaseTimeRule;

  /// 文件级证据
  final InboxEvidence? evidence;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'file': file,
    'series_id': seriesId,
    'rows': rows,
    'release_time_rule': releaseTimeRule,
    'evidence': evidence,
  };
}

/// RejectedFile —— 契约嵌套对象。
final class RejectedFile {
  const RejectedFile({
    required this.file,
    required this.reason,
    this.errorFile,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory RejectedFile.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return RejectedFile(
      file: r.str('file'),
      reason: r.str('reason'),
      errorFile: r.strOpt('error_file'),
    );
  }

  /// 文件名
  final String file;

  /// 拒绝原因（中文短句）
  final String reason;

  /// 错误明细文件路径
  final String? errorFile;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'file': file,
    'reason': reason,
    'error_file': errorFile,
  };
}

/// InboxEvidence —— 契约嵌套对象。
final class InboxEvidence {
  const InboxEvidence({
    required this.evidenceId,
    required this.sourceId,
    this.declaredSource,
    required this.rows,
    required this.droppedRows,
    required this.hash,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory InboxEvidence.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return InboxEvidence(
      evidenceId: r.str('evidence_id'),
      sourceId: r.str('source_id'),
      declaredSource: r.strOpt('declared_source'),
      rows: r.integer('rows'),
      droppedRows: r.integer('dropped_rows'),
      hash: r.str('hash'),
    );
  }

  /// 证据 ID
  final String evidenceId;

  /// 来源 ID（未知时为 null）
  final String sourceId;

  /// 用户声明的来源 ID
  final String? declaredSource;

  /// 有效行数
  final int rows;

  /// 剔除的脏行数
  final int droppedRows;

  /// 内容哈希（64 位小写 hex）
  final String hash;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'evidence_id': evidenceId,
    'source_id': sourceId,
    'declared_source': declaredSource,
    'rows': rows,
    'dropped_rows': droppedRows,
    'hash': hash,
  };
}

/// HealthEntry —— 契约嵌套对象。
final class HealthEntry {
  const HealthEntry({
    required this.sourceId,
    this.lastSuccessAt,
    required this.stale,
    this.coverageStart,
    this.coverageEnd,
    this.failureReason,
    required this.state,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory HealthEntry.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return HealthEntry(
      sourceId: r.str('source_id'),
      lastSuccessAt: r.strOpt('last_success_at'),
      stale: r.boolean('stale'),
      coverageStart: r.strOpt('coverage_start'),
      coverageEnd: r.strOpt('coverage_end'),
      failureReason: r.strOpt('failure_reason'),
      state: SourceState.parse(r.str('state')),
    );
  }

  /// 台账条目 ID
  final String sourceId;

  /// 最后一次成功抓取时刻
  final String? lastSuccessAt;

  /// 是否已超过 staleThresholdDays
  final bool stale;

  /// 覆盖区间起始日
  final String? coverageStart;

  /// 覆盖区间结束日
  final String? coverageEnd;

  /// 失败原因（五态映射）
  final String? failureReason;

  /// 可达性状态
  final SourceState state;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'source_id': sourceId,
    'last_success_at': lastSuccessAt,
    'stale': stale,
    'coverage_start': coverageStart,
    'coverage_end': coverageEnd,
    'failure_reason': failureReason,
    'state': state.wire,
  };
}

/// SourceLedgerEntry —— 契约嵌套对象。
final class SourceLedgerEntry {
  const SourceLedgerEntry({
    required this.id,
    required this.modality,
    required this.subject,
    required this.sourceName,
    required this.tier,
    required this.accessMode,
    required this.authorizationStatus,
    required this.endpointStatus,
    required this.reachability,
    required this.seriesIds,
    this.lastSuccessAt,
    this.lastError,
    this.notes,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory SourceLedgerEntry.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return SourceLedgerEntry(
      id: r.str('id'),
      modality: r.str('modality'),
      subject: r.str('subject'),
      sourceName: r.str('source_name'),
      tier: LedgerTier.parse(r.str('tier')),
      accessMode: r.str('access_mode'),
      authorizationStatus: r.str('authorization_status'),
      endpointStatus: EndpointStatus.parse(r.str('endpoint_status')),
      reachability: r.str('reachability'),
      seriesIds: r.strings('series_ids'),
      lastSuccessAt: r.strOpt('last_success_at'),
      lastError: r.strOpt('last_error'),
      notes: r.strOpt('notes'),
    );
  }

  /// 台账条目 ID（XL-xx / REG-xx）
  final String id;

  /// 模态（text/speech/image/video/numeric）
  final String modality;

  /// 采集对象
  final String subject;

  /// 数据来源名称
  final String sourceName;

  /// 可达性分档
  final LedgerTier tier;

  /// 访问方式
  final String accessMode;

  /// 授权状态
  final String authorizationStatus;

  /// 端点核实状态
  final EndpointStatus endpointStatus;

  /// 运行期可达性状态
  final String reachability;

  /// 关联规范序列 ID
  final List<String> seriesIds;

  /// 最后一次成功抓取时刻
  final String? lastSuccessAt;

  /// 最近一次失败原因摘要
  final String? lastError;

  /// 备注
  final String? notes;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'id': id,
    'modality': modality,
    'subject': subject,
    'source_name': sourceName,
    'tier': tier.wire,
    'access_mode': accessMode,
    'authorization_status': authorizationStatus,
    'endpoint_status': endpointStatus.wire,
    'reachability': reachability,
    'series_ids': seriesIds,
    'last_success_at': lastSuccessAt,
    'last_error': lastError,
    'notes': notes,
  };
}

/// ProbeDetail —— 契约嵌套对象。
final class ProbeDetail {
  const ProbeDetail({
    required this.reason,
    required this.checkedAt,
    this.httpStatus,
    this.latencyMs,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory ProbeDetail.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return ProbeDetail(
      reason: r.str('reason'),
      checkedAt: r.str('checked_at'),
      httpStatus: r.integerOpt('http_status'),
      latencyMs: r.integerOpt('latency_ms'),
    );
  }

  /// 中文短句说明
  final String reason;

  /// 探测时刻
  final String checkedAt;

  /// HTTP 状态码（如适用）
  final int? httpStatus;

  /// 探测耗时（毫秒）
  final int? latencyMs;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'reason': reason,
    'checked_at': checkedAt,
    'http_status': httpStatus,
    'latency_ms': latencyMs,
  };
}

/// KbHit —— 契约嵌套对象。
final class KbHit {
  const KbHit({
    required this.chunkId,
    required this.score,
    required this.text,
    required this.documentId,
    required this.locator,
    this.publishedAt,
    this.sourceId,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory KbHit.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return KbHit(
      chunkId: r.str('chunk_id'),
      score: r.number('score'),
      text: r.str('text'),
      documentId: r.str('document_id'),
      locator: r.str('locator'),
      publishedAt: r.strOpt('published_at'),
      sourceId: r.strOpt('source_id'),
    );
  }

  /// 分块 ID
  final String chunkId;

  /// 打分
  final double score;

  /// 分块原文
  final String text;

  /// 文档 ID
  final String documentId;

  /// 文档内定位
  final String locator;

  /// 文档发布时间
  final String? publishedAt;

  /// 来源 ID
  final String? sourceId;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'chunk_id': chunkId,
    'score': score,
    'text': text,
    'document_id': documentId,
    'locator': locator,
    'published_at': publishedAt,
    'source_id': sourceId,
  };
}

/// PitSeries —— 契约嵌套对象。
final class PitSeries {
  const PitSeries({
    required this.seriesId,
    required this.rows,
    required this.releaseTimeRule,
    required this.coverage,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory PitSeries.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return PitSeries(
      seriesId: r.str('series_id'),
      rows: r.integer('rows'),
      releaseTimeRule: r.str('release_time_rule'),
      coverage: Coverage.parse(r.obj('coverage')),
    );
  }

  /// 规范序列 ID
  final String seriesId;

  /// 写入行数
  final int rows;

  /// release_time 推导规则
  final String releaseTimeRule;

  /// 覆盖区间
  final Coverage coverage;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'series_id': seriesId,
    'rows': rows,
    'release_time_rule': releaseTimeRule,
    'coverage': coverage,
  };
}

/// Coverage —— 契约嵌套对象。
final class Coverage {
  const Coverage({required this.start, required this.end});

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory Coverage.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return Coverage(start: r.str('start'), end: r.str('end'));
  }

  /// 起始日
  final String start;

  /// 结束日
  final String end;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {'start': start, 'end': end};
}

/// CoverageGate —— 契约嵌套对象。
final class CoverageGate {
  const CoverageGate({
    required this.passed,
    required this.baseline,
    required this.current,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory CoverageGate.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return CoverageGate(
      passed: r.boolean('passed'),
      baseline: r.number('baseline'),
      current: r.number('current'),
    );
  }

  /// 是否通过守门
  final bool passed;

  /// 基线覆盖率
  final double baseline;

  /// 本次覆盖率
  final double current;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'passed': passed,
    'baseline': baseline,
    'current': current,
  };
}

/// ToolEvidence —— 契约嵌套对象。
final class ToolEvidence {
  const ToolEvidence({
    required this.evidenceId,
    required this.tool,
    required this.version,
    required this.inputsHash,
    required this.hash,
    this.value,
    this.unit,
    required this.asOf,
    required this.params,
    this.title,
    this.summary,
    this.data,
  });

  /// 从 JSON 对象解析（解析即校验；不符合契约抛 ContractFormatException）。
  factory ToolEvidence.parse(Object? json) {
    final r = JsonReader(json, 'object');
    return ToolEvidence(
      evidenceId: r.str('evidence_id'),
      tool: r.str('tool'),
      version: r.str('version'),
      inputsHash: r.str('inputs_hash'),
      hash: r.str('hash'),
      value: r.numberOpt('value'),
      unit: r.strOpt('unit'),
      asOf: r.str('as_of'),
      params: r.obj('params'),
      title: r.strOpt('title'),
      summary: r.strOpt('summary'),
      data: r.objOpt('data'),
    );
  }

  /// 证据 ID
  final String evidenceId;

  /// 工具名
  final String tool;

  /// 工具版本
  final String version;

  /// 入参哈希（64 位小写 hex）
  final String inputsHash;

  /// 证据载荷哈希（64 位小写 hex）
  final String hash;

  /// 主数值
  final double? value;

  /// 单位
  final String? unit;

  /// 时点
  final String asOf;

  /// 规范化后的入参
  final Map<String, Object?> params;

  /// 证据标题（工具生成的可读名称）
  final String? title;

  /// 证据摘要（工具生成的一句话解读）
  final String? summary;

  /// 工具产出的完整结构化读数（维度明细 / 窗口端点 / 新鲜度等）
  final Map<String, Object?>? data;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'evidence_id': evidenceId,
    'tool': tool,
    'version': version,
    'inputs_hash': inputsHash,
    'hash': hash,
    'value': value,
    'unit': unit,
    'as_of': asOf,
    'params': params,
    'title': title,
    'summary': summary,
    'data': data,
  };
}

/// `collect.run` params。
final class CollectRunParams extends RpcParams {
  const CollectRunParams({required this.sourceId, this.range, this.dryRun});

  /// 从 JSON 对象解析（解析即校验）。
  factory CollectRunParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return CollectRunParams(
      sourceId: r.str('source_id'),
      range: switch (r.objOpt('range')) {
        null => null,
        final v => DateRange.parse(v),
      },
      dryRun: r.booleanOpt('dry_run'),
    );
  }

  @override
  String get method => 'collect.run';

  /// 台账条目 ID
  final String sourceId;

  /// 抓取区间
  final DateRange? range;

  /// 只探测不落盘
  final bool? dryRun;

  @override
  Map<String, Object?> toJson() => {
    'source_id': sourceId,
    'range': range,
    'dry_run': dryRun,
  };
}

/// `collect.run` result。
final class CollectRunResult extends RpcResult {
  const CollectRunResult({
    required this.jobId,
    required this.status,
    required this.writtenFiles,
    required this.evidence,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory CollectRunResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return CollectRunResult(
      jobId: r.str('job_id'),
      status: CollectStatus.parse(r.str('status')),
      writtenFiles: r.strings('written_files'),
      evidence: r.listOf('evidence', (e) => CollectEvidence.parse(e.raw)),
    );
  }

  @override
  String get method => 'collect.run';

  /// 抓取任务 ID
  final String jobId;

  /// 任务结论
  final CollectStatus status;

  /// 落盘的规范化中间文件
  final List<String> writtenFiles;

  /// 来源证据
  final List<CollectEvidence> evidence;

  @override
  Map<String, Object?> toJson() => {
    'job_id': jobId,
    'status': status.wire,
    'written_files': writtenFiles,
    'evidence': evidence,
  };
}

/// `events.poll` params。
final class EventsPollParams extends RpcParams {
  const EventsPollParams({this.jobId});

  /// 从 JSON 对象解析（解析即校验）。
  factory EventsPollParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return EventsPollParams(jobId: r.strOpt('job_id'));
  }

  @override
  String get method => 'events.poll';

  /// 只看某个任务的事件
  final String? jobId;

  @override
  Map<String, Object?> toJson() => {'job_id': jobId};
}

/// `events.poll` result。
final class EventsPollResult extends RpcResult {
  const EventsPollResult({required this.events});

  /// 从 JSON 对象解析（解析即校验）。
  factory EventsPollResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return EventsPollResult(
      events: r.listOf('events', (e) => CollectEvent.parse(e.raw)),
    );
  }

  @override
  String get method => 'events.poll';

  /// 抓取事件流
  final List<CollectEvent> events;

  @override
  Map<String, Object?> toJson() => {'events': events};
}

/// `inbox.ingest` params。
final class InboxIngestParams extends RpcParams {
  const InboxIngestParams({required this.path, this.declaredSource, this.asOf});

  /// 从 JSON 对象解析（解析即校验）。
  factory InboxIngestParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return InboxIngestParams(
      path: r.str('path'),
      declaredSource: r.strOpt('declared_source'),
      asOf: r.strOpt('as_of'),
    );
  }

  @override
  String get method => 'inbox.ingest';

  /// 投递文件绝对路径
  final String path;

  /// 用户声明的来源 ID
  final String? declaredSource;

  /// 时点（ISO 8601 或 YYYY-MM-DD）
  final String? asOf;

  @override
  Map<String, Object?> toJson() => {
    'path': path,
    'declared_source': declaredSource,
    'as_of': asOf,
  };
}

/// `inbox.ingest` result。
final class InboxIngestResult extends RpcResult {
  const InboxIngestResult({
    required this.batchId,
    required this.accepted,
    required this.rejected,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory InboxIngestResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return InboxIngestResult(
      batchId: r.str('batch_id'),
      accepted: r.listOf('accepted', (e) => AcceptedFile.parse(e.raw)),
      rejected: r.listOf('rejected', (e) => RejectedFile.parse(e.raw)),
    );
  }

  @override
  String get method => 'inbox.ingest';

  /// 清洗批次 ID
  final String batchId;

  /// 接受的文件
  final List<AcceptedFile> accepted;

  /// 拒绝的文件
  final List<RejectedFile> rejected;

  @override
  Map<String, Object?> toJson() => {
    'batch_id': batchId,
    'accepted': accepted,
    'rejected': rejected,
  };
}

/// `initialize` params。
final class InitializeParams extends RpcParams {
  const InitializeParams({
    required this.contractVersion,
    required this.clientVersion,
    required this.workspace,
    required this.dataHome,
    required this.resourceHome,
    this.capabilities,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory InitializeParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return InitializeParams(
      contractVersion: r.str('contract_version'),
      clientVersion: r.str('client_version'),
      workspace: r.str('workspace'),
      dataHome: r.str('data_home'),
      resourceHome: r.str('resource_home'),
      capabilities: r.stringsOpt('capabilities'),
    );
  }

  @override
  String get method => 'initialize';

  /// 契约版本（契约/VERSION）
  final String contractVersion;

  /// 客户端版本
  final String clientVersion;

  /// 工作区绝对路径
  final String workspace;

  /// 可写根绝对路径
  final String dataHome;

  /// 只读资源根绝对路径
  final String resourceHome;

  /// 客户端能力清单
  final List<String>? capabilities;

  @override
  Map<String, Object?> toJson() => {
    'contract_version': contractVersion,
    'client_version': clientVersion,
    'workspace': workspace,
    'data_home': dataHome,
    'resource_home': resourceHome,
    'capabilities': capabilities,
  };
}

/// `initialize` result。
final class InitializeResult extends RpcResult {
  const InitializeResult({
    required this.sidecar,
    required this.version,
    required this.contractVersion,
    required this.schemaVersion,
    required this.capabilities,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory InitializeResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return InitializeResult(
      sidecar: SidecarId.parse(r.str('sidecar')),
      version: r.str('version'),
      contractVersion: r.str('contract_version'),
      schemaVersion: r.integer('schema_version'),
      capabilities: r.strings('capabilities'),
    );
  }

  @override
  String get method => 'initialize';

  /// sidecar 身份
  final SidecarId sidecar;

  /// sidecar 版本
  final String version;

  /// 契约版本
  final String contractVersion;

  /// schema 版本
  final int schemaVersion;

  /// sidecar 能力清单
  final List<String> capabilities;

  @override
  Map<String, Object?> toJson() => {
    'sidecar': sidecar.wire,
    'version': version,
    'contract_version': contractVersion,
    'schema_version': schemaVersion,
    'capabilities': capabilities,
  };
}

/// `ping` params。
final class PingParams extends RpcParams {
  const PingParams();

  /// 从 JSON 对象解析（解析即校验）。
  factory PingParams.parse(Object? json) {
    JsonReader(json, 'params').requireKeys(<String>{});
    return const PingParams();
  }

  @override
  String get method => 'ping';

  @override
  Map<String, Object?> toJson() => {};
}

/// `ping` result。
final class PingResult extends RpcResult {
  const PingResult({required this.pong, this.serverTime});

  /// 从 JSON 对象解析（解析即校验）。
  factory PingResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return PingResult(
      pong: r.boolean('pong'),
      serverTime: r.strOpt('server_time'),
    );
  }

  @override
  String get method => 'ping';

  /// 存活应答
  final bool pong;

  /// sidecar 当前时刻（ISO 8601）
  final String? serverTime;

  @override
  Map<String, Object?> toJson() => {'pong': pong, 'server_time': serverTime};
}

/// `shutdown` params。
final class ShutdownParams extends RpcParams {
  const ShutdownParams();

  /// 从 JSON 对象解析（解析即校验）。
  factory ShutdownParams.parse(Object? json) {
    JsonReader(json, 'params').requireKeys(<String>{});
    return const ShutdownParams();
  }

  @override
  String get method => 'shutdown';

  @override
  Map<String, Object?> toJson() => {};
}

/// `shutdown` result。
final class ShutdownResult extends RpcResult {
  const ShutdownResult({required this.stopped});

  /// 从 JSON 对象解析（解析即校验）。
  factory ShutdownResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return ShutdownResult(stopped: r.boolean('stopped'));
  }

  @override
  String get method => 'shutdown';

  /// 是否已进入退出流程
  final bool stopped;

  @override
  Map<String, Object?> toJson() => {'stopped': stopped};
}

/// `sources.health` params。
final class SourcesHealthParams extends RpcParams {
  const SourcesHealthParams();

  /// 从 JSON 对象解析（解析即校验）。
  factory SourcesHealthParams.parse(Object? json) {
    JsonReader(json, 'params').requireKeys(<String>{});
    return const SourcesHealthParams();
  }

  @override
  String get method => 'sources.health';

  @override
  Map<String, Object?> toJson() => {};
}

/// `sources.health` result。
final class SourcesHealthResult extends RpcResult {
  const SourcesHealthResult({required this.entries});

  /// 从 JSON 对象解析（解析即校验）。
  factory SourcesHealthResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return SourcesHealthResult(
      entries: r.listOf('entries', (e) => HealthEntry.parse(e.raw)),
    );
  }

  @override
  String get method => 'sources.health';

  /// 各来源健康状态
  final List<HealthEntry> entries;

  @override
  Map<String, Object?> toJson() => {'entries': entries};
}

/// `sources.list` params。
final class SourcesListParams extends RpcParams {
  const SourcesListParams({this.includeDisabled});

  /// 从 JSON 对象解析（解析即校验）。
  factory SourcesListParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return SourcesListParams(includeDisabled: r.booleanOpt('include_disabled'));
  }

  @override
  String get method => 'sources.list';

  /// 是否包含不可自动抓取的条目
  final bool? includeDisabled;

  @override
  Map<String, Object?> toJson() => {'include_disabled': includeDisabled};
}

/// `sources.list` result。
final class SourcesListResult extends RpcResult {
  const SourcesListResult({required this.sources});

  /// 从 JSON 对象解析（解析即校验）。
  factory SourcesListResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return SourcesListResult(
      sources: r.listOf('sources', (e) => SourceLedgerEntry.parse(e.raw)),
    );
  }

  @override
  String get method => 'sources.list';

  /// 来源台账条目
  final List<SourceLedgerEntry> sources;

  @override
  Map<String, Object?> toJson() => {'sources': sources};
}

/// `sources.probe` params。
final class SourcesProbeParams extends RpcParams {
  const SourcesProbeParams({required this.sourceId, this.timeoutS});

  /// 从 JSON 对象解析（解析即校验）。
  factory SourcesProbeParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return SourcesProbeParams(
      sourceId: r.str('source_id'),
      timeoutS: r.integerOpt('timeout_s'),
    );
  }

  @override
  String get method => 'sources.probe';

  /// 台账条目 ID
  final String sourceId;

  /// 探测超时（秒）
  final int? timeoutS;

  @override
  Map<String, Object?> toJson() => {
    'source_id': sourceId,
    'timeout_s': timeoutS,
  };
}

/// `sources.probe` result。
final class SourcesProbeResult extends RpcResult {
  const SourcesProbeResult({
    required this.sourceId,
    required this.state,
    required this.detail,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory SourcesProbeResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return SourcesProbeResult(
      sourceId: r.str('source_id'),
      state: SourceState.parse(r.str('state')),
      detail: ProbeDetail.parse(r.obj('detail')),
    );
  }

  @override
  String get method => 'sources.probe';

  /// 台账条目 ID
  final String sourceId;

  /// 探测结论（五态）
  final SourceState state;

  /// 探测明细
  final ProbeDetail detail;

  @override
  Map<String, Object?> toJson() => {
    'source_id': sourceId,
    'state': state.wire,
    'detail': detail,
  };
}

/// `cfsi.compute` params。
final class CfsiComputeParams extends RpcParams {
  const CfsiComputeParams({required this.asOf});

  /// 从 JSON 对象解析（解析即校验）。
  factory CfsiComputeParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return CfsiComputeParams(asOf: r.str('as_of'));
  }

  @override
  String get method => 'cfsi.compute';

  /// 时点
  final String asOf;

  @override
  Map<String, Object?> toJson() => {'as_of': asOf};
}

/// `cfsi.compute` result。
final class CfsiComputeResult extends RpcResult {
  const CfsiComputeResult({
    required this.cfsi,
    required this.level,
    required this.tau,
    required this.dims,
    required this.missingDims,
    required this.limitations,
    required this.provenance,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory CfsiComputeResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return CfsiComputeResult(
      cfsi: r.number('cfsi'),
      level: RiskLevel.parse(r.str('level')),
      tau: r.number('tau'),
      dims: r.obj('dims'),
      missingDims: r.strings('missing_dims'),
      limitations: r.strings('limitations'),
      provenance: r.obj('provenance'),
    );
  }

  @override
  String get method => 'cfsi.compute';

  /// CFSI 数值
  final double cfsi;

  /// 压力等级
  final RiskLevel level;

  /// 阈值 τ
  final double tau;

  /// 六维明细（缺席维度不出现）
  final Map<String, Object?> dims;

  /// 缺席维度
  final List<String> missingDims;

  /// 局限性说明
  final List<String> limitations;

  /// 来源与版本溯源
  final Map<String, Object?> provenance;

  @override
  Map<String, Object?> toJson() => {
    'cfsi': cfsi,
    'level': level.wire,
    'tau': tau,
    'dims': dims,
    'missing_dims': missingDims,
    'limitations': limitations,
    'provenance': provenance,
  };
}

/// `db.query` params。
final class DbQueryParams extends RpcParams {
  const DbQueryParams({
    required this.view,
    this.filters,
    required this.asOf,
    this.limit,
    this.order,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory DbQueryParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return DbQueryParams(
      view: DbView.parse(r.str('view')),
      filters: r.objOpt('filters'),
      asOf: r.str('as_of'),
      limit: r.integerOpt('limit'),
      order: switch (r.strOpt('order')) {
        null => null,
        final v => SortOrder.parse(v),
      },
    );
  }

  @override
  String get method => 'db.query';

  /// 具名视图（不接受任意 SQL）
  final DbView view;

  /// 参数化过滤条件
  final Map<String, Object?>? filters;

  /// 时点（由 kernel 强制注入过滤）
  final String asOf;

  /// 返回行上限
  final int? limit;

  /// 排序方向；默认升序。取「最近 N 条」时用 desc。
  final SortOrder? order;

  @override
  Map<String, Object?> toJson() => {
    'view': view.wire,
    'filters': filters,
    'as_of': asOf,
    'limit': limit,
    'order': order?.wire,
  };
}

/// `db.query` result。
final class DbQueryResult extends RpcResult {
  const DbQueryResult({
    required this.columns,
    required this.rows,
    required this.asOf,
    required this.truncated,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory DbQueryResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return DbQueryResult(
      columns: r.strings('columns'),
      rows: r.lists('rows'),
      asOf: r.str('as_of'),
      truncated: r.boolean('truncated'),
    );
  }

  @override
  String get method => 'db.query';

  /// 列名
  final List<String> columns;

  /// 行数据
  final List<List<Object?>> rows;

  /// 实际生效的时点
  final String asOf;

  /// 是否因 limit 截断
  final bool truncated;

  @override
  Map<String, Object?> toJson() => {
    'columns': columns,
    'rows': rows,
    'as_of': asOf,
    'truncated': truncated,
  };
}

/// `db.write` params。
final class DbWriteParams extends RpcParams {
  const DbWriteParams({
    required this.table,
    required this.rows,
    required this.idempotencyKey,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory DbWriteParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return DbWriteParams(
      table: r.str('table'),
      rows: r.objects('rows'),
      idempotencyKey: r.str('idempotency_key'),
    );
  }

  @override
  String get method => 'db.write';

  /// 目标表（受白名单约束）
  final String table;

  /// 待写入行
  final List<Map<String, Object?>> rows;

  /// 幂等键（重放同键不重复写）
  final String idempotencyKey;

  @override
  Map<String, Object?> toJson() => {
    'table': table,
    'rows': rows,
    'idempotency_key': idempotencyKey,
  };
}

/// `db.write` result。
final class DbWriteResult extends RpcResult {
  const DbWriteResult({required this.written, required this.idempotencyKey});

  /// 从 JSON 对象解析（解析即校验）。
  factory DbWriteResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return DbWriteResult(
      written: r.integer('written'),
      idempotencyKey: r.str('idempotency_key'),
    );
  }

  @override
  String get method => 'db.write';

  /// 实际写入行数
  final int written;

  /// 回显的幂等键
  final String idempotencyKey;

  @override
  Map<String, Object?> toJson() => {
    'written': written,
    'idempotency_key': idempotencyKey,
  };
}

/// `features.build` params。
final class FeaturesBuildParams extends RpcParams {
  const FeaturesBuildParams({required this.seriesIds, required this.asOf});

  /// 从 JSON 对象解析（解析即校验）。
  factory FeaturesBuildParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return FeaturesBuildParams(
      seriesIds: r.strings('series_ids'),
      asOf: r.str('as_of'),
    );
  }

  @override
  String get method => 'features.build';

  /// 参与计算的序列 ID
  final List<String> seriesIds;

  /// 时点
  final String asOf;

  @override
  Map<String, Object?> toJson() => {'series_ids': seriesIds, 'as_of': asOf};
}

/// `features.build` result。
final class FeaturesBuildResult extends RpcResult {
  const FeaturesBuildResult({required this.built, required this.featureIds});

  /// 从 JSON 对象解析（解析即校验）。
  factory FeaturesBuildResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return FeaturesBuildResult(
      built: r.integer('built'),
      featureIds: r.strings('feature_ids'),
    );
  }

  @override
  String get method => 'features.build';

  /// 生成的特征数
  final int built;

  /// 特征 ID
  final List<String> featureIds;

  @override
  Map<String, Object?> toJson() => {'built': built, 'feature_ids': featureIds};
}

/// `kb.index` params。
final class KbIndexParams extends RpcParams {
  const KbIndexParams({required this.corpusDir, this.force});

  /// 从 JSON 对象解析（解析即校验）。
  factory KbIndexParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return KbIndexParams(
      corpusDir: r.str('corpus_dir'),
      force: r.booleanOpt('force'),
    );
  }

  @override
  String get method => 'kb.index';

  /// 语料目录绝对路径
  final String corpusDir;

  /// 强制重建索引
  final bool? force;

  @override
  Map<String, Object?> toJson() => {'corpus_dir': corpusDir, 'force': force};
}

/// `kb.index` result。
final class KbIndexResult extends RpcResult {
  const KbIndexResult({
    required this.documents,
    required this.chunks,
    required this.indexVersion,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory KbIndexResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return KbIndexResult(
      documents: r.integer('documents'),
      chunks: r.integer('chunks'),
      indexVersion: r.str('index_version'),
    );
  }

  @override
  String get method => 'kb.index';

  /// 文档数
  final int documents;

  /// 分块数
  final int chunks;

  /// 索引版本（如 kb-bm25-v1）
  final String indexVersion;

  @override
  Map<String, Object?> toJson() => {
    'documents': documents,
    'chunks': chunks,
    'index_version': indexVersion,
  };
}

/// `kb.search` params。
final class KbSearchParams extends RpcParams {
  const KbSearchParams({required this.query, this.topK, this.filters});

  /// 从 JSON 对象解析（解析即校验）。
  factory KbSearchParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return KbSearchParams(
      query: r.str('query'),
      topK: r.integerOpt('top_k'),
      filters: r.objOpt('filters'),
    );
  }

  @override
  String get method => 'kb.search';

  /// 检索式（1..500 字符）
  final String query;

  /// 返回条数
  final int? topK;

  /// 过滤条件（来源/时间等）
  final Map<String, Object?>? filters;

  @override
  Map<String, Object?> toJson() => {
    'query': query,
    'top_k': topK,
    'filters': filters,
  };
}

/// `kb.search` result。
final class KbSearchResult extends RpcResult {
  const KbSearchResult({required this.hits});

  /// 从 JSON 对象解析（解析即校验）。
  factory KbSearchResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return KbSearchResult(hits: r.listOf('hits', (e) => KbHit.parse(e.raw)));
  }

  @override
  String get method => 'kb.search';

  /// 检索命中
  final List<KbHit> hits;

  @override
  Map<String, Object?> toJson() => {'hits': hits};
}

/// `kernel.hash` params。
final class KernelHashParams extends RpcParams {
  const KernelHashParams({required this.payload, required this.kind});

  /// 从 JSON 对象解析（解析即校验）。
  factory KernelHashParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return KernelHashParams(
      payload: r.obj('payload'),
      kind: HashKind.parse(r.str('kind')),
    );
  }

  @override
  String get method => 'kernel.hash';

  /// 待哈希载荷
  final Map<String, Object?> payload;

  /// 哈希种类
  final HashKind kind;

  @override
  Map<String, Object?> toJson() => {'payload': payload, 'kind': kind.wire};
}

/// `kernel.hash` result。
final class KernelHashResult extends RpcResult {
  const KernelHashResult({required this.hash});

  /// 从 JSON 对象解析（解析即校验）。
  factory KernelHashResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return KernelHashResult(hash: r.str('hash'));
  }

  @override
  String get method => 'kernel.hash';

  /// 哈希结果
  final String hash;

  @override
  Map<String, Object?> toJson() => {'hash': hash};
}

/// `pit.ingest` params。
final class PitIngestParams extends RpcParams {
  const PitIngestParams({
    required this.source,
    required this.path,
    this.declared,
    required this.idempotencyKey,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory PitIngestParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return PitIngestParams(
      source: r.str('source'),
      path: r.str('path'),
      declared: r.objOpt('declared'),
      idempotencyKey: r.str('idempotency_key'),
    );
  }

  @override
  String get method => 'pit.ingest';

  /// 中间文件来源描述
  final String source;

  /// 中间文件绝对路径
  final String path;

  /// 声明的时点与映射信息
  final Map<String, Object?>? declared;

  /// 幂等键
  final String idempotencyKey;

  @override
  Map<String, Object?> toJson() => {
    'source': source,
    'path': path,
    'declared': declared,
    'idempotency_key': idempotencyKey,
  };
}

/// `pit.ingest` result。
final class PitIngestResult extends RpcResult {
  const PitIngestResult({
    required this.series,
    required this.derivedRecomputed,
    required this.coverageGate,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory PitIngestResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return PitIngestResult(
      series: r.listOf('series', (e) => PitSeries.parse(e.raw)),
      derivedRecomputed: r.strings('derived_recomputed'),
      coverageGate: CoverageGate.parse(r.obj('coverage_gate')),
    );
  }

  @override
  String get method => 'pit.ingest';

  /// 写入的序列
  final List<PitSeries> series;

  /// 重算的派生序列 ID
  final List<String> derivedRecomputed;

  /// 覆盖率守门结论
  final CoverageGate coverageGate;

  @override
  Map<String, Object?> toJson() => {
    'series': series,
    'derived_recomputed': derivedRecomputed,
    'coverage_gate': coverageGate,
  };
}

/// `signal.compute` params。
final class SignalComputeParams extends RpcParams {
  const SignalComputeParams({required this.asOf});

  /// 从 JSON 对象解析（解析即校验）。
  factory SignalComputeParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return SignalComputeParams(asOf: r.str('as_of'));
  }

  @override
  String get method => 'signal.compute';

  /// 时点
  final String asOf;

  @override
  Map<String, Object?> toJson() => {'as_of': asOf};
}

/// `signal.compute` result。
final class SignalComputeResult extends RpcResult {
  const SignalComputeResult({
    required this.signalId,
    required this.value,
    required this.dims,
    required this.missingDims,
    required this.limitations,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory SignalComputeResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return SignalComputeResult(
      signalId: r.str('signal_id'),
      value: r.number('value'),
      dims: r.obj('dims'),
      missingDims: r.strings('missing_dims'),
      limitations: r.strings('limitations'),
    );
  }

  @override
  String get method => 'signal.compute';

  /// 信号 ID
  final String signalId;

  /// 压力概率
  final double value;

  /// 各维度贡献
  final Map<String, Object?> dims;

  /// 缺席维度（不参与计算，禁止填充）
  final List<String> missingDims;

  /// 局限性说明
  final List<String> limitations;

  @override
  Map<String, Object?> toJson() => {
    'signal_id': signalId,
    'value': value,
    'dims': dims,
    'missing_dims': missingDims,
    'limitations': limitations,
  };
}

/// `tools.invoke` params。
final class ToolsInvokeParams extends RpcParams {
  const ToolsInvokeParams({
    required this.tool,
    required this.params,
    required this.idempotencyKey,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory ToolsInvokeParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return ToolsInvokeParams(
      tool: ToolName.parse(r.str('tool')),
      params: r.obj('params'),
      idempotencyKey: r.str('idempotency_key'),
    );
  }

  @override
  String get method => 'tools.invoke';

  /// 工具名（须在 tools.json 注册表内）
  final ToolName tool;

  /// 工具参数（按 `tools/<tool>.params.schema.json`）
  final Map<String, Object?> params;

  /// 幂等键
  final String idempotencyKey;

  @override
  Map<String, Object?> toJson() => {
    'tool': tool.wire,
    'params': params,
    'idempotency_key': idempotencyKey,
  };
}

/// `tools.invoke` result。
final class ToolsInvokeResult extends RpcResult {
  const ToolsInvokeResult({required this.evidence});

  /// 从 JSON 对象解析（解析即校验）。
  factory ToolsInvokeResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return ToolsInvokeResult(evidence: ToolEvidence.parse(r.obj('evidence')));
  }

  @override
  String get method => 'tools.invoke';

  /// 工具产出的证据
  final ToolEvidence evidence;

  @override
  Map<String, Object?> toJson() => {'evidence': evidence};
}

/// `workspace.info` params。
final class WorkspaceInfoParams extends RpcParams {
  const WorkspaceInfoParams();

  /// 从 JSON 对象解析（解析即校验）。
  factory WorkspaceInfoParams.parse(Object? json) {
    JsonReader(json, 'params').requireKeys(<String>{});
    return const WorkspaceInfoParams();
  }

  @override
  String get method => 'workspace.info';

  @override
  Map<String, Object?> toJson() => {};
}

/// `workspace.info` result。
final class WorkspaceInfoResult extends RpcResult {
  const WorkspaceInfoResult({
    required this.path,
    required this.sizeBytes,
    required this.schemaVersion,
    required this.seriesCount,
    required this.obsCount,
    this.lastIngestAt,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory WorkspaceInfoResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return WorkspaceInfoResult(
      path: r.str('path'),
      sizeBytes: r.integer('size_bytes'),
      schemaVersion: r.integer('schema_version'),
      seriesCount: r.integer('series_count'),
      obsCount: r.integer('obs_count'),
      lastIngestAt: r.strOpt('last_ingest_at'),
    );
  }

  @override
  String get method => 'workspace.info';

  /// 工作区路径
  final String path;

  /// 占用字节数
  final int sizeBytes;

  /// schema 版本
  final int schemaVersion;

  /// 序列数
  final int seriesCount;

  /// 观测总数
  final int obsCount;

  /// 最近一次入库时刻
  final String? lastIngestAt;

  @override
  Map<String, Object?> toJson() => {
    'path': path,
    'size_bytes': sizeBytes,
    'schema_version': schemaVersion,
    'series_count': seriesCount,
    'obs_count': obsCount,
    'last_ingest_at': lastIngestAt,
  };
}

/// `workspace.migrate` params。
final class WorkspaceMigrateParams extends RpcParams {
  const WorkspaceMigrateParams({required this.targetVersion});

  /// 从 JSON 对象解析（解析即校验）。
  factory WorkspaceMigrateParams.parse(Object? json) {
    final r = JsonReader(json, 'params');
    return WorkspaceMigrateParams(targetVersion: r.integer('target_version'));
  }

  @override
  String get method => 'workspace.migrate';

  /// 目标 schema 版本
  final int targetVersion;

  @override
  Map<String, Object?> toJson() => {'target_version': targetVersion};
}

/// `workspace.migrate` result。
final class WorkspaceMigrateResult extends RpcResult {
  const WorkspaceMigrateResult({required this.from, required this.to});

  /// 从 JSON 对象解析（解析即校验）。
  factory WorkspaceMigrateResult.parse(Object? json) {
    final r = JsonReader(json, 'result');
    return WorkspaceMigrateResult(from: r.integer('from'), to: r.integer('to'));
  }

  @override
  String get method => 'workspace.migrate';

  /// 迁移前版本
  final int from;

  /// 迁移后版本
  final int to;

  @override
  Map<String, Object?> toJson() => {'from': from, 'to': to};
}
