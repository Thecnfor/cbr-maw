import 'dart:io';

import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:flutter/foundation.dart' show ChangeNotifier;
import 'package:path/path.dart' as p;

import '../core/clock.dart';
import '../core/errors.dart';
import 'app_state.dart';

/// 单个文件的投递结果状态（docs/22 屏 3）。
enum IngestStatus {
  /// 已入库。
  ingested('ingested', '已入库'),

  /// 被拒（格式 / 编码 / 表头）。
  rejected('rejected', '被拒'),

  /// 需人工确认（列名映射未命中）。
  needsConfirmation('needs_confirmation', '需人工确认');

  const IngestStatus(this.wire, this.label);

  /// 字面量。
  final String wire;

  /// 中文标签。
  final String label;
}

/// 一次投递里单个文件的记录。
final class IngestRecord {
  const IngestRecord({
    required this.fileName,
    required this.originalPath,
    required this.status,
    this.reason,
    this.seriesId,
    this.rows,
    this.batchId,
    this.declaredSource,
    required this.at,
  });

  /// 文件名（原文件保留在投递箱，不删除）。
  final String fileName;

  /// 原始路径（供「原文件保留」说明与重试）。
  final String originalPath;

  /// 状态。
  final IngestStatus status;

  /// 被拒或需确认的原因（已入库时为 null）。
  final String? reason;

  /// 识别到的序列 ID（已入库时）。
  final String? seriesId;

  /// 行数（已入库时）。
  final int? rows;

  /// 清洗批次。
  final String? batchId;

  /// 用户声明的来源（重试时可改）。
  final String? declaredSource;

  /// 时间。
  final String at;

  /// 复制一份（改声明来源后重试）。
  IngestRecord copyWith({String? declaredSource}) => IngestRecord(
    fileName: fileName,
    originalPath: originalPath,
    status: status,
    reason: reason,
    seriesId: seriesId,
    rows: rows,
    batchId: batchId,
    declaredSource: declaredSource ?? this.declaredSource,
    at: at,
  );
}

/// 投递日志（新→旧）。窗口拖拽与输入框附件区共用同一份。
final class InboxLog extends ChangeNotifier {
  final _records = <IngestRecord>[];

  /// 记录（新→旧）。
  List<IngestRecord> get records => List.unmodifiable(_records.reversed);

  /// 待处理（被拒 / 需确认）数量，用于侧栏角标。
  int get pendingCount =>
      _records.where((r) => r.status != IngestStatus.ingested).length;

  /// 追加记录。
  void add(IngestRecord record) {
    _records.add(record);
    notifyListeners();
  }

  /// 清空。
  void clear() {
    _records.clear();
    notifyListeners();
  }
}

/// 投递器：复制到可写根 inbox/ → `inbox.ingest` → 逐文件记录结果。
///
/// 与 `InboxIngestService` 同一清洗链路（同一个 `inbox.ingest` RPC），
/// 区别是保留逐文件结构以便界面展示原因；原文件一律保留。
final class InboxUploader {
  /// 创建投递器。
  const InboxUploader({
    required this.inboxDir,
    required this.ingestInbox,
    required this.log,
  });

  /// 从应用状态装配（生产路径）。
  factory InboxUploader.of(AppState state) => InboxUploader(
    inboxDir: state.paths.inboxDir,
    ingestInbox: state.repository.ingestInbox,
    log: state.inboxLog,
  );

  /// 可写根下的投递箱目录。
  final String inboxDir;

  /// `inbox.ingest` 调用（由上层注入，便于测试）。
  final Future<InboxIngestResult> Function({
    required String path,
    String? declaredSource,
  })
  ingestInbox;

  /// 投递日志。
  final InboxLog log;

  /// 允许的扩展名（清洗在 collector 侧完成）。
  static const supportedExtensions = {
    '.csv',
    '.tsv',
    '.xlsx',
    '.xls',
    '.json',
    '.jsonl',
    '.txt',
    '.zip',
  };

  /// 处理一组路径（目录递归展开）；返回追加的记录。
  Future<List<IngestRecord>> ingestAll(
    List<String> paths, {
    String? declaredSource,
  }) async {
    final out = <IngestRecord>[];
    for (final path in paths) {
      out.addAll(await ingest(path, declaredSource: declaredSource));
    }
    return out;
  }

