import sys
import tkinter as tk
from tkinter import filedialog
from functions.helpers import log

def pick_csv() -> str:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title="Choisir le fichier Journal Vente CSV",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        parent=root,
    )
    root.destroy()
    if not path:
        print("Aucun fichier sélectionné. Abandon.")
        sys.exit(0)
    return path
    