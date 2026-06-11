import tkinter as tk
from tkinter import ttk
from typing import Callable
from data.mappings import MAPPINGS, save_user_mappings

# ── Define the exact columns to show in the preview table ────────────────────
# Maps the "Clean UI Header" -> "Actual CSV Column Name"
DISPLAY_COLUMNS = {
    "Client": "Client",
    "Operation": "Operation",
    "Ref": "Reference",
    "Date": "Date",
    "TTC": "TTC",
    "HT": "Tot. Net. HT",
    "Rate": "TVA %",
    "TVA": "Montant TVA"
}

class CsvTableTab(ttk.Frame):
    def __init__(self, parent, on_process: Callable[[dict, list[dict]], None]):
        super().__init__(parent)
        self.on_process = on_process
        self.current_doc_type = "Vente"
        self.csv_data: list[dict] = []
        self.headers: list[str] = []
        self.mapping_vars: dict[str, tk.StringVar] = {}

        self._build_ui()

    def load_data(self, doc_type: str, file_path: str, data: list[dict]):
        self.current_doc_type = doc_type
        self.csv_data = data
        if not data:
            return
        
        self.headers = list(data[0].keys())
        self._build_mapping_ui()
        self._build_table_ui()

    def _build_ui(self):
        info_frame = ttk.Frame(self)
        info_frame.pack(fill=tk.X, padx=20, pady=10)
        self.info_label = ttk.Label(info_frame, text="Please import a file in the previous tab.", font=("Arial", 10, "bold"))
        self.info_label.pack(side=tk.LEFT)

        self.mapping_frame = ttk.LabelFrame(self, text="Column Mapping Configuration")
        self.mapping_frame.pack(fill=tk.X, padx=20, pady=10)

        table_frame = ttk.Frame(self)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        v_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL)
        h_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL)
        
        self.tree = ttk.Treeview(table_frame, yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        v_scroll.config(command=self.tree.yview)
        h_scroll.config(command=self.tree.xview)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=20, pady=10)
        
        ttk.Button(btn_frame, text="💾 Save Mapping Config", command=self._save_mapping).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🚀 Process & Automate", command=self._process, style="Accent.TButton").pack(side=tk.RIGHT, padx=5)

               # 🆕 Stop Button
        self.stop_btn = ttk.Button(btn_frame, text="🛑 Stop Automation", command=self._stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.RIGHT, padx=5)
        
        self.process_btn = ttk.Button(btn_frame, text="🚀 Process & Automate", command=self._process, style="Accent.TButton")
        self.process_btn.pack(side=tk.RIGHT, padx=5)


    def _build_mapping_ui(self):
        for widget in self.mapping_frame.winfo_children():
            widget.destroy()

        self.mapping_vars = {}
        current_defaults = MAPPINGS.get(self.current_doc_type, {})
        target_fields = sorted(list(set(current_defaults.values())))
        options = ["-- Ignore --"] + target_fields

        for idx, header in enumerate(self.headers):
            ttk.Label(self.mapping_frame, text=header, font=("Arial", 9, "bold")).grid(row=0, column=idx, padx=5, pady=5)
            
            default_val = current_defaults.get(header, "-- Ignore --")
            var = tk.StringVar(value=default_val)
            self.mapping_vars[header] = var
            
            combo = ttk.Combobox(self.mapping_frame, textvariable=var, values=options, state="readonly", width=14)
            combo.grid(row=1, column=idx, padx=5, pady=5)

    def _build_table_ui(self):
        self.tree.delete(*self.tree.get_children())
        
        # Filter to only show the columns defined in DISPLAY_COLUMNS that actually exist in the CSV
        self.display_headers = [disp_name for disp_name, csv_col in DISPLAY_COLUMNS.items() if csv_col in self.headers]
        
        self.tree["columns"] = self.display_headers
        self.tree["show"] = "headings"

        for col in self.display_headers:
            self.tree.heading(col, text=col)
            # Make Client and Operation columns wider for better readability
            width = 180 if col in ["Client", "Operation"] else 100
            self.tree.column(col, width=width, anchor=tk.W)

        # 🆕 Show ALL rows (removed the 100-row limit)
        for row in self.csv_data:
            values = [row.get(DISPLAY_COLUMNS[col], "") for col in self.display_headers]
            self.tree.insert("", tk.END, values=values)

        self.info_label.config(text=f"Loaded: {self.current_doc_type} ({len(self.csv_data)} total rows)")

    def _save_mapping(self):
        active_mapping = {h: var.get() for h, var in self.mapping_vars.items() if var.get() != "-- Ignore --"}
        MAPPINGS[self.current_doc_type] = active_mapping
        save_user_mappings(MAPPINGS)
        self.info_label.config(text="✅ Mapping configuration saved!", foreground="green")

# 🆕 NEW: Method to update row colors live from the background thread
    def update_row_color(self, ref: str, status: str):
        def _update():
            color_map = {
                'processing': '#FFF59D', # Light Yellow
                'success': '#A5D6A7',    # Light Green
                'error': '#EF9A9A'       # Light Red
            }
            tag = f"status_{ref.replace('/', '_')}"
            self.tree.tag_configure(tag, background=color_map.get(status, '#FFFFFF'))
            
            for item in self.tree.get_children():
                values = self.tree.item(item, 'values')
                # Ref is the 3rd column (index 2)
                if len(values) > 2 and values[2] == ref:
                    self.tree.item(item, tags=(tag,))
                    self.tree.see(item) # Auto-scroll to the active row
                    break
        self.after(0, _update) # Thread-safe UI update

    def _process(self):
        active_mapping = {h: var.get() for h, var in self.mapping_vars.items() if var.get() != "-- Ignore --"}
        if not active_mapping:
            self.info_label.config(text="❌ No columns mapped!", foreground="red")
            return
        
        if self.on_process:
            # 🆕 Pass self.current_doc_type as the 3rd argument
            self.on_process(active_mapping, self.csv_data, self.current_doc_type)
            