import os
import sys
import subprocess
import asyncio
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from data.config import SETTINGS, save_settings

def get_default_browser():
    if sys.platform == "win32":
        default_edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        default_chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        return default_edge if os.path.exists(default_edge) else default_chrome
    elif sys.platform == "darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return "chrome"

class PwaSettingsTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        
        default_port = "9222"
        try:
            default_port = SETTINGS.get("cdp_url", "").split(":")[-1] or "9222"
        except:
            pass

        self.cdp_port = tk.StringVar(value=default_port)
        self.user = tk.StringVar(value=SETTINGS.get("axeane_user", "RIHAB1"))
        self.password = tk.StringVar(value=SETTINGS.get("axeane_password", ""))
        
        # 🆕 Enterprise & Exercice Variables
        self.entreprise = tk.StringVar(value=SETTINGS.get("axeane_entreprise", "CPR"))
        self.exercice = tk.StringVar(value=SETTINGS.get("axeane_exercice", "EX 2026"))
        
        self.slow_mo = tk.StringVar(value=str(SETTINGS.get("slow_mo", 300)))
        self.browser_path = tk.StringVar(value=get_default_browser())
        
        self.is_verified = False

        self._build_ui()

    def _build_ui(self):
        # ── Connection & Credentials ──────────────────────────────────────────
        config_frame = ttk.LabelFrame(self, text="⚙️ Connection & Context Configuration")
        config_frame.pack(fill=tk.X, padx=20, pady=10)

        ttk.Label(config_frame, text="Browser Executable:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(config_frame, textvariable=self.browser_path, width=50).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(config_frame, text="Browse...", command=self._browse_browser).grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(config_frame, text="CDP Debug Port:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(config_frame, textvariable=self.cdp_port, width=10).grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Label(config_frame, text="Axeane Username:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(config_frame, textvariable=self.user, width=20).grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Label(config_frame, text="Axeane Password:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(config_frame, textvariable=self.password, width=20, show="*").grid(row=3, column=1, sticky=tk.W, padx=5, pady=5)

        # 🆕 NEW: Enterprise & Exercice Fields
        ttk.Separator(config_frame, orient=tk.HORIZONTAL).grid(row=4, column=0, columnspan=3, sticky=tk.EW, pady=10)
        ttk.Label(config_frame, text="🏢 Axeane Enterprise:", font=("Arial", 9, "bold")).grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(config_frame, textvariable=self.entreprise, width=20).grid(row=5, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Label(config_frame, text="📅 Axeane Exercice:", font=("Arial", 9, "bold")).grid(row=6, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(config_frame, textvariable=self.exercice, width=20).grid(row=6, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Separator(config_frame, orient=tk.HORIZONTAL).grid(row=7, column=0, columnspan=3, sticky=tk.EW, pady=10)
        
        ttk.Label(config_frame, text="Automation Delay (ms):").grid(row=8, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(config_frame, textvariable=self.slow_mo, width=10).grid(row=8, column=1, sticky=tk.W, padx=5, pady=5)

        ttk.Button(config_frame, text="💾 Save Settings", command=self._save_settings).grid(row=9, column=1, sticky=tk.E, padx=5, pady=10)

        # ── Actions & Status ──────────────────────────────────────────────────
        action_frame = ttk.Frame(self)
        action_frame.pack(fill=tk.X, padx=20, pady=10)

        self.launch_btn = ttk.Button(action_frame, text="🚀 Launch Browser with CDP", command=self._launch_browser)
        self.launch_btn.pack(side=tk.LEFT, padx=5)

        self.verify_btn = ttk.Button(action_frame, text="🛡️ Connect & Wait for Human Verification", command=self._start_verification, state=tk.DISABLED)
        self.verify_btn.pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar(value="🔴 Disconnected")
        self.status_label = ttk.Label(action_frame, textvariable=self.status_var, font=("Arial", 10, "bold"), foreground="red")
        self.status_label.pack(side=tk.LEFT, padx=20)

        # ── Debug Console ─────────────────────────────────────────────────────
        console_frame = ttk.LabelFrame(self, text="🖥️ Debug Console")
        console_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        self.console_text = tk.Text(console_frame, height=10, state=tk.DISABLED, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 9))
        self.console_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        scrollbar = ttk.Scrollbar(console_frame, orient=tk.VERTICAL, command=self.console_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.console_text.config(yscrollcommand=scrollbar.set)

        self._log("Ready. Configure settings and click 'Launch Browser'.")

    def _browse_browser(self):
        path = filedialog.askopenfilename(title="Select Browser Executable")
        if path:
            self.browser_path.set(path)

    def _save_settings(self):
        try:
            port = self.cdp_port.get()
            new_settings = {
                "cdp_url": f"http://localhost:{port}",
                "axeane_user": self.user.get(),
                "axeane_password": self.password.get(),
                "axeane_entreprise": self.entreprise.get(), # 🆕 Saved
                "axeane_exercice": self.exercice.get(),     # 🆕 Saved
                "slow_mo": int(self.slow_mo.get())
            }
            save_settings(new_settings)
            SETTINGS.update(new_settings) # Update in-memory immediately
            
            self._log("✅ Settings saved successfully to settings.json")
            messagebox.showinfo("Success", "Settings saved successfully!")
        except ValueError:
            messagebox.showerror("Error", "Automation Delay must be a valid number.")
        except Exception as e:
            self._log(f"❌ Failed to save settings: {e}")

    def _launch_browser(self):
        port = self.cdp_port.get()
        exe = self.browser_path.get()
        url = "https://kompta.axeane.com"

        if not os.path.exists(exe):
            self._log(f"❌ Browser not found at: {exe}")
            return

        user_data_dir = os.path.join(os.getcwd(), "cdp_user_data")
        os.makedirs(user_data_dir, exist_ok=True)

        cmd = [
            exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-notifications",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=TrackingPrevention,EdgeSidebar,msEdgeSettingsImport", # 🆕 Stop Sidebar and Imports
            "--force-device-scale-factor=1", # 🆕 Keeps UI scale consistent
            "--start-maximized",
            url
        ]
        try:
            subprocess.Popen(cmd)
            self.status_var.set("🟡 Browser Launched (Waiting for connection...)")
            self.status_label.config(foreground="orange")
            self.verify_btn.config(state=tk.NORMAL)
            self._log("✅ Browser process started. Please wait a few seconds, then click 'Connect & Wait for Human Verification'.")
        except Exception as e:
            self._log(f"❌ Failed to launch browser: {e}")

    def _start_verification(self):
        self.verify_btn.config(state=tk.DISABLED)
        self.status_var.set("🔄 Connecting to CDP...")
        self.status_label.config(foreground="blue")
        thread = threading.Thread(target=self._run_async_verification, daemon=True)
        thread.start()

    def _run_async_verification(self):
        port = self.cdp_port.get()
        cdp_url = f"http://localhost:{port}"

        async def check():
            try:
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    self._log_safe(f"🔗 Connecting to CDP at {cdp_url}...")
                    browser = await p.chromium.connect_over_cdp(cdp_url)
                    pages = [p for ctx in browser.contexts for p in ctx.pages]
                    page = next((p for p in pages if "axeane" in p.url.lower() or "kompta" in p.url.lower()), None)
                    
                    if not page:
                        self._log_safe("❌ No Axeane/Kompta page found.")
                        self._reset_ui_state()
                        return

                    self._log_safe(f"✅ Connected to: {page.url}")
                    self._log_safe("⏳ Waiting for human to solve Turnstile (Timeout: 120s)...")
                    
                    await page.wait_for_function(
                        "() => { const inp = document.querySelector('input[name=\"cf-turnstile-response\"]'); return inp && inp.value && inp.value.length > 10; }",
                        timeout=120_000
                    )
                    
                    self._log_safe("🛡️ SUCCESS: Turnstile verified! Token acquired.")
                    self.is_verified = True
                    self._update_status_safe("🟢 Verified & Ready", "green")
                    self._log_safe("🎉 You can now proceed to the 'Import Data' tab.")

            except Exception as e:
                self._log_safe(f"❌ Verification failed or timed out: {e}")
                self._reset_ui_state()

        asyncio.run(check())

    # ── Thread-Safe UI Helpers ────────────────────────────────────────────────
    def _log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console_text.config(state=tk.NORMAL)
        self.console_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.console_text.see(tk.END)
        self.console_text.config(state=tk.DISABLED)

    def _log_safe(self, msg: str): self.after(0, lambda: self._log(msg))
    def _update_status_safe(self, text: str, color: str): self.after(0, lambda: self._set_status(text, color))

    def _set_status(self, text: str, color: str):
        self.status_var.set(text)
        self.status_label.config(foreground=color)

    def _reset_ui_state(self):
        self.after(0, lambda: self.verify_btn.config(state=tk.NORMAL))
        self._update_status_safe("🔴 Disconnected / Failed", "red")
        