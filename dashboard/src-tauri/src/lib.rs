// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod db;
mod sqlite;

use std::process::Command;

/// Trigger a manual scraper run (shells out to run_scraper.sh).
#[tauri::command]
fn run_scraper(days: u32) -> Result<String, String> {
    let output = Command::new("bash")
        .arg("../scraper/run_scraper.sh")
        .env("SCRAPER_DAYS", days.to_string())
        .output()
        .map_err(|e| e.to_string())?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).to_string())
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            db::get_summary,
            db::get_pr_list,
            db::get_run_distribution,
            db::get_error_breakdown,
            db::get_stage_failures,
            db::get_rerun_stats,
            db::get_pr_open_times,
            db::get_scrape_meta,
            run_scraper,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
