import 'dart:io';

import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:path/path.dart' as p;

import '../../core/clock.dart';
import '../../core/errors.dart';

/// 投递结果（UI 直接展示）。
final class InboxIngestOutcome {
  const InboxIngestOutcome({
    required this.message,
    this.accepted = 0,
    this.rejected = 0,
  });

  /// 中文提示（三段式或简洁成功文案）。
  final String message;

  /// 接受文件数。
  final int accepted;

  /// 拒绝文件数。
  final int rejected;
}

/// 拖入文件 → 复制到可写根 inbox/ → 调 `inbox.ingest` → 展示清洗结果与被拒原因。
///
/// 支持文件与目录（目录递归展开）；不支持的扩展名显式列出，不静默忽略。
final class InboxIngestService {
  /// 创建服务。
  ///
  /// 依赖倒置（docs/09 §3 第 7 条）：data 层不 import app 层，改为注入所需能力。
  InboxIngestService({required this.inboxDir, required this.ingestInbox});

  /// 可写根下的投递箱目录。
  final String inboxDir;

  /// 把文件交给 sidecar 清洗入库（由上层注入）。
  final Future<InboxIngestResult> Function({required String path, String? asOf})
  ingestInbox;

  /// 允许投递的扩展名（清洗在 collector 侧完成）。
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

  /// 处理一个路径。
  Future<InboxIngestOutcome> ingest(String sourcePath) async {
    final type = FileSystemEntity.typeSync(sourcePath);
    if (type == FileSystemEntityType.notFound) {
      return InboxIngestOutcome(
        message: '未能读取文件。路径不存在或已被移动。可重新选择文件后重试。',
        rejected: 1,
      );
    }
    final files = <String>[];
    if (type == FileSystemEntityType.directory) {
      await for (final entity in Directory(sourcePath).list(recursive: true)) {
        if (entity is File) {
          files.add(entity.path);
        }
      }
    } else {
      files.add(sourcePath);
    }

    final unsupported = files
        .where(
          (path) =>
              !supportedExtensions.contains(p.extension(path).toLowerCase()),
        )
        .map((path) => p.basename(path))
        .toList();
    final supported = files
        .where(
          (path) =>
              supportedExtensions.contains(p.extension(path).toLowerCase()),
        )
        .toList();
    if (supported.isEmpty) {
      return InboxIngestOutcome(
        message:
            '未加入投递箱。不支持的文件类型：${unsupported.join('、')}。'
            '可导出为 CSV 或 XLSX 后重试。',
        rejected: unsupported.length,
      );
    }

    final inboxDir = this.inboxDir;
    await Directory(inboxDir).create(recursive: true);
    var accepted = 0;
    var rejected = unsupported.length;
    final reasons = <String>[
      if (unsupported.isNotEmpty) '不支持的文件类型：${unsupported.join('、')}',
    ];
    for (final path in supported) {
      final target = p.join(inboxDir, p.basename(path));
      try {
        await File(path).copy(target);
      } on FileSystemException catch (e) {
        rejected++;
        reasons.add(
          '${p.basename(path)} 复制失败（${e.osError?.message ?? e.message}）',
        );
        continue;
      }
      try {
        final result = await ingestInbox(path: target, asOf: Clock.asOfNow());
        accepted += result.accepted.length;
        rejected += result.rejected.length;
        for (final file in result.accepted) {
          reasons.add(
            '${file.file} → ${file.seriesId}（${file.rows} 行，'
            '${file.releaseTimeRule}）',
          );
        }
        for (final file in result.rejected) {
          reasons.add('${file.file} 被拒：${file.reason}');
        }
      } on AppError catch (e) {
        rejected++;
        reasons.add('${p.basename(path)} 清洗失败：${e.why}');
      }
    }
    return InboxIngestOutcome(
      message: reasons.isEmpty
          ? '已加入投递箱，正在清洗入库。'
          : '投递完成：接受 $accepted 个文件，拒绝 $rejected 个。${reasons.join('；')}',
      accepted: accepted,
      rejected: rejected,
    );
  }
}
