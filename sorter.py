import os
import shutil
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import json
import threading
import re
from tkinterdnd2 import TkinterDnD, DND_FILES

# --- Tooltip Helper Class ---
class Tooltip:
    def __init__(self, widget, text, delay=500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.tipwindow = None
        self.id = None
        self.x = self.y = 0
        self.widget.bind('<Enter>', self.enter)
        self.widget.bind('<Leave>', self.leave)
        self.widget.bind('<ButtonPress>', self.leave)

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(self.delay, self.showtip)

    def unschedule(self):
        id_ = self.id
        self.id = None
        if id_:
            self.widget.after_cancel(id_)

    def showtip(self, event=None):
        if self.tipwindow or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert") if self.widget.winfo_class() == 'Entry' else (0, 0, 0, 0)
        x = x + self.widget.winfo_rootx() + 25
        y = y + cy + self.widget.winfo_rooty() + 20
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack(ipadx=4)

    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            tw.destroy()

# Constants
SORT_RECORD = 'last_sort.json'
SETTINGS_FILE = 'settings.json'
WINDOW_WIDTH = 420
WINDOW_HEIGHT = 320
ENTRY_WIDTH = 38
MAX_PREVIEW_FILES = 5
MAX_FOLDER_NAME_LENGTH = 50

# UI Constants
PADDING_LARGE = 20
PADDING_MEDIUM = 12
PADDING_SMALL = 8
FONT_HEADER = ("Segoe UI", 18, "bold")
FONT_LABEL = ("Segoe UI", 12, "bold")
FONT_NORMAL = ("Segoe UI", 9)
FONT_ITALIC = ("Segoe UI", 9, "italic")

class FileSorterApp:
    def __init__(self):
        self.settings = self.load_settings()
        self.folder_var = None
        self.folder_path_label_var = None
        self.status_var = None
        self.unsort_btn = None
        self.progress = None
        self.root = None
        self.main_frame = None
        
        # Check for drag-and-drop availability
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES
            self.dnd_available = True
        except ImportError:
            self.dnd_available = False
        
        self.setup_gui()
    
    def load_settings(self):
        """Load settings from file with error handling."""
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    # Validate settings structure
                    if not isinstance(settings, dict):
                        return {"custom_folders": {}, "theme": "light"}
                    if "custom_folders" not in settings:
                        settings["custom_folders"] = {}
                    return settings
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load settings: {e}")
        return {"custom_folders": {}, "theme": "light"}
    
    def save_settings(self):
        """Save settings to file with error handling."""
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
        except IOError as e:
            messagebox.showerror("Error", f"Could not save settings: {e}")
    
    def validate_folder_name(self, name):
        """Validate custom folder name."""
        if not name or not name.strip():
            return False, "Folder name cannot be empty"
        
        name = name.strip()
        if len(name) > MAX_FOLDER_NAME_LENGTH:
            return False, f"Folder name too long (max {MAX_FOLDER_NAME_LENGTH} characters)"
        
        # Check for invalid characters
        invalid_chars = r'[<>:"/\\|?*]'
        if re.search(invalid_chars, name):
            return False, "Folder name contains invalid characters"
        
        return True, ""
    
    def validate_extension(self, ext):
        """Validate file extension."""
        if not ext or not ext.strip():
            return False, "Extension cannot be empty"
        
        ext = ext.strip().lower()
        if ext.startswith('.'):
            ext = ext[1:]
        
        # Check for valid extension format
        if not re.match(r'^[a-zA-Z0-9]+$', ext):
            return False, "Extension can only contain letters and numbers"
        
        return True, ext
    
    def validate_path(self, path):
        """Validate and sanitize file path."""
        try:
            path = os.path.normpath(path)
            if not os.path.exists(path):
                return False, "Path does not exist"
            if not os.path.isdir(path):
                return False, "Path is not a directory"
            return True, path
        except Exception as e:
            return False, f"Invalid path: {e}"
    
    # --- File Sorting Logic ---
    def create_folder(self, parent_folder, name):
        """Create folder with error handling."""
        try:
            folder_path = parent_folder / name
            folder_path.mkdir(exist_ok=True)
            return folder_path
        except Exception as e:
            raise Exception(f"Could not create folder '{name}': {e}")
    
    def sort_files_bulk(self, folder_path):
        """Sort files in bulk with improved error handling."""
        try:
            folder = Path(folder_path)
            if not folder.exists():
                messagebox.showerror("Error", "Folder does not exist.")
                return
            
            moved = 0
            failed = []
            sort_record = {}
            
            # Get all files first to show progress
            files = [f for f in folder.iterdir() if f.is_file()]
            total_files = len(files)
            
            if total_files == 0:
                messagebox.showinfo("Info", "No files to sort in this folder.")
                return
            
            for i, file in enumerate(files):
                # Update status
                self.set_status(f"Processing {i+1}/{total_files}: {file.name}")
                
                ext = file.suffix[1:] if file.suffix else "NoExtension"
                # Use custom folder name if available (case-insensitive)
                folder_name = self.settings.get("custom_folders", {}).get(ext.lower(), ext.upper())
                
                try:
                    dest_folder = self.create_folder(folder, folder_name)
                    dest_path = dest_folder / file.name
                    
                    # Handle file name conflicts
                    counter = 1
                    original_dest = dest_path
                    while dest_path.exists():
                        stem = original_dest.stem
                        suffix = original_dest.suffix
                        dest_path = dest_folder / f"{stem}_{counter}{suffix}"
                        counter += 1
                    
                    shutil.move(str(file), dest_path)
                    sort_record[str(dest_path)] = str(file)
                    moved += 1
                    
                except Exception as e:
                    failed.append(f"{file.name}: {e}")
            
            # Save sort record
            if sort_record:
                try:
                    with open(folder / SORT_RECORD, 'w', encoding='utf-8') as f:
                        json.dump(sort_record, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    messagebox.showwarning("Warning", f"Could not save sort record: {e}")
            
            # Show results
            msg = f"Successfully moved {moved} files."
            if failed:
                msg += f"\nFailed to move {len(failed)} files:\n" + "\n".join(failed[:10])
                if len(failed) > 10:
                    msg += f"\n... and {len(failed) - 10} more errors"
            
            messagebox.showinfo("Sort Complete", msg)
            self.update_unsort_button()
            
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred during sorting: {e}")
        finally:
            self.set_status("Ready")
    
    def unsort_files(self, folder_path):
        """Unsort files with improved error handling."""
        try:
            folder = Path(folder_path)
            record_path = folder / SORT_RECORD
            
            if not record_path.exists():
                messagebox.showinfo("Unsort", "No sort record found to undo.")
                return
            
            try:
                with open(record_path, 'r', encoding='utf-8') as f:
                    sort_record = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                messagebox.showerror("Error", f"Could not read sort record: {e}")
                return
            
            moved = 0
            failed = []
            extension_folders = set()
            total_files = len(sort_record)
            
            for i, (dest, orig) in enumerate(sort_record.items()):
                self.set_status(f"Restoring {i+1}/{total_files}")
                
                dest_path = Path(dest)
                orig_path = Path(orig)
                
                # Track extension folders for cleanup
                if dest_path.parent != folder:
                    extension_folders.add(dest_path.parent)
                
                try:
                    if dest_path.exists():
                        # Handle conflicts in original location
                        counter = 1
                        final_orig_path = orig_path
                        while final_orig_path.exists():
                            stem = orig_path.stem
                            suffix = orig_path.suffix
                            final_orig_path = orig_path.parent / f"{stem}_restored_{counter}{suffix}"
                            counter += 1
                        
                        shutil.move(str(dest_path), final_orig_path)
                        moved += 1
                except Exception as e:
                    failed.append(f"{dest_path.name}: {e}")
            
            # Remove sort record
            try:
                os.remove(record_path)
            except Exception as e:
                print(f"Warning: Could not remove sort record: {e}")
            
            # Remove empty extension folders
            for ext_folder in extension_folders:
                try:
                    if ext_folder.exists() and not any(ext_folder.iterdir()):
                        ext_folder.rmdir()
                except Exception as e:
                    print(f"Warning: Could not remove folder {ext_folder}: {e}")
            
            msg = f"Successfully restored {moved} files."
            if failed:
                msg += f"\nFailed to restore {len(failed)} files:\n" + "\n".join(failed[:10])
                if len(failed) > 10:
                    msg += f"\n... and {len(failed) - 10} more errors"
            
            messagebox.showinfo("Unsort Complete", msg)
            self.update_unsort_button()
            
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred during unsort: {e}")
        finally:
            self.set_status("Ready")
    
    def get_sort_preview(self, folder_path):
        """Get preview of files to be sorted."""
        try:
            folder = Path(folder_path)
            if not folder.exists():
                return None
            
            preview = {}
            for file in folder.iterdir():
                if file.is_file():
                    ext = file.suffix[1:] if file.suffix else "NoExtension"
                    preview.setdefault(ext.upper(), []).append(file.name)
            
            return preview
        except Exception as e:
            print(f"Error getting preview: {e}")
            return None
    
    def show_preview_dialog(self, folder):
        """Show preview dialog with improved layout."""
        preview = self.get_sort_preview(folder)
        if preview is None or not preview:
            messagebox.showinfo("Preview", "No files to sort in this folder.")
            return False
        
        # Build preview text
        lines = []
        total = 0
        for ext, files in preview.items():
            # Use custom folder name if available (case-insensitive)
            folder_name = self.settings.get("custom_folders", {}).get(ext.lower(), ext.upper())
            lines.append(f"{folder_name}: {len(files)} file(s)")
            for f in files[:MAX_PREVIEW_FILES]:
                lines.append(f"    - {f}")
            if len(files) > MAX_PREVIEW_FILES:
                lines.append(f"    ...and {len(files) - MAX_PREVIEW_FILES} more")
            total += len(files)
        
        lines.insert(0, f"Total files to be sorted: {total}\n")
        preview_text = "\n".join(lines)
        
        # Show dialog
        preview_win = tk.Toplevel(self.root)
        preview_win.title("Preview Sort")
        preview_win.geometry("500x400")
        preview_win.transient(self.root)
        preview_win.grab_set()
        
        # Center the window
        if self.root is not None:
            preview_win.geometry("+%d+%d" % (
                self.root.winfo_rootx() + 50,
                self.root.winfo_rooty() + 50
            ))
        else:
            print("[Warning] show_preview_dialog: root is None, cannot center window.")
        
        ttk.Label(preview_win, text="Preview of files to be sorted:", 
                 font=FONT_LABEL).pack(padx=16, pady=(16, 4), anchor="w")
        
        # Text widget with scrollbar
        text_frame = ttk.Frame(preview_win)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=4)
        
        text = tk.Text(text_frame, width=60, height=18, wrap="none")
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        text.insert("1.0", preview_text)
        text.config(state="disabled")
        
        btn_frame = ttk.Frame(preview_win)
        btn_frame.pack(pady=(0, 16))
        
        proceed = {'value': False}
        
        def on_proceed():
            proceed['value'] = True
            preview_win.destroy()
        
        def on_cancel():
            preview_win.destroy()
        
        ttk.Button(btn_frame, text="Proceed", command=on_proceed).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="left", padx=8)
        
        preview_win.wait_window()
        return proceed['value']
    
    # --- Settings Panel ---
    def open_settings_panel(self):
        """Open settings panel with improved validation."""
        panel = tk.Toplevel(self.root)
        panel.title("Settings")
        panel.geometry("450x400")
        panel.transient(self.root)
        panel.grab_set()
        
        # Center the window
        if self.root is not None:
            panel.geometry("+%d+%d" % (
                self.root.winfo_rootx() + 50,
                self.root.winfo_rooty() + 50
            ))
        else:
            print("[Warning] open_settings_panel: root is None, cannot center window.")
        
        ttk.Label(panel, text="Custom Folder Names for Extensions", 
                 font=FONT_LABEL).pack(pady=(16, 8))
        
        # Main frame with scrollbar
        main_frame = ttk.Frame(panel)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)
        
        canvas = tk.Canvas(main_frame, height=160)  # Limit height to about 5-6 rows
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Show current custom folder names
        ext_vars = {}
        row = 0
        
        def display_ext(ext):
            return f".{ext.lower()}"
        
        for ext, folder in self.settings.get("custom_folders", {}).items():
            ext_lc = ext.lower()
            ttk.Label(scrollable_frame, text=display_ext(ext_lc)).grid(row=row, column=0, sticky="w", padx=(0, 8))
            var = tk.StringVar(value=folder)
            ext_vars[ext_lc] = var
            entry = ttk.Entry(scrollable_frame, textvariable=var, width=25)
            entry.grid(row=row, column=1, padx=8, pady=2)
            
            # Delete button for each entry
            def make_delete_func(ext_key, row_widgets):
                def delete_entry():
                    if ext_key in ext_vars:
                        del ext_vars[ext_key]
                    for widget in row_widgets:
                        widget.destroy()
                return delete_entry
            
            delete_btn = ttk.Button(scrollable_frame, text="×", width=3)
            delete_btn.grid(row=row, column=2, padx=(4, 0))
            
            row_widgets = [scrollable_frame.grid_slaves(row=row, column=col)[0] for col in range(3)]
            delete_btn.configure(command=make_delete_func(ext_lc, row_widgets))
            
            row += 1
        
        # Add new extension section
        add_frame = ttk.Frame(panel)
        add_frame.pack(pady=(8, 0))
        
        new_ext_var = tk.StringVar()
        new_folder_var = tk.StringVar()
        error_var = tk.StringVar()
        
        def add_ext():
            ext_input = new_ext_var.get().strip()
            folder_input = new_folder_var.get().strip()
            
            # Validate extension
            ext_valid, ext_result = self.validate_extension(ext_input)
            if not ext_valid:
                error_var.set(f"Extension error: {ext_result}")
                return
            
            # Validate folder name
            folder_valid, folder_error = self.validate_folder_name(folder_input)
            if not folder_valid:
                error_var.set(f"Folder name error: {folder_error}")
                return
            
            ext = ext_result.lower()
            folder = folder_input.strip()
            
            if ext not in ext_vars:
                ext_vars[ext] = tk.StringVar(value=folder)
                
                # Add to UI
                ttk.Label(scrollable_frame, text=display_ext(ext)).grid(row=row, column=0, sticky="w", padx=(0, 8))
                entry = ttk.Entry(scrollable_frame, textvariable=ext_vars[ext], width=25)
                entry.grid(row=row, column=1, padx=8, pady=2)
                
                delete_btn = ttk.Button(scrollable_frame, text="×", width=3)
                delete_btn.grid(row=row, column=2, padx=(4, 0))
                
                def make_delete_func(ext_key, current_row):
                    def delete_entry():
                        if ext_key in ext_vars:
                            del ext_vars[ext_key]
                        for col in range(3):
                            widgets = scrollable_frame.grid_slaves(row=current_row, column=col)
                            for widget in widgets:
                                widget.destroy()
                    return delete_entry
                
                delete_btn.configure(command=make_delete_func(ext, row))
                
                new_ext_var.set("")
                new_folder_var.set("")
                error_var.set("")
                
                # Update canvas scroll region
                canvas.configure(scrollregion=canvas.bbox("all"))
            else:
                error_var.set("Extension already exists")
        
        ttk.Label(add_frame, text="Extension:").pack(side="left")
        ttk.Entry(add_frame, textvariable=new_ext_var, width=8).pack(side="left", padx=(2, 8))
        ttk.Label(add_frame, text="Folder Name:").pack(side="left")
        ttk.Entry(add_frame, textvariable=new_folder_var, width=16).pack(side="left", padx=(2, 8))
        ttk.Button(add_frame, text="Add", command=add_ext).pack(side="left")
        
        # Error label
        error_label = ttk.Label(panel, textvariable=error_var, foreground="red")
        error_label.pack(pady=(4, 0))
        
        # Clear all button
        def clear_all():
            for widget in scrollable_frame.winfo_children():
                widget.destroy()
            ext_vars.clear()
            error_var.set("")
        
        clear_btn = ttk.Button(panel, text="Clear All", command=clear_all)
        clear_btn.pack(pady=(8, 0))
        
        # Separator for clarity
        ttk.Separator(panel, orient="horizontal").pack(fill="x", pady=(8, 0))
        
        # Save/cancel buttons (always at the bottom)
        def save_and_close():
            try:
                # Validate all entries before saving
                custom_folders = {}
                for ext, var in ext_vars.items():
                    folder_name = var.get().strip()
                    if folder_name:
                        valid, error = self.validate_folder_name(folder_name)
                        if not valid:
                            error_var.set(f"Invalid folder name for .{ext}: {error}")
                            return
                        custom_folders[ext.lower()] = folder_name
                
                self.settings["custom_folders"] = custom_folders
                self.save_settings()
                panel.destroy()
                messagebox.showinfo("Settings", "Settings saved successfully!")
                
            except Exception as e:
                messagebox.showerror("Error", f"Could not save settings: {e}")
        
        def cancel():
            panel.destroy()
        
        btn_frame = ttk.Frame(panel)
        btn_frame.pack(pady=16, side="bottom")
        ttk.Button(btn_frame, text="Save", command=save_and_close).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="Cancel", command=cancel).pack(side="left", padx=8)
    
    # --- Theme Support ---
    THEMES = {
        "light": {
            "bg": "#f4f4f4",
            "fg": "#222",
            "button": "#e0e0e0",
            "highlight": "#cce6ff"
        },
        "dark": {
            "bg": "#23272e",
            "fg": "#f4f4f4",
            "button": "#333a44",
            "highlight": "#3a4a5a"
        }
    }
    
    def apply_theme(self, theme_name):
        """Apply theme with error handling."""
        try:
            if theme_name not in self.THEMES:
                theme_name = "light"
            
            theme = self.THEMES[theme_name]
            if self.root is not None:
                self.root.configure(bg=theme["bg"])
            else:
                print("[Warning] apply_theme: root is None, cannot configure bg.")
            if self.main_frame is not None:
                self.main_frame.configure(style="Main.TFrame")
            else:
                print("[Warning] apply_theme: main_frame is None, cannot configure style.")
            
            style = ttk.Style()
            style.configure("TFrame", background=theme["bg"])
            style.configure("Main.TFrame", background=theme["bg"])
            style.configure("TLabel", background=theme["bg"], foreground=theme["fg"])
            style.configure("TButton", background=theme["button"], foreground=theme["fg"])
            style.configure("TEntry", fieldbackground=theme["bg"], foreground=theme["fg"])
            style.configure("TProgressbar", background=theme["highlight"])
            
            if self.root is not None:
                self.root.update_idletasks()
            else:
                print("[Warning] apply_theme: root is None, cannot update idletasks.")
        except Exception as e:
            print(f"Warning: Could not apply theme: {e}")
    
    def toggle_theme(self):
        """Toggle between light and dark themes."""
        current = self.settings.get("theme", "light")
        new_theme = "dark" if current == "light" else "light"
        self.settings["theme"] = new_theme
        self.save_settings()
        self.apply_theme(new_theme)
    
    # --- Status Update Helpers ---
    def set_status(self, msg):
        """Update status bar."""
        if self.status_var is None or self.root is None:
            print(f"[Warning] set_status: status_var or root not initialized. Message: {msg}")
            return
        self.status_var.set(msg)
        self.root.update_idletasks()
    
    def update_unsort_button(self):
        """Update unsort button state."""
        if self.unsort_btn is None or self.folder_var is None:
            print("[Warning] update_unsort_button: unsort_btn or folder_var not initialized.")
            return
        folder = self.folder_var.get().strip()
        if folder and os.path.exists(os.path.join(folder, SORT_RECORD)):
            self.unsort_btn.state(["!disabled"])
        else:
            self.unsort_btn.state(["disabled"])
    
    # --- Threading Functions ---
    def finish_sort(self, folder):
        """Finish sorting in thread."""
        if self.root is None or self.progress is None:
            print("[Warning] finish_sort: root or progress not initialized.")
            return
        def sort_thread():
            try:
                self.sort_files_bulk(folder)
            finally:
                if self.root is None:
                    print("[Warning] finish_sort thread: root is not initialized in thread cleanup.")
                    return
                if self.progress is None:
                    print("[Warning] finish_sort thread: progress is not initialized in thread cleanup.")
                    return
                self.root.after(0, lambda: [
                    self.progress.stop() if self.progress is not None else print("[Warning] finish_sort after: progress is None (stop)"),
                    self.progress.grid_remove() if self.progress is not None else print("[Warning] finish_sort after: progress is None (grid_remove)"),
                    self.set_status("Sorting complete.") if self.status_var is not None else print("[Warning] finish_sort after: status_var is None (set_status)")
                ])
        
        threading.Thread(target=sort_thread, daemon=True).start()
    
    def finish_unsort(self, folder):
        """Finish unsorting in thread."""
        if self.root is None or self.progress is None:
            print("[Warning] finish_unsort: root or progress not initialized.")
            return
        def unsort_thread():
            try:
                self.unsort_files(folder)
            finally:
                if self.root is None:
                    print("[Warning] finish_unsort thread: root is not initialized in thread cleanup.")
                    return
                if self.progress is None:
                    print("[Warning] finish_unsort thread: progress is not initialized in thread cleanup.")
                    return
                self.root.after(0, lambda: [
                    self.progress.stop() if self.progress is not None else print("[Warning] finish_unsort after: progress is None (stop)"),
                    self.progress.grid_remove() if self.progress is not None else print("[Warning] finish_unsort after: progress is None (grid_remove)"),
                    self.set_status("Unsort complete.") if self.status_var is not None else print("[Warning] finish_unsort after: status_var is None (set_status)")
                ])
        
        threading.Thread(target=unsort_thread, daemon=True).start()
    
    def start_sort(self):
        """Start sorting process."""
        if self.folder_var is None or self.progress is None:
            print("[Warning] start_sort: folder_var or progress not initialized.")
            return
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showerror("Error", "Please select a folder.")
            return
        
        # Validate path
        valid, result = self.validate_path(folder)
        if not valid:
            messagebox.showerror("Error", result)
            return
        
        # Preview before sorting
        if not self.show_preview_dialog(folder):
            return
        
        self.progress.grid()
        self.progress.start()
        self.set_status("Sorting files...")
        self.finish_sort(folder)
    
    def start_unsort(self):
        """Start unsorting process."""
        if self.folder_var is None or self.progress is None:
            print("[Warning] start_unsort: folder_var or progress not initialized.")
            return
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showerror("Error", "Please select a folder.")
            return
        
        # Validate path
        valid, result = self.validate_path(folder)
        if not valid:
            messagebox.showerror("Error", result)
            return
        
        self.progress.grid()
        self.progress.start()
        self.set_status("Restoring files...")
        self.finish_unsort(folder)
    
    # --- GUI Setup ---
    def setup_gui(self):
        """Setup the main GUI."""
        # Create root window
        if self.dnd_available:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()
        
        self.root.title("Python File Sorter")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.root.resizable(True, True)
        
        # Set app icon
        icon_path = os.path.join(os.path.dirname(__file__), 'file sorter.ico')
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass  # Icon loading failed, continue without icon

        # --- Add Menu Bar with Help/About ---
        menubar = tk.Menu(self.root)
        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label="About", command=self.show_about_dialog)
        menubar.add_cascade(label="Help", menu=helpmenu)
        self.root.config(menu=menubar)

        # Setup style
        style = ttk.Style(self.root)
        style.theme_use('clam')
        
        self.main_frame = ttk.Frame(self.root, padding=PADDING_LARGE, style="Main.TFrame")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Theme toggle button
        theme_btn = ttk.Button(self.main_frame, text="Toggle Theme", command=self.toggle_theme)
        theme_btn.grid(row=0, column=2, sticky="e", padx=(PADDING_SMALL, 0), pady=(0, 18))

        # Apply theme on startup
        self.apply_theme(self.settings.get("theme", "light"))
        
        # Header label
        header_label = ttk.Label(self.main_frame, text="Desktop File Sorter", font=FONT_HEADER)
        header_label.grid(row=1, column=0, columnspan=3, pady=(0, 18))
        
        # Create UI components
        self.create_folder_group()
        self.create_actions_group()
        self.create_status_bar()
        
        # Progress bar
        self.progress = ttk.Progressbar(self.main_frame, mode='indeterminate')
        self.progress.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.progress.grid_remove()
        
        # Configure grid weights
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)

        # --- Attach Tooltips ---
        # Wait until widgets are created
        self.root.after(100, self.attach_tooltips)
    
    def create_folder_group(self):
        """Create folder selection group."""
        folder_group = ttk.LabelFrame(self.main_frame, text="Folder Selection", padding=(PADDING_MEDIUM, PADDING_SMALL))
        folder_group.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, PADDING_MEDIUM))
        folder_group.columnconfigure(1, weight=1)
        
        # Remove folder_path_label_var and label, only use entry for folder selection
        label = ttk.Label(folder_group, text="Select folder to sort:")
        label.grid(row=0, column=0, sticky="w", columnspan=3)
        
        self.folder_var = tk.StringVar()
        
        folder_entry = tk.Entry(folder_group, textvariable=self.folder_var, width=ENTRY_WIDTH)
        folder_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        
        def browse_folder():
            folder_selected = filedialog.askdirectory()
            if folder_selected:
                if self.folder_var is not None:
                    self.folder_var.set(folder_selected)
                else:
                    print("[Warning] browse_folder: folder_var is None, cannot set value.")
                self.update_unsort_button()
                self.set_status(f"Selected folder: {folder_selected}")
        
        browse_btn = ttk.Button(folder_group, text="Browse", command=browse_folder)
        browse_btn.grid(row=1, column=2, padx=(PADDING_SMALL, 0), sticky="ew")
        
        # Drag and Drop Label for visual feedback only
        dnd_label = ttk.Label(folder_group, text="⬇️ Drop folder here", 
                             relief="ridge", anchor="center", font=("Segoe UI", 11, "bold"))
        dnd_label.grid(row=2, column=0, columnspan=3, pady=(PADDING_SMALL, 0), sticky="ew")
        
        # Register the root window as a drop target if DnD is available
        if self.dnd_available:
            def on_label_drop(event):
                try:
                    # Handle multiple paths and clean them
                    paths = event.data.split()
                    if paths:
                        path = paths[0].strip().strip('{}').strip('"')
                        valid, result = self.validate_path(path)
                        if valid:
                            # Always replace the previous folder path
                            if self.folder_var is not None:
                                self.folder_var.set(result)  # This will update the entry and label
                            else:
                                print("[Warning] on_label_drop: folder_var is None, cannot set value.")
                            self.update_unsort_button()
                            self.set_status(f"Selected folder: {result}")
                        else:
                            messagebox.showerror("Error", f"Invalid folder: {result}")
                except Exception as e:
                    messagebox.showerror("Error", f"Could not process dropped folder: {e}")
            if hasattr(self.root, 'drop_target_register'):
                self.root.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            else:
                print("[Warning] root does not support drop_target_register.")
            if hasattr(self.root, 'dnd_bind'):
                self.root.dnd_bind('<<Drop>>', on_label_drop)  # type: ignore[attr-defined]
            else:
                print("[Warning] root does not support dnd_bind.")
        else:
            dnd_label = ttk.Label(folder_group, text="⬇️ Drop folder here", 
                                 relief="ridge", anchor="center", font=("Segoe UI", 11, "bold"))
            dnd_label.grid(row=2, column=0, columnspan=3, pady=(PADDING_SMALL, 0), sticky="ew")
    
    def create_actions_group(self):
        """Create actions button group."""
        actions_frame = ttk.Frame(self.main_frame)
        actions_frame.grid(row=3, column=0, columnspan=3, pady=(0, PADDING_MEDIUM), sticky="ew")
        actions_frame.columnconfigure((0, 1, 2), weight=1)
        
        sort_btn = ttk.Button(actions_frame, text="Sort Files", command=self.start_sort)
        sort_btn.grid(row=0, column=0, padx=(0, PADDING_SMALL), sticky="ew")
        
        self.unsort_btn = ttk.Button(actions_frame, text="Unsort (Undo)", command=self.start_unsort)
        self.unsort_btn.grid(row=0, column=1, padx=(0, PADDING_SMALL), sticky="ew")
        self.unsort_btn.state(["disabled"])
        
        settings_btn = ttk.Button(actions_frame, text="Settings", command=self.open_settings_panel)
        settings_btn.grid(row=0, column=2, sticky="ew")
    
    def create_status_bar(self):
        """Create status bar."""
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, anchor="w", 
                              relief="sunken", font=FONT_NORMAL, padding=(PADDING_SMALL, 2))
        status_bar.pack(side="bottom", fill="x")
    
    def run(self):
        """Start the application."""
        try:
            if self.root is not None:
                self.root.mainloop()
            else:
                print("[Warning] run: root is None, cannot start mainloop.")
        except KeyboardInterrupt:
            print("Application interrupted by user")
        except Exception as e:
            messagebox.showerror("Fatal Error", f"An unexpected error occurred: {e}")

    def show_about_dialog(self):
        about = tk.Toplevel(self.root)
        about.title("About Desktop File Sorter")
        about.geometry("400x300")
        about.transient(self.root)
        about.grab_set()
        ttk.Label(about, text="Desktop File Sorter", font=FONT_HEADER).pack(pady=(18, 6))
        ttk.Label(about, text="Version 2.2", font=FONT_LABEL).pack()
        ttk.Label(about, text="\nA simple tool to organize files in a folder by type.\n\n- Drag and drop a folder or use Browse.\n- Click 'Sort Files' to organize.\n- Use 'Unsort' to undo the last sort.\n- Customize folder names in Settings.\n- Toggle light/dark theme.\n\nDeveloped with ❤️ in Python.", font=FONT_NORMAL, justify="left", wraplength=360).pack(padx=18, pady=8)
        ttk.Button(about, text="Close", command=about.destroy).pack(pady=18)

    def attach_tooltips(self):
        # Folder entry, browse button, drag-and-drop label
        try:
            folder_group = self.main_frame.winfo_children()[2]  # LabelFrame
            folder_entry = folder_group.winfo_children()[1]
            browse_btn = folder_group.winfo_children()[2]
            dnd_label = folder_group.winfo_children()[3]
            Tooltip(folder_entry, "Enter or paste the path to the folder you want to sort.")
            Tooltip(browse_btn, "Browse for a folder to sort.")
            Tooltip(dnd_label, "You can drag and drop a folder here.")
        except Exception as e:
            print(f"[Tooltip] Could not attach to folder group: {e}")
        # Action buttons
        try:
            actions_frame = self.main_frame.winfo_children()[3]
            sort_btn = actions_frame.winfo_children()[0]
            unsort_btn = actions_frame.winfo_children()[1]
            settings_btn = actions_frame.winfo_children()[2]
            Tooltip(sort_btn, "Sort all files in the selected folder into subfolders by type.")
            Tooltip(unsort_btn, "Undo the last sort operation and restore files.")
            Tooltip(settings_btn, "Open settings to customize folder names for extensions.")
        except Exception as e:
            print(f"[Tooltip] Could not attach to actions group: {e}")
        # Theme toggle
        try:
            theme_btn = self.main_frame.winfo_children()[0]
            Tooltip(theme_btn, "Toggle between light and dark themes.")
        except Exception as e:
            print(f"[Tooltip] Could not attach to theme button: {e}")

def main():
    """Main entry point."""
    try:
        app = FileSorterApp()
        app.run()
    except Exception as e:
        print(f"Failed to start application: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()