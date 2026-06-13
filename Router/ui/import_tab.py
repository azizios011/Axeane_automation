import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv
from typing import Callable

class ImportTab(ttk.Frame):
    def __init__(self, parent, on_data_loaded: Callable[[str, str, list[dict]], None]):
        super().__init__(parent)
        self.on_data_loaded = on_data_loaded
        self.doc_type = tk.StringVar(value="Vente")
        self.file_path = tk.StringVar(value="")
        self.csv_data: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        # Header Info
        header_label = ttk.Label(self, text="Select CSV and Document Type to begin", font=("Arial", 10, "italic"))
        header_label.pack(pady=(10, 0))

        container = ttk.Frame(self)
        container.pack(expand=True)

        # Config Box
        config_frame = ttk.LabelFrame(container, text=" File Configuration ", padding=20)
        config_frame.pack(padx=20, pady=20)

        ttk.Label(config_frame, text="Step 1: Select Type").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.doc_combo = ttk.Combobox(config_frame, textvariable=self.doc_type, values=["Vente", "Achat", "Bank"], state="readonly", width=30)
        self.doc_combo.grid(row=1, column=0, pady=(0, 15))

        ttk.Label(config_frame, text="Step 2: Load Data").grid(row=2, column=0, sticky=tk.W, pady=5)
        import_btn = ttk.Button(config_frame, text="📂 Browse CSV File", command=self._import_file, width=32)
        import_btn.grid(row=3, column=0, pady=(0, 15))

        self.status_label = ttk.Label(config_frame, text="No file selected", foreground="gray")
        self.status_label.grid(row=4, column=0)

        # Continue Button
        self.next_btn = ttk.Button(self, text="Configure Columns & Continue >>", command=self._on_next, state=tk.DISABLED, style="Accent.TButton")
        self.next_btn.pack(side=tk.BOTTOM, pady=30)

    def _import_file(self):
        path = filedialog.askopenfilename(title="Select CSV", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path: return
        self.file_path.set(path)
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                self.csv_data = list(reader)
            self.status_label.config(text=f"✅ {len(self.csv_data)} rows loaded", foreground="green")
            self.next_btn.config(state=tk.NORMAL)
        except Exception as e:
            self.status_label.config(text=f"❌ Error: {str(e)}", foreground="red")

    def _on_next(self):
        if self.on_data_loaded:
            self.on_data_loaded(self.doc_type.get(), self.file_path.get(), self.csv_data)
            