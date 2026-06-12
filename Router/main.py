import asyncio
import threading
from ui.main_window import MainWindow
from functions.csv_parser import parse_csv_with_mapping
from functions.helpers import log
from modules.axeane_session import run
from data.migrate_formulas import migrate

stop_event = threading.Event()

def on_process_data(mapping: dict, raw_data: list[dict], doc_type: str, update_ui_callback=None):
    log(f"Processing data for document type: {doc_type}...")
    entries = parse_csv_with_mapping(mapping, raw_data, doc_type)
    
    unbalanced = [e for e in entries if not e["balanced"]]
    if unbalanced:
        log(f"⚠️ WARNING: {len(unbalanced)} unbalanced entries will be skipped locally.")

    valid_count = len(entries) - len(unbalanced)
    if valid_count == 0:
        log("❌ No valid entries to process. Aborting.")
        return

    log(f"🚀 Starting automation for {valid_count} entries...")
    stop_event.clear()
    
    def run_async():
        try:
            asyncio.run(run(entries, update_ui_callback, stop_event))
            log("✅ Automation finished successfully!")
        except Exception as e:
            log(f"❌ Automation failed: {e}")

    threading.Thread(target=run_async, daemon=True).start()

def stop_automation():
    log("🛑 Stop requested by user...")
    stop_event.set()

def main() -> None:
    log("Checking/running formulas database migration...")
    try:
        migrate()
    except Exception as e:
        log(f"⚠️ Migration failed/skipped: {e}")
    log("Starting Axeane Kompta Automation UI...")
    app = MainWindow(on_process_callback=on_process_data, on_stop_callback=stop_automation)
    app.run()

if __name__ == "__main__":
    main()
    