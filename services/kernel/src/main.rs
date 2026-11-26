//! kernel sidecar 入口：`kernel.exe --workspace <path> --data-home <path> --resource-home <path> --log-level <lvl>`

use std::io::{self, BufReader};

fn main() {
    let args = std::env::args().skip(1);
    let mut kernel = match cbr_kernel::Kernel::from_args(args) {
        Ok(kernel) => kernel,
        Err(err) => {
            eprintln!(
                "{}",
                serde_json::json!({
                    "ts": chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6fZ").to_string(),
                    "level": "error",
                    "sidecar": "kernel",
                    "msg": format!("启动失败: {err}"),
                })
            );
            std::process::exit(2);
        }
    };

    let stdin = io::stdin();
    let stdout = io::stdout();
    let reader = BufReader::new(stdin.lock());
    if let Err(err) = cbr_kernel::serve(&mut kernel, reader, stdout.lock()) {
        eprintln!(
            "{}",
            serde_json::json!({
                "ts": chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S%.6fZ").to_string(),
                "level": "error",
                "sidecar": "kernel",
                "msg": format!("stdio 循环异常: {err}"),
            })
        );
        std::process::exit(1);
    }
}
