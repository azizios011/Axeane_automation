import tkinter as tk
from tkinter import ttk, filedialog
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
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=20, pady=20)

        ttk.Label(top_frame, text="Document Type:").pack(side=tk.LEFT, padx=(0, 5))
        doc_combo = ttk.Combobox(top_frame, textvariable=self.doc_type, values=["Vente", "Achat", "Bank"], state="readonly", width=15)
        doc_combo.pack(side=tk.LEFT, padx=(0, 20))

        import_btn = ttk.Button(top_frame, text="📂 Import CSV File", command=self._import_file)
        import_btn.pack(side=tk.LEFT)

        self.status_label = ttk.Label(self, text="No file selected", foreground="gray")
        self.status_label.pack(fill=tk.X, padx=20, pady=10)

        self.next_btn = ttk.Button(self, text="Configure Columns & Continue >>", command=self._on_next, state=tk.DISABLED)
        self.next_btn.pack(side=tk.BOTTOM, pady=30)

    def _import_file(self):
        path = filedialog.askopenfilename(
            title="Choisir le fichier CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return

        self.file_path.set(path)
        try:
            import csv
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                self.csv_data = list(reader)
            
            self.status_label.config(text=f"✅ Loaded: {path} ({len(self.csv_data)} rows)", foreground="green")
            self.next_btn.config(state=tk.NORMAL)
        except Exception as e:
            self.status_label.config(text=f"❌ Error loading file: {e}", foreground="red")
            self.next_btn.config(state=tk.DISABLED)

    def _on_next(self):
        if self.on_data_loaded:
            self.on_data_loaded(self.doc_type.get(), self.file_path.get(), self.csv_data)
            