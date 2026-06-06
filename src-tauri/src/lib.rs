use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut};
use tauri_plugin_shell::ShellExt;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::Duration;

/// 通过原生 TCP 直接向后端发送 HTTP GET /health 请求，
/// 完全绕过 WebView2 的网络栈（不受 FlClash 等系统代理影响）。
#[tauri::command]
fn health_check() -> Result<String, String> {
    let addr: std::net::SocketAddr = "127.0.0.1:9100"
        .parse()
        .map_err(|e: std::net::AddrParseError| e.to_string())?;
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_secs(4))
        .map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(Duration::from_secs(4))).ok();
    stream
        .write_all(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .map_err(|e| e.to_string())?;
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|e| e.to_string())?;
    // 取 HTTP 响应体（\r\n\r\n 之后的部分）
    if let Some(body_start) = response.find("\r\n\r\n") {
        Ok(response[body_start + 4..].to_string())
    } else {
        Err("Invalid HTTP response (no header separator)".to_string())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            // 0. 后台静默检查更新（启动 5 秒后）
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                if let Ok(updater) = tauri_plugin_updater::UpdaterExt::updater(&handle) {
                    if let Ok(Some(update)) = updater.check().await {
                        // 通知前端有新版本
                        let _ = handle.emit("update-available", serde_json::json!({
                            "version": update.version,
                            "body": update.body.clone().unwrap_or_default(),
                        }));
                    }
                }
            });
            // 1. 启动 Python 后端 sidecar（带自动重启守护）
            //    dev 模式: 请手动运行 python backend/websocket_server.py
            //    release 模式: 自动从 resources 目录启动 anima-server.exe，
            //                   崩溃后按指数退避自动重启，连续失败时通知前端
            #[cfg(not(debug_assertions))]
            {
                let sidecar_handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    use tauri_plugin_shell::process::CommandEvent;
                    let mut consecutive_failures: u32 = 0;
                    loop {
                        let started_at = std::time::Instant::now();
                        // 每轮重新创建 sidecar 命令并启动
                        let spawn_result = sidecar_handle
                            .shell()
                            .sidecar("anima-server")
                            .and_then(|cmd| cmd.spawn());

                        match spawn_result {
                            Ok((mut rx, _child)) => {
                                // 进程已起来，通知前端后端恢复
                                let _ = sidecar_handle.emit("backend-up", ());
                                // 监听 sidecar 输出，直到进程退出
                                while let Some(event) = rx.recv().await {
                                    match event {
                                        CommandEvent::Stdout(line) => {
                                            let s = String::from_utf8_lossy(&line);
                                            println!("[Backend] {}", s.trim_end());
                                        }
                                        CommandEvent::Stderr(line) => {
                                            let s = String::from_utf8_lossy(&line);
                                            eprintln!("[Backend] {}", s.trim_end());
                                        }
                                        CommandEvent::Error(e) => {
                                            eprintln!("[Backend] error: {e}");
                                        }
                                        CommandEvent::Terminated(status) => {
                                            eprintln!("[Backend] terminated: {:?}", status);
                                            break;
                                        }
                                        _ => {}
                                    }
                                }
                                // 进程退出：活够 30s 视为"正常运行后崩溃"，重置失败计数
                                if started_at.elapsed().as_secs() >= 30 {
                                    consecutive_failures = 0;
                                } else {
                                    consecutive_failures += 1;
                                }
                            }
                            Err(e) => {
                                eprintln!("[Anima] 后端启动失败: {e}");
                                consecutive_failures += 1;
                            }
                        }

                        // 连续快速失败 ≥5 次：通知前端展示"后端不可用"提示
                        if consecutive_failures >= 5 {
                            let _ = sidecar_handle.emit(
                                "backend-down",
                                serde_json::json!({ "failures": consecutive_failures }),
                            );
                        }

                        // 指数退避：1,2,4,8,16,最多 30 秒
                        let shift = std::cmp::min(consecutive_failures, 5);
                        let backoff = std::cmp::min(30u64, 1u64 << shift);
                        eprintln!(
                            "[Anima] {}秒后重启后端 (连续失败 {} 次)",
                            backoff, consecutive_failures
                        );
                        tokio::time::sleep(std::time::Duration::from_secs(backoff)).await;
                    }
                });
            }

            // 2. 注册全局热键 Ctrl+Shift+H — 显示/隐藏窗口（失败时仅记录，不崩溃）
            let shortcut = Shortcut::new(
                Some(Modifiers::CONTROL | Modifiers::SHIFT),
                Code::KeyH,
            );
            let app_handle = app.handle().clone();
            let _ = app.global_shortcut().on_shortcut(shortcut, move |_app, _shortcut, _event| {
                if let Some(w) = app_handle.get_webview_window("main") {
                    let visible = w.is_visible().unwrap_or(false);
                    if visible && w.is_focused().unwrap_or(false) {
                        let _ = w.hide();
                    } else {
                        let _ = w.show();
                        let _ = w.set_focus();
                    }
                }
            });
            // 注：若 Ctrl+Shift+H 被其它应用占用，热键注册失败但 Anima 照常启动

            // 3. 系统托盘
            let show = MenuItem::with_id(app, "show", "显示 Anima", true, None::<&str>)?;
            let hide = MenuItem::with_id(app, "hide", "最小化到托盘", true, None::<&str>)?;
            let sep  = tauri::menu::PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;

            let menu = Menu::with_items(app, &[&show, &hide, &sep, &quit])?;

            let _tray = TrayIconBuilder::new()
                .menu(&menu)
                .tooltip("Anima  (Ctrl+Shift+H 呼出)")
                .icon(app.default_window_icon().unwrap().clone())
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "hide" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.hide();
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(w) = app.get_webview_window("main") {
                            let visible = w.is_visible().unwrap_or(false);
                            if visible {
                                let _ = w.hide();
                            } else {
                                let _ = w.show();
                                let _ = w.set_focus();
                            }
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            // 关闭窗口时最小化到托盘，不退出进程
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                window.hide().unwrap_or_default();
                api.prevent_close();
            }
        })
        .invoke_handler(tauri::generate_handler![health_check])
        .run(tauri::generate_context!())
        .expect("error while running Anima");
}