  /// 处理单个路径。
  Future<List<IngestRecord>> ingest(
    String path, {
    String? declaredSource,
  }) async {
    final type = FileSystemEntity.typeSync(path);
    if (type == FileSystemEntityType.notFound) {
      return [
        _record(
          fileName: p.basename(path),
          originalPath: path,
          status: IngestStatus.rejected,
          reason: '路径不存在或已被移动',
          declaredSource: declaredSource,
        ),
      ];
    }
    final files = <String>[];
    if (type == FileSystemEntityType.directory) {
      await for (final entity in Directory(path).list(recursive: true)) {
        if (entity is File) {
          files.add(entity.path);
        }
      }
    } else {
      files.add(path);
    }

    final out = <IngestRecord>[];
    for (final file in files) {
      final ext = p.extension(file).toLowerCase();
      if (!supportedExtensions.contains(ext)) {
        out.add(
          _record(
            fileName: p.basename(file),
            originalPath: file,
            status: IngestStatus.rejected,
            reason: '不支持的格式（$ext）；可导出为 CSV 或 XLSX 后重试',
            declaredSource: declaredSource,
          ),
        );
        continue;
      }
      final target = p.join(inboxDir, p.basename(file));
      try {
        if (p.normalize(p.absolute(file)) != p.normalize(target)) {
          await Directory(inboxDir).create(recursive: true);
          await File(file).copy(target);
        }
      } on FileSystemException catch (e) {
        out.add(
          _record(
            fileName: p.basename(file),
            originalPath: file,
            status: IngestStatus.rejected,
            reason: '复制到投递箱失败（${e.osError?.message ?? e.message}）',
            declaredSource: declaredSource,
          ),
        );
        continue;
      }
      try {
        final result = await ingestInbox(
          path: target,
          declaredSource: declaredSource,
        );
        for (final accepted in result.accepted) {
          out.add(
            _record(
              fileName: p.basename(file),
              originalPath: target,
              status: IngestStatus.ingested,
              seriesId: accepted.seriesId,
              rows: accepted.rows,
              batchId: result.batchId,
              declaredSource: declaredSource,
            ),
          );
        }
        for (final rejected in result.rejected) {
          out.add(
            _record(
              fileName: rejected.file,
              originalPath: target,
              status: _classify(rejected.reason),
              reason: rejected.reason,
              batchId: result.batchId,
              declaredSource: declaredSource,
            ),
          );
        }
        if (result.accepted.isEmpty && result.rejected.isEmpty) {
          out.add(
            _record(
              fileName: p.basename(file),
              originalPath: target,
              status: IngestStatus.rejected,
              reason: '清洗后没有可入库的行（空表或全部为脏行）',
              batchId: result.batchId,
              declaredSource: declaredSource,
            ),
          );
        }
      } on AppError catch (e) {
        out.add(
          _record(
            fileName: p.basename(file),
            originalPath: target,
            status: IngestStatus.rejected,
            reason: e.why,
            declaredSource: declaredSource,
          ),
        );
      } on Object catch (e) {
        out.add(
          _record(
            fileName: p.basename(file),
            originalPath: target,
            status: IngestStatus.rejected,
            reason: '$e',
            declaredSource: declaredSource,
          ),
        );
      }
    }
    return out;
  }

  /// 映射失败类原因归到「需人工确认」，其余为「被拒」。
  ///
  /// shortcut: 按原因文案分类，collector 尚未返回结构化分类码；
  /// 契约新增 `rejected[].kind` 后改为读字段。
  static IngestStatus _classify(String reason) {
    // 只认「列名 / 映射 / 序列」类失败；编码识别失败仍算被拒。
    const mappingHints = ['列名映射', '映射失败', '列名', '序列未命中', '未命中序列'];
    return mappingHints.any(reason.contains)
        ? IngestStatus.needsConfirmation
        : IngestStatus.rejected;
  }

  IngestRecord _record({
    required String fileName,
    required String originalPath,
    required IngestStatus status,
    String? reason,
    String? seriesId,
    int? rows,
    String? batchId,
    String? declaredSource,
  }) {
    final record = IngestRecord(
      fileName: fileName,
      originalPath: originalPath,
      status: status,
      reason: reason,
      seriesId: seriesId,
      rows: rows,
      batchId: batchId,
      declaredSource: declaredSource,
      at: Clock.asOfNow(),
    );
    log.add(record);
    return record;
  }
}
