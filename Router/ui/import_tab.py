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
            
        canvas = tk.Canvas(self.formula_list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.formula_list_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for idx, f in enumerate(self.formulas):
            row_frame = ttk.Frame(scrollable_frame, relief=tk.GROOVE, borderwidth=1)
            row_frame.pack(fill=tk.X, padx=5, pady=2)
            
            info = f"Client: '{f['client_match']}' | Client: {f['compte_client']} | TVA19: {f['compte_tva_19']} | HT19: {f['compte_ht_19']}"
            if f['use_timbre']: info += f" | Timbre: {f['compte_timbre']}"
            if f['use_7_percent']: info += f" | 7%: TVA({f['compte_tva_7']}) HT({f['compte_ht_7']})"
            if f['use_cash']: info += f" | Cash: {f['compte_caisse']}"
            
            ttk.Label(row_frame, text=info, font=("Arial", 9), justify=tk.LEFT).pack(side=tk.LEFT, padx=5, pady=5, fill=tk.X, expand=True)
            ttk.Button(row_frame, text="🗑️", width=3, command=lambda i=idx: self._delete_formula(i)).pack(side=tk.RIGHT, padx=5, pady=5)

    def _add_formula(self):
        dialog = tk.Toplevel(self)
        dialog.title("Add Accounting Formula")
        dialog.geometry("420x520")
        dialog.transient(self)
        dialog.grab_set()

        vars_dict = {}
        row = 0
        def add_field(label, default=""):
            nonlocal row
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky=tk.W, padx=10, pady=5)
            v = tk.StringVar(value=default)
            vars_dict[label] = v
            ttk.Entry(dialog, textvariable=v, width=30).grid(row=row, column=1, padx=10, pady=5)
            row += 1
            return v

        vars_dict['client_match'] = add_field("Client Name (Match):", "PASSAGER")
        vars_dict['compte_client'] = add_field("Compte Client:", "411000")
        vars_dict['compte_tva_19'] = add_field("Compte TVA 19%:", "436710")
        vars_dict['compte_ht_19'] = add_field("Compte HT 19%:", "707019")
        
        row += 1
        use_timbre = tk.BooleanVar(value=True)
        ttk.Checkbutton(dialog, text="Include Timbre (1.000 TND)", variable=use_timbre).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
        row += 1
        vars_dict['compte_timbre'] = add_field("Compte Timbre:", "736000")
        
        row += 1
        use_7 = tk.BooleanVar(value=False)
        ttk.Checkbutton(dialog, text="Include 7% Rate Rows", variable=use_7).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
        row += 1
        vars_dict['compte_tva_7'] = add_field("Compte TVA 7%:", "436707")
        vars_dict['compte_ht_7'] = add_field("Compte HT 7%:", "707007")
        
        row += 1
        use_cash = tk.BooleanVar(value=False)
        ttk.Checkbutton(dialog, text="Include Cash (Espèces) Logic", variable=use_cash).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
        row += 1
        vars_dict['compte_caisse'] = add_field("Compte Caisse:", "541100")

        def save():
            new_f = {
                "client_match": vars_dict['client_match'].get().strip(),
                "compte_client": vars_dict['compte_client'].get().strip(),
                "compte_tva_19": vars_dict['compte_tva_19'].get().strip(),
                "compte_ht_19": vars_dict['compte_ht_19'].get().strip(),
                "use_timbre": use_timbre.get(),
                "compte_timbre": vars_dict['compte_timbre'].get().strip(),
                "use_7_percent": use_7.get(),
                "compte_tva_7": vars_dict['compte_tva_7'].get().strip(),
                "compte_ht_7": vars_dict['compte_ht_7'].get().strip(),
                "use_cash": use_cash.get(),
                "compte_caisse": vars_dict['compte_caisse'].get().strip()
            }
            self.formulas.append(new_f)
            self._refresh_formula_list()
            dialog.destroy()

        ttk.Button(dialog, text="Save Formula", command=save).pack(pady=20)

    def _delete_formula(self, idx):
        del self.formulas[idx]
        self._refresh_formula_list()

    def _save_formulas(self):
        save_formulas(self.formulas)
        messagebox.showinfo("Success", "Formulas saved successfully!")

    def _import_file(self):
        path = filedialog.askopenfilename(title="Choisir le fichier CSV", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
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
            