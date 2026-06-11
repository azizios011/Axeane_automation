import asyncio
from ui.main_window import MainWindow
from functions.csv_parser import parse_csv_with_mapping
from functions.helpers import log
from modules.axeane_session import run

# 🆕 Add doc_type: str to the parameters
def on_process_data(mapping: dict, raw_data: list[dict], doc_type: str):
    log(f"Processing data for document type: {doc_type}...")
    
    # 🆕 Pass doc_type to the parser
    entries = parse_csv_with_mapping(mapping, raw_data, doc_type)
    
    unbalanced = [e for e in entries if not e["balanced"]]
    if unbalanced:
        log(f"⚠️ WARNING: {len(unbalanced)} unbalanced entries will be skipped:")
        for e in unbalanced:
            log(f"  - {e['docRef']}")

    valid_count = len(entries) - len(unbalanced)
    if valid_count == 0:
        log("❌ No valid entries to process. Aborting.")
        return

    log(f"🚀 Starting automation for {valid_count} entries...")
    try:
        asyncio.run(run(entries))
        log("✅ Automation finished successfully!")
    except Exception as e:
        log(f"❌ Automation failed: {e}")
        
def main() -> None:
    log("Starting Axeane Kompta Automation UI...")
    app = MainWindow(on_process_callback=on_process_data)
    app.run()

if __name__ == "__main__":
    main()
    