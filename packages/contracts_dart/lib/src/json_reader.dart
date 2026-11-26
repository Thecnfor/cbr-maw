import 'contract_format_exception.dart';

/// 契约 JSON 读取器：所有取值都在这里做类型与必填校验（解析即校验）。
///
/// 用法：`JsonReader(json, 'params').str('source_id')`；
/// 类型不符、字段缺失一律抛 [ContractFormatException]，并带上出错路径。
final class JsonReader {
  const JsonReader(Object? value, this.path) : _value = value;

  final Object? _value;

  /// 出错路径前缀（如 `params.sources[0]`）。
  final String path;

  /// 原始值（未经校验），仅供 `raw` 透传字段使用。
  Object? get raw => _value;

  /// 字段是否存在。
  bool has(String key) {
    final map = _asMap();
    return map.containsKey(key);
  }

  /// 校验必填字段全部存在。
  void requireKeys(Set<String> keys) {
    final map = _asMap();
    for (final key in keys) {
      if (!map.containsKey(key)) {
        throw ContractFormatException('缺少必填字段', path: '$path.$key');
      }
    }
  }

  /// 字符串（必填）。
  String str(String key) {
    final value = _asMap()[key];
    if (value is! String) {
      throw ContractFormatException(
        '期望字符串，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value;
  }

  /// 字符串（可选，缺失返回 null）。
  String? strOpt(String key) {
    final value = _asMap()[key];
    if (value == null) {
      return null;
    }
    if (value is! String) {
      throw ContractFormatException(
        '期望字符串，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value;
  }

  /// 整数（必填）。
  int integer(String key) {
    final value = _asMap()[key];
    if (value is! int) {
      throw ContractFormatException(
        '期望整数，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value;
  }

  /// 整数（可选，缺失返回 fallback）。
  int integerOpt(String key, {int fallback = 0}) {
    final value = _asMap()[key];
    if (value == null) {
      return fallback;
    }
    if (value is! int) {
      throw ContractFormatException(
        '期望整数，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value;
  }

  /// 数值（必填，接受 int 或 double）。
  double number(String key) {
    final value = _asMap()[key];
    if (value is! num) {
      throw ContractFormatException(
        '期望数值，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value.toDouble();
  }

  /// 数值（可选，缺失返回 fallback）。
  double numberOpt(String key, {double fallback = 0}) {
    final value = _asMap()[key];
    if (value == null) {
      return fallback;
    }
    if (value is! num) {
      throw ContractFormatException(
        '期望数值，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value.toDouble();
  }

  /// 布尔（必填）。
  bool boolean(String key) {
    final value = _asMap()[key];
    if (value is! bool) {
      throw ContractFormatException(
        '期望布尔值，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value;
  }

  /// 布尔（可选，缺失返回 fallback）。
  bool booleanOpt(String key, {bool fallback = false}) {
    final value = _asMap()[key];
    if (value == null) {
      return fallback;
    }
    if (value is! bool) {
      throw ContractFormatException(
        '期望布尔值，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value;
  }

  /// 数组（必填）。
  List<Object?> list(String key) {
    final value = _asMap()[key];
    if (value is! List<Object?>) {
      throw ContractFormatException(
        '期望数组，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value;
  }

  /// 数组（可选，缺失返回 null）。
  List<Object?>? listOpt(String key) {
    final value = _asMap()[key];
    if (value == null) {
      return null;
    }
    if (value is! List<Object?>) {
      throw ContractFormatException(
        '期望数组，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value;
  }

  /// 对象（必填）。
  Map<String, Object?> obj(String key) {
    final value = _asMap()[key];
    if (value is! Map<String, Object?>) {
      throw ContractFormatException(
        '期望对象，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value;
  }

  /// 对象（可选，缺失返回 null）。
  Map<String, Object?>? objOpt(String key) {
    final value = _asMap()[key];
    if (value == null) {
      return null;
    }
    if (value is! Map<String, Object?>) {
      throw ContractFormatException(
        '期望对象，实际 ${value.runtimeType}',
        path: '$path.$key',
      );
    }
    return value;
  }

  /// 整数数组（必填）。
  List<int> integers(String key) =>
      listOf(key, (e) => _requireInt(e.raw, '$path.$key'));

  /// 整数数组（可选）。
  List<int>? integersOpt(String key) =>
      listOfOpt(key, (e) => _requireInt(e.raw, '$path.$key'));

  /// 数值数组（必填）。
  List<double> numbers(String key) =>
      listOf(key, (e) => _requireDouble(e.raw, '$path.$key'));

  /// 数值数组（可选）。
  List<double>? numbersOpt(String key) =>
      listOfOpt(key, (e) => _requireDouble(e.raw, '$path.$key'));

  /// 布尔数组（必填）。
  List<bool> booleans(String key) =>
      listOf(key, (e) => _requireBool(e.raw, '$path.$key'));

  /// 布尔数组（可选）。
  List<bool>? booleansOpt(String key) =>
      listOfOpt(key, (e) => _requireBool(e.raw, '$path.$key'));

  /// 任意值数组（必填）。
  List<Object?> values(String key) => list(key);

  /// 任意值数组（可选）。
  List<Object?>? valuesOpt(String key) => listOpt(key);

  /// 字符串数组（必填）。
  List<String> strings(String key) =>
      listOf(key, (e) => _requireString(e.raw, '$path.$key'));

  /// 字符串数组（可选）。
  List<String>? stringsOpt(String key) =>
      listOfOpt(key, (e) => _requireString(e.raw, '$path.$key'));

  /// 对象数组（必填）。
  List<Map<String, Object?>> objects(String key) =>
      listOf(key, (e) => _requireMap(e.raw, '$path.$key'));

  /// 对象数组（可选）。
  List<Map<String, Object?>>? objectsOpt(String key) =>
      listOfOpt(key, (e) => _requireMap(e.raw, '$path.$key'));

  /// 二维数组（必填）。
  List<List<Object?>> lists(String key) =>
      listOf(key, (e) => _requireList(e.raw, '$path.$key'));

  /// 二维数组（可选）。
  List<List<Object?>>? listsOpt(String key) =>
      listOfOpt(key, (e) => _requireList(e.raw, '$path.$key'));

  /// 数组元素逐项解析。
  List<T> listOf<T>(String key, T Function(JsonReader) parse) {
    final items = list(key);
    return List<T>.generate(
      items.length,
      (i) => parse(JsonReader(items[i], '$path.$key[$i]')),
      growable: false,
    );
  }

  /// 数组元素逐项解析（可选）。
  List<T>? listOfOpt<T>(String key, T Function(JsonReader) parse) {
    final items = listOpt(key);
    if (items == null) {
      return null;
    }
    return List<T>.generate(
      items.length,
      (i) => parse(JsonReader(items[i], '$path.$key[$i]')),
      growable: false,
    );
  }

  Map<String, Object?> _asMap() {
    final value = _value;
    if (value is! Map<String, Object?>) {
      throw ContractFormatException('期望对象，实际 ${value.runtimeType}', path: path);
    }
    return value;
  }
}

String _requireString(Object? value, String path) {
  if (value is! String) {
    throw ContractFormatException('期望字符串，实际 ${value.runtimeType}', path: path);
  }
  return value;
}

Map<String, Object?> _requireMap(Object? value, String path) {
  if (value is! Map<String, Object?>) {
    throw ContractFormatException('期望对象，实际 ${value.runtimeType}', path: path);
  }
  return value;
}

int _requireInt(Object? value, String path) {
  if (value is! int) {
    throw ContractFormatException('期望整数，实际 ${value.runtimeType}', path: path);
  }
  return value;
}

double _requireDouble(Object? value, String path) {
  if (value is! num) {
    throw ContractFormatException('期望数值，实际 ${value.runtimeType}', path: path);
  }
  return value.toDouble();
}

bool _requireBool(Object? value, String path) {
  if (value is! bool) {
    throw ContractFormatException('期望布尔值，实际 ${value.runtimeType}', path: path);
  }
  return value;
}

List<Object?> _requireList(Object? value, String path) {
  if (value is! List<Object?>) {
    throw ContractFormatException('期望数组，实际 ${value.runtimeType}', path: path);
  }
  return value;
}
