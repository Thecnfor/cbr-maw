"""把旧版真实 PIT 库导出为 NDJSON（Rust kernel 的 pit.ingest 中间文件形态 / Go collector 的规范化输出形态）。

用法（需要 duckdb 绑定）：
    uv venv /tmp/cbrvenv --python 3.14
    uv pip install --python /tmp/cbrvenv/bin/python duckdb
    /tmp/cbrvenv/bin/python data/seed/export_real_pit.py

来源（只读）：/mnt/shared/recently/commorcial/data/pit_real.duckdb
输出：data/seed/pit_real_obs.jsonl、data/seed/documents.jsonl（**不入库**，由本脚本重建）
"""
import json, os, sys

SRC = os.environ.get("CBR_PIT_DB", "/mnt/shared/recently/commorcial/data/pit_real.duckdb")
OUT = os.path.dirname(os.path.abspath(__file__))

def main():
    try:
        import duckdb
    except ImportError:
        sys.exit("需要 duckdb：uv pip install --python <venv>/bin/python duckdb")
    con = duckdb.connect(SRC, read_only=True)
    rows = con.sql("""
      select o.series_id, o.obs_date, o.value, o.release_time, o.source, o.unit,
             m.frequency, m.release_lag_days, m.pit_grade, m.coverage_start, m.coverage_end,
             m.name, m.notes
      from series_obs o left join series_meta m using(series_id)
      order by o.series_id, o.obs_date
    """).fetchall()
    cols = ["series_id","obs_date","value","release_time","source","unit","frequency",
            "release_lag_days","pit_grade","coverage_start","coverage_end","name","notes"]
    with open(os.path.join(OUT, "pit_real_obs.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            d = dict(zip(cols, r))
            for k in ("obs_date","release_time","coverage_start","coverage_end"):
                d[k] = str(d[k])
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    docs = con.sql("select doc_id, publish_time, source, title, body, url, hash from documents").fetchall()
    with open(os.path.join(OUT, "documents.jsonl"), "w", encoding="utf-8") as f:
        for r in docs:
            d = dict(zip(["doc_id","publish_time","source","title","body","url","hash"], r))
            d["publish_time"] = str(d["publish_time"])
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"obs={len(rows)} docs={len(docs)} -> {OUT}")

if __name__ == "__main__":
    main()
