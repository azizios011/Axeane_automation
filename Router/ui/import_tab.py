import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable
from data.formulas import FORMULAS, save_formulas

class ImportTab(ttk.Frame):
    def __init__(self, parent, on_data_loaded: Callable[[str, str, list[dict]], None]):
        super().__init__(parent)
        self.on_data_loaded = on_data_loaded
        self.doc_type = tk.StringVar(value="Vente")
        self.file_path = tk.StringVar(value="")
        self.csv_data: list[dict] = []
        self.formulas = FORMULAS.copy()
        self.formula_vars = []

        self._build_ui()

    def _build_ui(self):
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=20, pady=10)

        ttk.Label(top_frame, text="Document Type:").pack(side=tk.LEFT, padx=(0, 5))
        self.doc_combo = ttk.Combobox(top_frame, textvariable=self.doc_type, values=["Vente", "Achat", "Bank"], state="readonly", width=15)
        self.doc_combo.pack(side=tk.LEFT, padx=(0, 20))
        self.doc_combo.bind("<<ComboboxSelected>>", self._on_doc_type_change)

        import_btn = ttk.Button(top_frame, text="📂 Import CSV File", command=self._import_file)
        import_btn.pack(side=tk.LEFT)

        self.status_label = ttk.Label(self, text="No file selected", foreground="gray")
        self.status_label.pack(fill=tk.X, padx=20, pady=5)

        # ── Formula Manager (Vente Only) ──────────────────────────────────
        self.formula_frame = ttk.LabelFrame(self, text="⚙️ Formules de Vente (Règles de Comptes)")
        
        self.formula_list_frame = ttk.Frame(self.formula_frame)
        self.formula_list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._refresh_formula_list()
        
        btn_frame = ttk.Frame(self.formula_frame)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(btn_frame, text="➕ Add Formula", command=self._add_formula).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="💾 Save Formulas", command=self._save_formulas).pack(side=tk.RIGHT)

        self.next_btn = ttk.Button(self, text="Configure Columns & Continue >>", command=self._on_next, state=tk.DISABLED)
        self.next_btn.pack(side=tk.BOTTOM, pady=10)
        
        self._on_doc_type_change(None)

    def _on_doc_type_change(self, event):
        if self.doc_type.get() == "Vente":
            self.formula_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10, before=self.next_btn)
        else:
            self.formula_frame.pack_forget()

    def _refresh_formula_list(self):
        for widget in self.formula_list_frame.winfo_children():
            widget.destroy()
            
        self.formula_vars = []
        
        canvas = tk.Canvas(self.formula_list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.formula_list_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for idx, f in enumerate(self.formulas):
            self._build_formula_ui(scrollable_frame, idx, f)
            
        ttk.Frame(scrollable_frame, height=20).pack(fill=tk.X)

    def _build_formula_ui(self, parent, idx, f_data):
        frame = ttk.LabelFrame(parent, text=f"Formula {idx+1}")
        frame.pack(fill=tk.X, padx=5, pady=5)
        
        vars_dict = {}
        
        # Row 0: Client Match & Delete
        ttk.Label(frame, text="Client Match:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        vars_dict['client_match'] = tk.StringVar(value=f_data.get('client_match', ''))
        ttk.Entry(frame, textvariable=vars_dict['client_match'], width=25).grid(row=0, column=1, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        ttk.Button(frame, text="🗑️ Delete", command=lambda: self._delete_formula(idx)).grid(row=0, column=3, padx=5, pady=2)

        # Row 1: Base Accounts
        ttk.Label(frame, text="Compte Client:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        vars_dict['compte_client'] = tk.StringVar(value=f_data.get('compte_client', ''))
        ttk.Entry(frame, textvariable=vars_dict['compte_client'], width=15).grid(row=1, column=1, padx=5, pady=2)

        ttk.Label(frame, text="Compte HT 19%:").grid(row=1, column=2, sticky=tk.W, padx=5, pady=2)
        vars_dict['compte_ht_19'] = tk.StringVar(value=f_data.get('compte_ht_19', ''))
        ttk.Entry(frame, textvariable=vars_dict['compte_ht_19'], width=15).grid(row=1, column=3, padx=5, pady=2)

        # Row 2: TVA 19%
        ttk.Label(frame, text="Compte TVA 19%:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        vars_dict['compte_tva_19'] = tk.StringVar(value=f_data.get('compte_tva_19', ''))
        ttk.Entry(frame, textvariable=vars_dict['compte_tva_19'], width=15).grid(row=2, column=1, padx=5, pady=2)
        
        # Row 3: Timbre
        vars_dict['use_timbre'] = tk.BooleanVar(value=f_data.get('use_timbre', False))
        ttk.Checkbutton(frame, text="Include Timbre (1.000)", variable=vars_dict['use_timbre']).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        ttk.Label(frame, text="Compte Timbre:").grid(row=3, column=2, sticky=tk.W, padx=5, pady=2)
        vars_dict['compte_timbre'] = tk.StringVar(value=f_data.get('compte_timbre', ''))
        ttk.Entry(frame, textvariable=vars_dict['compte_timbre'], width=15).grid(row=3, column=3, padx=5, pady=2)

        # Row 4: 7% Rate
        vars_dict['use_7_percent'] = tk.BooleanVar(value=f_data.get('use_7_percent', False))
        ttk.Checkbutton(frame, text="Include 7% Rate", variable=vars_dict['use_7_percent']).grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)

        ttk.Label(frame, text="Compte HT 7%:").grid(row=4, column=2, sticky=tk.W, padx=5, pady=2)
        vars_dict['compte_ht_7'] = tk.StringVar(value=f_data.get('compte_ht_7', ''))
        ttk.Entry(frame, textvariable=vars_dict['compte_ht_7'], width=15).grid(row=4, column=3, padx=5, pady=2)

        # Row 5: TVA 7%
        ttk.Label(frame, text="Compte TVA 7%:").grid(row=5, column=2, sticky=tk.W, padx=5, pady=2)
        vars_dict['compte_tva_7'] = tk.StringVar(value=f_data.get('compte_tva_7', ''))
        ttk.Entry(frame, textvariable=vars_dict['compte_tva_7'], width=15).grid(row=5, column=3, padx=5, pady=2)

        # Row 6: Cash
        vars_dict['use_cash'] = tk.BooleanVar(value=f_data.get('use_cash', False))
        ttk.Checkbutton(frame, text="Include Cash Logic", variable=vars_dict['use_cash']).grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=5, pady=2)

        ttk.Label(frame, text="Compte Caisse:").grid(row=6, column=2, sticky=tk.W, padx=5, pady=2)
        vars_dict['compte_caisse'] = tk.StringVar(value=f_data.get('compte_caisse', ''))
        ttk.Entry(frame, textvariable=vars_dict['compte_caisse'], width=15).grid(row=6, column=3, padx=5, pady=2)

        self.formula_vars.append(vars_dict)

    def _sync_formulas_from_ui(self):
        updated = []
        for v in self.formula_vars:
            updated.append({
                "client_match": v['client_match'].get().strip(),
                "compte_client": v['compte_client'].get().strip(),
                "compte_tva_19": v['compte_tva_19'].get().strip(),
                "compte_ht_19": v['compte_ht_19'].get().strip(),
                "use_timbre": v['use_timbre'].get(),
                "compte_timbre": v['compte_timbre'].get().strip(),
                "use_7_percent": v['use_7_percent'].get(),
                "compte_tva_7": v['compte_tva_7'].get().strip(),
                "compte_ht_7": v['compte_ht_7'].get().strip(),
                "use_cash": v['use_cash'].get(),
                "compte_caisse": v['compte_caisse'].get().strip()
            })
        self.formulas = updated

    def _add_formula(self):
        self._sync_formulas_from_ui()
        self.formulas.append({
            "client_match": "", "compte_client": "", "compte_tva_19": "", "compte_ht_19": "",
            "use_timbre": False, "compte_timbre": "",
            "use_7_percent": False, "compte_tva_7": "", "compte_ht_7": "",
            "use_cash": False, "compte_caisse": ""
        })
        self._refresh_formula_list()

    def _delete_formula(self, idx):
        self._sync_formulas_from_ui()
        del self.formulas[idx]
        self._refresh_formula_list()

    def _save_formulas(self):
        self._sync_formulas_from_ui()
        save_formulas(self.formulas)
        messagebox.showinfo("Success", "Formulas saved successfully!")

    def _import_file(self):
        path = filedialog.askopenfilename(title="Choisir le fichier CSV", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path: return
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
            