import csv
import os
import re
import hashlib
import requests
from datetime import datetime
from ftplib import FTP
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# =========================
# UI Colors
# =========================
COLOR_BG_MAIN = "#D5E0E2"
COLOR_PANEL_BG = "#BCD1D4"
COLOR_HEADER_TEAL = "#376E77"
COLOR_BTN_TEAL = "#2E5E66"
COLOR_CREAM = "#F7F3E3"
COLOR_TEXT_DARK = "#222222"

# =========================
# Validation Config
# =========================
EXPECTED_HEADERS = [
    "transaction_id","timestamp","store_id","product_id",
    "quantity","unit_price","total_amount","payment_method"
]
NUM_COLUMNS = 8
FILENAME_PATTERN = re.compile(r"^SALES_DATA_\d{14}\.csv$", re.IGNORECASE)

# =========================
# Chain of Responsibility
# =========================
class Handler:
    def __init__(self):
        self._next = None

    def set_next(self, handler):
        self._next = handler
        return handler

    def handle(self, filename, context):
        return self._next.handle(filename, context) if self._next else True


class ValidateHandler(Handler):
    def handle(self, filename, context):
        context.log_event(f"Validating: {filename}")
        
        if not filename or filename in {"No files found", "No matching files found"}:
            context.log_event("Validation failed: Select a real file.")
            return False

        if not FILENAME_PATTERN.match(filename):
            context.log_event(f"Validation failed: Incorrect filename format '{filename}'.")
            self._log_error_file(context, filename, ["Incorrectly formatted filename"])
            return False

        # Download directory is NOT required anymore for validation pass
        # Just check CSV structure if file exists on FTP
        try:
            local_temp = Path("temp_validation.csv")
            context.log_event(f"Downloading '{filename}' for validation...")
            with open(local_temp, "wb") as local_f:
                context.ftp.retrbinary(f"RETR {filename}", local_f.write)
        except Exception as err:
            context.log_event(f"Validation failed: FTP download error - {err}")
            self._log_error_file(context, filename, [f"FTP download failure: {err}"])
            return False

        errors = self._validate_csv_file(local_temp)
        local_temp.unlink(missing_ok=True)

        if errors:
            context.log_event(f"Validation failed for '{filename}' ({len(errors)} error(s) found):")
            for err in errors:
                context.log_event(f"  └── {err}")
            self._log_error_file(context, filename, errors)
            return False

        context.log_event(f"Validation passed for: {filename}")
        return super().handle(filename, context)


    def _log_error_file(self, context, filename: str, error_messages: list[str], source_url: str):
        error_dir = context.dir_errors.get().strip()
        if error_dir:
            os.makedirs(error_dir, exist_ok=True)
            error_file_path = Path(error_dir) / "error.txt"
        else:
            error_file_path = Path("error.txt")

        # Call external API to get a GUID
        try:
            response = requests.get("https://www.uuidtools.com/api/generate/v1")
            response.raise_for_status()
            entry_id = response.json()[0]  # API returns a list of UUIDs
        except Exception as e:
            # Fallback to SHA256 if API fails
            entry_id = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:12]
            context.log_event(f"GUID API failed, fallback used: {e}")

        with open(error_file_path, "a", encoding="utf-8") as f:
            f.write(f"\n[Error ID: {entry_id}] {filename}\n")
            f.write(f"Source URL: {source_url}\n")
            for msg in error_messages:
                f.write(f" - {msg}\n")

        context.log_event(f"Logged errors with GUID to '{error_file_path}'")


    def _validate_csv_file(self, file_path: Path) -> list[str]:
        errors = []
        if file_path.stat().st_size == 0:
            return ["Empty (0-byte) file"]

        try:
            with file_path.open(mode="r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                try:
                    headers = next(reader)
                except StopIteration:
                    return ["Missing header row"]

                headers = [h.strip() for h in headers]
                if len(headers) != NUM_COLUMNS:
                    errors.append(f"Header column count mismatch: expected {NUM_COLUMNS}, got {len(headers)}")
                elif headers != EXPECTED_HEADERS:
                    errors.append("Missing or incorrect headers")

                seen_tx_ids = set()
                for line_num, row in enumerate(reader, start=2):
                    if len(row) != NUM_COLUMNS:
                        errors.append(f"Row {line_num}: Inconsistent column count (got {len(row)})")
                        continue

                    row_dict = dict(zip(headers, row))
                    tx_id = row_dict.get("transaction_id", "").strip()
                    if not tx_id:
                        errors.append(f"Row {line_num}: Missing transaction_id")
                    elif tx_id in seen_tx_ids:
                        errors.append(f"Row {line_num}: Duplicate transaction_id '{tx_id}'")
                    else:
                        seen_tx_ids.add(tx_id)

                    try:
                        qty = int(row_dict.get("quantity", "").strip())
                        if qty <= 0:
                            errors.append(f"Row {line_num}: Quantity must be > 0 (got {qty})")
                    except ValueError:
                        errors.append(f"Row {line_num}: Invalid quantity integer")

                    try:
                        total = float(row_dict.get("total_amount", "").strip())
                        if total <= 0:
                            errors.append(f"Row {line_num}: Total amount must be > 0 (got {total})")
                    except ValueError:
                        errors.append(f"Row {line_num}: Invalid total_amount float")

        except csv.Error as csv_err:
            errors.append(f"Malformed CSV causing import failure: {csv_err}")
        except Exception as ex:
            errors.append(f"File reading error: {ex}")

        return errors


class ProcessHandler(Handler):
    def handle(self, filename, context):
        if filename.lower().endswith((".txt", ".csv")):
            context.log_event(f"Processing eligible file: {filename}")
            return super().handle(filename, context)
        context.log_event(f"Skipped unsupported file type: {filename}")
        return False


class ArchiveHandler(Handler):
    def handle(self, filename, context):
        archive_dir = context.dir_archive.get().strip()
        if archive_dir:
            os.makedirs(archive_dir, exist_ok=True)
            target = os.path.join(archive_dir, os.path.basename(filename))
            context.log_event(f"Archive target: {target}")
        else:
            context.log_event("No archive directory selected; archive step skipped.")
        return True

# =========================
# Tkinter GUI
# =========================
class FTPClientGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Nexus Dynamic")
        self.root.geometry("1100x650")
        self.root.configure(bg=COLOR_BG_MAIN)

        self.ftp = None
        self.all_files = []

        style = ttk.Style()
        style.theme_use("clam")

        self.setup_ui()
        self.log_event("Activity Feed initialized.")

    def setup_ui(self):
        # Title
        title = tk.Frame(self.root, bg=COLOR_BG_MAIN, padx=15, pady=10)
        title.pack(fill="x")
        tk.Label(title, text="Nexus Dynamic", font=("Arial", 16, "bold"),
                 fg=COLOR_HEADER_TEAL, bg=COLOR_BG_MAIN).pack(side="left")
        self.status_label = tk.Label(title, text="● Disconnected", font=("Arial", 11),
                                     fg="#B22222", bg=COLOR_BG_MAIN)
        self.status_label.pack(side="right", padx=10)

        # Middle split
        middle = tk.Frame(self.root, bg=COLOR_BG_MAIN, padx=10)
        middle.pack(fill="both", expand=True)

        left = tk.LabelFrame(middle, text="Connection & Browser", font=("Arial", 11, "bold"),
                             bg=COLOR_PANEL_BG, fg=COLOR_TEXT_DARK, labelanchor="nw", bd=0)
        left.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        right = tk.LabelFrame(middle, text="Workspace & Actions", font=("Arial", 11, "bold"),
                              bg=COLOR_PANEL_BG, fg=COLOR_TEXT_DARK, labelanchor="nw", bd=0)
        right.pack(side="right", fill="both", expand=True, padx=5, pady=5)

        # Connection panel
        conn = tk.Frame(left, bg=COLOR_PANEL_BG, padx=10, pady=10)
        conn.place(relx=0, rely=0, relwidth=0.45, relheight=1)
        tk.Label(conn, text="1. Host Connection", font=("Arial", 11, "bold"),
                 bg=COLOR_PANEL_BG).pack(anchor="w", pady=(0, 10))
        self.host_entry = self._labeled_entry(conn, "Host", "127.0.0.1")
        self.user_entry = self._labeled_entry(conn, "Username")
        self.pass_entry = self._labeled_entry(conn, "Password", show="*")

        for entry in (self.host_entry, self.user_entry, self.pass_entry):
            entry.bind("<Return>", lambda event: self.connect())

        buttons = tk.Frame(conn, bg=COLOR_PANEL_BG)
        buttons.pack(fill="x", pady=(10, 0))
        tk.Button(buttons, text="Connect", command=self.connect, **self._button_style()).pack(side="left", padx=(0, 5))
        tk.Button(buttons, text="Disconnect", command=self.disconnect, bg="#7A9A9E", fg="white", relief="flat").pack(side="left")

        # Browser panel
        browser = tk.Frame(left, bg=COLOR_PANEL_BG, padx=10, pady=10)
        browser.place(relx=0.45, rely=0, relwidth=0.55, relheight=1)
        tk.Label(browser, text="2. Server Browser", font=("Arial", 11, "bold"), bg=COLOR_PANEL_BG).pack(anchor="w", pady=(0, 5))

        search = tk.Frame(browser, bg=COLOR_PANEL_BG)
        search.pack(fill="x", pady=(0, 5))
        tk.Label(search, text="Filter:", bg=COLOR_PANEL_BG).pack(side="left", padx=(0, 5))
        self.search_entry = tk.Entry(search, bg=COLOR_CREAM)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.search_entry.bind("<Return>", lambda event: self.filter_files())
        tk.Button(search, text="Apply", command=self.filter_files, **self._button_style()).pack(side="left", padx=2)
        tk.Button(search, text="Reset", command=self.clear_search, **self._button_style()).pack(side="left")

        self.file_list = tk.Listbox(browser, bg=COLOR_CREAM, fg=COLOR_TEXT_DARK, highlightthickness=0)
        self.file_list.pack(fill="both", expand=True)

        # Workspace panel
        workspace = tk.Frame(right, bg=COLOR_PANEL_BG, padx=15, pady=10)
        workspace.pack(fill="both", expand=True)
        self.dir_download = self._path_row(workspace, "Download directory")
        self.dir_archive = self._path_row(workspace, "Archive directory")
        self.dir_errors = self._path_row(workspace, "Errors directory")

        actions = tk.Frame(workspace, bg=COLOR_PANEL_BG, pady=15)
        actions.pack(fill="x", side="bottom")
        for column in range(2):
            actions.grid_columnconfigure(column, weight=1)

        action_buttons = [
            (0, 0, "Validate Selected File", self.validate_file),
            (0, 1, "Process Selected File", self.process_file),
            (1, 0, "Open Error Log", self.open_error_log),
            (1, 1, "Clear Activity Feed", self.clear_log_history),
        ]
        for row, column, text, command in action_buttons:
            tk.Button(actions, text=text, command=command, font=("Arial", 10), height=2,
                      **self._button_style()).grid(row=row, column=column, sticky="ew", padx=5, pady=5)

        # Activity Feed
        bottom = tk.LabelFrame(self.root, text="Activity Feed", font=("Arial", 11, "bold"),
                               bg=COLOR_PANEL_BG, fg=COLOR_TEXT_DARK, labelanchor="nw", bd=0)
        bottom.pack(fill="x", side="bottom", padx=15, pady=(5, 15))
        self.log_list = tk.Listbox(bottom, bg=COLOR_CREAM, fg=COLOR_TEXT_DARK, height=6, bd=0, font=("Courier New", 10))
        self.log_list.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar = ttk.Scrollbar(bottom, orient="vertical", command=self.log_list.yview)
        scrollbar.pack(side="right", fill="y", pady=5)
        self.log_list.config(yscrollcommand=scrollbar.set)

    def _button_style(self):
        return {"bg": COLOR_BTN_TEAL, "fg": "white", "activebackground": COLOR_HEADER_TEAL, "relief": "flat"}

    def _labeled_entry(self, parent, label, default="", show=None):
        tk.Label(parent, text=label, bg=COLOR_PANEL_BG).pack(anchor="w")
        entry = tk.Entry(parent, bg=COLOR_CREAM, show=show)
        entry.pack(fill="x", pady=(0, 10), ipady=3)
        entry.insert(0, default)
        return entry

    def _path_row(self, parent, label):
        tk.Label(parent, text=label, bg=COLOR_PANEL_BG).pack(anchor="w", pady=(5, 0))
        row = tk.Frame(parent, bg=COLOR_PANEL_BG)
        row.pack(fill="x", pady=(2, 8))
        entry = tk.Entry(row, bg=COLOR_CREAM)
        entry.pack(side="left", fill="x", expand=True, ipady=3, padx=(0, 5))
        tk.Button(row, text="Browse...", command=lambda: self.browse_directory(entry), **self._button_style()).pack(side="right")
        return entry

    def browse_directory(self, entry):
        selected = filedialog.askdirectory()
        if selected:
            entry.delete(0, tk.END)
            entry.insert(0, os.path.normpath(selected))
            self.log_event(f"Selected directory: {selected}")

    def log_event(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_list.insert(tk.END, f"[{timestamp}] {message}")
        self.log_list.see(tk.END)

    def clear_log_history(self):
        self.log_list.delete(0, tk.END)
        self.log_event("Activity Feed cleared.")

    def connect(self):
        host = self.host_entry.get().strip()
        username = self.user_entry.get().strip()
        password = self.pass_entry.get()
        if not host:
            messagebox.showwarning("Warning", "Please enter a host address.")
            return
        self.disconnect(log=False)
        self.log_event(f"Attempting connection to {host}...")
        try:
            self.ftp = FTP(host, timeout=10)
            self.ftp.login(username, password)
            self.status_label.config(text="● Connected", fg="#2E8B57")
            self.all_files = self.ftp.nlst()
            self.clear_search()
            self.log_event(f"Connected. Loaded {len(self.all_files)} item(s).")
            messagebox.showinfo("Success", "FTP connected successfully.")
        except Exception as error:
            self.ftp = None
            self.status_label.config(text="● Disconnected", fg="#B22222")
            self.log_event(f"Connection error: {error}")
            messagebox.showerror("FTP Error", str(error))

    def disconnect(self, log=True):
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                pass
        self.ftp = None
        self.all_files = []
        self.status_label.config(text="● Disconnected", fg="#B22222")
        self.file_list.delete(0, tk.END)
        if log:
            self.log_event("Disconnected.")

    def filter_files(self):
        if not self.ftp:
            self.log_event("Search ignored: not connected.")
            return
        term = self.search_entry.get().strip().lower()
        filtered = [name for name in self.all_files if term in name.lower()]
        self._show_files(filtered)

    def clear_search(self):
        self.search_entry.delete(0, tk.END)
        self._show_files(self.all_files)

    def _show_files(self, files):
        self.file_list.delete(0, tk.END)
        if files:
            for name in files:
                self.file_list.insert(tk.END, name)
        else:
            if self.ftp:
                self.file_list.insert(tk.END, "No files found")
            else:
                self.file_list.insert(tk.END, "No matching files found")

    def _selected_filename(self):
        selection = self.file_list.curselection()
        if not selection:
            messagebox.showwarning("Selection", "Please select a file first.")
            return None
        return self.file_list.get(selection[0])

    def validate_file(self):
        filename = self._selected_filename()
        if filename is None:
            return
        if ValidateHandler().handle(filename, self):
            messagebox.showinfo("Validation", "Validation passed")
        else:
            messagebox.showwarning("Validation", f"Validation failed for: {filename}")

    def process_file(self):
        filename = self._selected_filename()
        if filename is None:
            return

        # Use existing Archive directory if already set, otherwise ask
        archive_dir = self.dir_archive.get().strip()
        if not archive_dir:
            archive_dir = filedialog.askdirectory(title="Select Archive Directory")
            if not archive_dir:
                messagebox.showwarning("Process", "Archive directory required.")
                return
            self.dir_archive.delete(0, tk.END)
            self.dir_archive.insert(0, os.path.normpath(archive_dir))

        # Use existing Error directory if already set, otherwise ask
        error_dir = self.dir_errors.get().strip()
        if not error_dir:
            error_dir = filedialog.askdirectory(title="Select Error Directory")
            if not error_dir:
                messagebox.showwarning("Process", "Error directory required.")
                return
            self.dir_errors.delete(0, tk.END)
            self.dir_errors.insert(0, os.path.normpath(error_dir))

        validator = ValidateHandler()
        validator.set_next(ProcessHandler())

        try:
            if validator.handle(filename, self):
                # Validation passed → copy to Archive
                local_archive = Path(archive_dir) / filename
                with open(local_archive, "wb") as f:
                    self.ftp.retrbinary(f"RETR {filename}", f.write)
                self.log_event(f"Copied file to Archive: {local_archive}")
                messagebox.showinfo("Process", f"Validation passed. File archived:\n{filename}")
            else:
                # Validation failed → copy to Error
                local_error = Path(error_dir) / filename
                with open(local_error, "wb") as f:
                    self.ftp.retrbinary(f"RETR {filename}", f.write)
                self.log_event(f"Copied file to Error: {local_error}")
                messagebox.showwarning("Process", f"Validation failed. File moved to Error:\n{filename}")
        except Exception as err:
            self.log_event(f"Processing failed: {err}")
            messagebox.showerror("Process Error", str(err))


    def open_error_log(self):
        log_path = Path("error.txt")  # always in the same folder
        if not log_path.exists():
            log_path.open("a", encoding="utf-8").close()
        os.startfile(log_path)
        self.log_event(f"Opened error log: {log_path}")


# =========================
# Main Entry Point
# =========================
if __name__ == "__main__":
    root = tk.Tk()
    FTPClientGUI(root)
    root.mainloop()

           