import 'contract_format_exception.dart';

/// 规范化 JSON 序列化：与旧版 Python `json.dumps(obj, sort_keys=True,
/// separators=(",", ":"), ensure_ascii=False)` **逐字节一致**。
///
/// 与 Python 的差异已在 [pythonReprDouble] 内对齐：
/// - 键按 Unicode 码位排序（Python `sort_keys` 语义）；
/// - 分隔符无空格；
/// - 非 ASCII 字符不转义（`ensure_ascii=False`）；
/// - 浮点按 Python `repr(float)` 输出（`1e+16` / `1e-05` / `-0.0`）；
/// - NaN / Inf 归一为 `null`（旧版 `to_native` 语义）。
///
/// 输入限定为 JSON 安全值：`Map` / `List` / `String` / `num` / `bool` / `null`。
String canonicalJson(Object? value) {
  final buffer = StringBuffer();
  _write(buffer, value);
  return buffer.toString();
}

void _write(StringBuffer buffer, Object? value) {
  if (value == null) {
    buffer.write('null');
    return;
  }
  if (value is bool) {
    buffer.write(value ? 'true' : 'false');
    return;
  }
  if (value is int) {
    buffer.write(value.toString());
    return;
  }
  if (value is double) {
    buffer.write(pythonReprDouble(value));
    return;
  }
  if (value is num) {
    buffer.write(pythonReprDouble(value.toDouble()));
    return;
  }
  if (value is String) {
    _writeString(buffer, value);
    return;
  }
  if (value is List<Object?>) {
    buffer.write('[');
    for (var i = 0; i < value.length; i++) {
      if (i > 0) {
        buffer.write(',');
      }
      _write(buffer, value[i]);
    }
    buffer.write(']');
    return;
  }
  if (value is Map<Object?, Object?>) {
    final keys = value.keys.map((k) {
      if (k is! String) {
        throw const ContractFormatException('JSON 对象的键必须是字符串');
      }
      return k;
    }).toList()..sort(compareCodePoints);
    buffer.write('{');
    for (var i = 0; i < keys.length; i++) {
      if (i > 0) {
        buffer.write(',');
      }
      _writeString(buffer, keys[i]);
      buffer.write(':');
      _write(buffer, value[keys[i]]);
    }
    buffer.write('}');
    return;
  }
  throw ContractFormatException('不支持的 JSON 值类型：${value.runtimeType}');
}

/// Python `json.dumps` 的字符串转义（`ensure_ascii=False`）。
void _writeString(StringBuffer buffer, String value) {
  buffer.write('"');
  for (final unit in value.codeUnits) {
    switch (unit) {
      case 0x22:
        buffer.write(r'\"');
      case 0x5C:
        buffer.write(r'\\');
      case 0x08:
        buffer.write(r'\b');
      case 0x0C:
        buffer.write(r'\f');
      case 0x0A:
        buffer.write(r'\n');
      case 0x0D:
        buffer.write(r'\r');
      case 0x09:
        buffer.write(r'\t');
      default:
        if (unit < 0x20) {
          buffer
            ..write(r'\u')
            ..write(unit.toRadixString(16).padLeft(4, '0'));
        } else {
          buffer.writeCharCode(unit);
        }
    }
  }
  buffer.write('"');
}

/// 按 Unicode 码位比较字符串（Python `str` 的比较语义）。
///
/// Dart 的 `String.compareTo` 按 UTF-16 码元比较，对补充平面字符与
/// U+E000–U+FFFF 区间的相对顺序与 Python 不同，故此处按码位比较。
int compareCodePoints(String a, String b) {
  final left = a.runes.toList(growable: false);
  final right = b.runes.toList(growable: false);
  final len = left.length < right.length ? left.length : right.length;
  for (var i = 0; i < len; i++) {
    if (left[i] != right[i]) {
      return left[i] - right[i];
    }
  }
  return left.length - right.length;
}

/// Python `repr(float)` 兼容输出。
///
/// Python 规则：取能往返的最短十进制数字串 `digits`，令
/// `decpt` 满足 值 = 0.digits × 10^decpt；当 `decpt <= -4` 或 `decpt > 16`
/// 时用科学计数法（指数至少两位、带符号），否则用定点写法，
/// 整数值补 `.0`。
///
/// Dart 的 `double.toString` 数字位相同但排版不同（`10000000000000000.0`
/// vs `1e+16`，`0.00001` vs `1e-05`），故这里从 Dart 的最短往返表示中
/// 还原数字位与 `decpt`，再按 Python 规则排版。
String pythonReprDouble(double value) {
  if (value.isNaN || value.isInfinite) {
    return 'null';
  }
  if (value == 0) {
    return value.isNegative ? '-0.0' : '0.0';
  }
  final negative = value.isNegative;
  final text = value.abs().toString();

  var mantissa = text;
  var exponent = 0;
  final eIndex = text.indexOf('e');
  if (eIndex >= 0) {
    mantissa = text.substring(0, eIndex);
    exponent = int.parse(text.substring(eIndex + 1));
  }

  final dotIndex = mantissa.indexOf('.');
  final fracLen = dotIndex < 0 ? 0 : mantissa.length - dotIndex - 1;
  final rawDigits = dotIndex < 0 ? mantissa : mantissa.replaceFirst('.', '');

  // 去掉首尾零（首零不影响数值，尾零并入指数）。
  var start = 0;
  while (start < rawDigits.length - 1 && rawDigits[start] == '0') {
    start++;
  }
  var end = rawDigits.length;
  while (end > start + 1 && rawDigits[end - 1] == '0') {
    end--;
  }
  final digits = rawDigits.substring(start, end);
  final trailingZeros = rawDigits.length - end;

  // 值 = digits × 10^(exponent - fracLen + trailingZeros) = 0.digits × 10^decpt
  final decpt = exponent - fracLen + trailingZeros + digits.length;

  final buffer = StringBuffer();
  if (negative) {
    buffer.write('-');
  }
  if (decpt <= -4 || decpt > 16) {
    buffer.write(digits[0]);
    if (digits.length > 1) {
      buffer
        ..write('.')
        ..write(digits.substring(1));
    }
    buffer.write('e');
    final exp = decpt - 1;
    buffer.write(exp < 0 ? '-' : '+');
    buffer.write(exp.abs().toString().padLeft(2, '0'));
  } else if (decpt <= 0) {
    buffer
      ..write('0.')
      ..write('0' * -decpt)
      ..write(digits);
  } else if (decpt >= digits.length) {
    buffer
      ..write(digits)
      ..write('0' * (decpt - digits.length))
      ..write('.0');
  } else {
    buffer
      ..write(digits.substring(0, decpt))
      ..write('.')
      ..write(digits.substring(decpt));
  }
  return buffer.toString();
}
