import tkinter as tk
from tkinter import ttk
from ui.pwa_settings_tab import PwaSettingsTab
from ui.import_tab import ImportTab
from ui.csv_table import CsvTableTab

class MainWindow:
    def __init__(self, on_process_callback, on_stop_callback):
        self.root = tk.Tk()
        self.root.title("Axeane Kompta Automation Studio")
        self.root.geometry("950x700")
        
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Accent.TButton", foreground="white", background="#0078d7", font=("Arial", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#005a9e")])

        self.on_process_callback = on_process_callback
        self.on_stop_callback = on_stop_callback
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.pwa_tab = PwaSettingsTab(self.notebook)
        self.notebook.add(self.pwa_tab, text=" 1. PWA Setup & Launch ")

        self.import_tab = ImportTab(self.notebook, on_data_loaded=self._on_data_loaded)
        self.notebook.add(self.import_tab, text=" 2. Import Data ")

        self.csv_table_tab = CsvTableTab(self.notebook, on_process=self._on_process, on_stop=self._on_stop)
        self.notebook.add(self.csv_table_tab, text=" 3. Configure & Process ")

    def _on_data_loaded(self, doc_type: str, file_path: str, data: list[dict]):
        self.csv_table_tab.load_data(doc_type, file_path, data)
        self.notebook.select(2)

    def _on_process(self, mapping: dict, data: list[dict], doc_type: str):
        if not self.pwa_tab.is_verified:
            tk.messagebox.showwarning("Verification Required", "Please complete Turnstile verification in Tab 1.")
            self.notebook.select(0)
            return

        def update_ui_callback(ref: str, status: str):
            self.csv_table_tab.update_row_color(ref, status)

        if self.on_process_callback:
            self.on_process_callback(mapping, data, doc_type, update_ui_callback)

    def _on_stop(self):
        if self.on_stop_callback:
            self.on_stop_callback()

    def run(self):
        self.root.mainloop()
        