import 'dart:io';

import 'package:path/path.dart' as p;

/// 密钥存储（docs/02 F1-2、F10-2）。
///
/// 界面永不回显明文，只显示 [maskSecret] 的结果。
///
/// shortcut: 当前所有平台都用受限权限文件（0600）；Windows DPAPI 需要
/// `win32`/`ffi` 作为直接依赖（本工程不允许自行加依赖），由 Lead 加入后
/// 换成 `_DpapiStore` 即可，接口不变。降级必须让 UI 明示，见 [osEncrypted]。
abstract interface class SecretStore {
  /// 读取明文；不存在返回 null。
  Future<String?> read(String key);

  /// 写入（覆盖）。
  Future<void> write(String key, String value);

  /// 删除。
  Future<void> delete(String key);

  /// 是否使用系统级加密（决定 UI 是否需要提示降级）。
  bool get osEncrypted;
}

/// 打开密钥存储（目录不存在则创建）。
Future<SecretStore> openSecretStore(String secretsDir) async {
  await Directory(secretsDir).create(recursive: true);
  return FileSecretStore(secretsDir);
}

/// 脱敏显示：`sk-1234567890abcd` → `sk-****abcd`。
String maskSecret(String value) {
  if (value.isEmpty) {
    return '';
  }
  final tail = value.length <= 4 ? '' : value.substring(value.length - 4);
  final prefix = value.startsWith('sk-') ? 'sk-' : '';
  return '$prefix****$tail';
}

/// 受限权限文件存储。
final class FileSecretStore implements SecretStore {
  /// [dir] 为密钥目录。
  FileSecretStore(this.dir);

  /// 密钥目录。
  final String dir;

  @override
  bool get osEncrypted => false;

  File _file(String key) => File(p.join(dir, '$key.secret'));

  @override
  Future<String?> read(String key) async {
    final file = _file(key);
    if (!await file.exists()) {
      return null;
    }
    return file.readAsString();
  }

  @override
  Future<void> write(String key, String value) async {
    final file = _file(key);
    await file.writeAsString(value, flush: true);
    if (!Platform.isWindows) {
      // 0600：仅当前用户可读写。
      await Process.run('chmod', ['600', file.path]);
    }
  }

  @override
  Future<void> delete(String key) async {
    final file = _file(key);
    if (await file.exists()) {
      await file.delete();
    }
  }
}
