import sys
import os
import json
import threading
import time
import requests
import sqlite3
import subprocess
import webbrowser
import ctypes
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QTableWidget, QTableWidgetItem, QProgressBar, QToolBar, QDialog,
                             QLineEdit, QPushButton, QLabel, QComboBox, QDialogButtonBox,
                             QHeaderView, QStackedWidget, QFileDialog, QSpinBox, QMenu, QMessageBox,
                             QSplashScreen, QListWidget, QListWidgetItem, QSystemTrayIcon, QCheckBox)
from PySide6.QtGui import QAction, QIcon, QFont, QDesktopServices, QCursor, QPixmap
from PySide6.QtCore import Qt, Signal, QObject, QPropertyAnimation, QPoint, QEasingCurve, QUrl
from flask import Flask, request, jsonify

# --- 1. 全局配置与助手函数 ---
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

PORTABLE_CONFIG_DIR = get_app_dir()
USER_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".SummerSunDownloader")

def get_config_dir():
    if os.path.exists(os.path.join(PORTABLE_CONFIG_DIR, "settings.json")):
        return PORTABLE_CONFIG_DIR
    else:
        os.makedirs(USER_CONFIG_DIR, exist_ok=True)
        return USER_CONFIG_DIR

CONFIG_DIR = get_config_dir()

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

DB_FILE = os.path.join(CONFIG_DIR, "history.db")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
LANG_PATH = resource_path("languages")
FONT_PATH = resource_path("fonts")
ICON_PATH = resource_path("icons")
STYLE_TEMPLATE_PATH = resource_path("style_template.qss")

THEMES = {
    "Dark Knight": {"accent": "#0078d7", "accent_hover": "#0089f0", "bg1": "#2b2b2b", "bg2": "#3c3c3c", "bg3": "#4f4f4f", "text1": "#f0f0f0", "text2": "#d0d0d0"},
    "Ocean Blue": {"accent": "#005f73", "accent_hover": "#0a9396", "bg1": "#e9f5f7", "bg2": "#d8eef1", "bg3": "#c1e5ea", "text1": "#001219", "text2": "#2e3e42"},
    "Forest Green": {"accent": "#4d7c0f", "accent_hover": "#65a30d", "bg1": "#f0fdf4", "bg2": "#dcfce7", "bg3": "#bbf7d0", "text1": "#14532d", "text2": "#166534"},
    "Sunrise Orange": {"accent": "#ea580c", "accent_hover": "#f97316", "bg1": "#fff7ed", "bg2": "#ffedd5", "bg3": "#fed7aa", "text1": "#7c2d12", "text2": "#9a3412"},
    "Royal Purple": {"accent": "#7e22ce", "accent_hover": "#9333ea", "bg1": "#f5f3ff", "bg2": "#ede9fe", "bg3": "#ddd6fe", "text1": "#581c87", "text2": "#6b21a8"},
    "Crimson Red": {"accent": "#dc2626", "accent_hover": "#ef4444", "bg1": "#fef2f2", "bg2": "#fee2e2", "bg3": "#fecaca", "text1": "#7f1d1d", "text2": "#991b1b"},
    "Slate Gray": {"accent": "#475569", "accent_hover": "#64748b", "bg1": "#f8fafc", "bg2": "#f1f5f9", "bg3": "#e2e8f0", "text1": "#1e293b", "text2": "#334155"},
    "Cyberpunk Neon": {"accent": "#db2777", "accent_hover": "#ec4899", "bg1": "#1e1b4b", "bg2": "#312e81", "bg3": "#4338ca", "text1": "#e0e7ff", "text2": "#c7d2fe"},
    "Coffee Cream": {"accent": "#78350f", "accent_hover": "#92400e", "bg1": "#fdfaf6", "bg2": "#f3eade", "bg3": "#e7d8c9", "text1": "#422006", "text2": "#572e0e"},
    "Mint Fresh": {"accent": "#059669", "accent_hover": "#10b981", "bg1": "#f0fdfa", "bg2": "#ccfbf1", "bg3": "#99f6e4", "text1": "#047857", "text2": "#065f46"},
}
lang_data, settings = {}, {}

def load_settings():
    global settings
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        settings = {"theme": "Dark Knight", "max_concurrent": 3, "language": "en", "speed_limit_kb": 0, "minimize_to_tray": True}
    defaults = {"download_path": os.path.expanduser("~/Downloads"), "language": "en", "speed_limit_kb": 0, "minimize_to_tray": True, "max_concurrent": 3, "theme": "Dark Knight"}
    for key, value in defaults.items():
        if key not in settings or settings.get(key) in [None, ""]:
            settings[key] = value

def save_settings():
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=4)

def apply_theme(app_or_window):
    theme_name = settings.get("theme", "Dark Knight")
    palette = THEMES.get(theme_name, THEMES["Dark Knight"])
    try:
        with open(STYLE_TEMPLATE_PATH, "r", encoding='utf-8') as f:
            template = f.read()
        stylesheet = template.replace("{COLOR_ACCENT}", palette["accent"]) \
                             .replace("{COLOR_ACCENT_HOVER}", palette["accent_hover"]) \
                             .replace("{COLOR_BACKGROUND_1}", palette["bg1"]) \
                             .replace("{COLOR_BACKGROUND_2}", palette["bg2"]) \
                             .replace("{COLOR_BACKGROUND_3}", palette["bg3"]) \
                             .replace("{COLOR_TEXT_PRIMARY}", palette["text1"]) \
                             .replace("{COLOR_TEXT_SECONDARY}", palette["text2"])
        app_or_window.setStyleSheet(stylesheet)
    except Exception as e:
        print(f"Error applying theme: {e}")

# --- 2. 数据库管理 ---
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE NOT NULL, filename TEXT,
            filepath TEXT, total_size INTEGER, downloaded_size INTEGER DEFAULT 0,
            status TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.commit()

# --- 3. 后端工作线程 ---
class DownloadWorker(QObject):
    progress = Signal(int, int, str, str, str)
    finished = Signal(int, str)
    def __init__(self, db_id, url, filepath, resume_from=0):
        super().__init__()
        self.db_id, self.url, self.filepath = db_id, url, filepath
        self.resume_from = resume_from
        self.is_paused = threading.Event()
    def run(self):
        try:
            speed_limit_kb = settings.get("speed_limit_kb", 0)
            speed_limit_bytes = speed_limit_kb * 1024
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'}
            if self.resume_from > 0:
                headers['Range'] = f'bytes={self.resume_from}-'
            with requests.get(self.url, stream=True, timeout=30, headers=headers) as r:
                r.raise_for_status()
                content_length = int(r.headers.get('content-length', 0))
                total_size = content_length + self.resume_from
                mode = 'ab' if self.resume_from > 0 else 'wb'
                downloaded_size = self.resume_from
                last_time, last_downloaded_size = time.time(), downloaded_size
                with open(self.filepath, mode) as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        chunk_start_time = time.time()
                        if self.is_paused.is_set():
                            self._update_db(downloaded_size, "Paused")
                            self.finished.emit(self.db_id, "Paused")
                            return
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            current_time = time.time()
                            if current_time - last_time >= 1:
                                speed = (downloaded_size - last_downloaded_size) / (current_time - last_time)
                                size_str = f"{downloaded_size/1024**2:.2f}MB / {total_size/1024**2:.2f}MB"
                                speed_str = f"{speed/1024**2:.2f}MB/s" if speed > 1024**2 else f"{speed/1024:.2f}KB/s"
                                self.progress.emit(self.db_id, int((downloaded_size/total_size)*100) if total_size > 0 else 0, size_str, speed_str, "Downloading")
                                self._update_db(downloaded_size, "Downloading", total_size)
                                last_time, last_downloaded_size = current_time, downloaded_size
                            if speed_limit_bytes > 0:
                                elapsed = time.time() - chunk_start_time
                                expected_time = len(chunk) / speed_limit_bytes
                                if elapsed < expected_time:
                                    time.sleep(expected_time - elapsed)
            self._update_db(downloaded_size, "Complete", total_size)
            self.finished.emit(self.db_id, "Complete")
        except Exception as e:
            print(f"Worker Error (ID: {self.db_id}): {e}")
            self._update_db(self.resume_from, "Error")
            self.finished.emit(self.db_id, "Error")
    def _update_db(self, downloaded_size, status, total_size=None):
        with sqlite3.connect(DB_FILE) as conn:
            if total_size is not None:
                conn.execute("UPDATE downloads SET downloaded_size=?, status=?, total_size=? WHERE id=?", (downloaded_size, status, total_size, self.db_id))
            else:
                conn.execute("UPDATE downloads SET downloaded_size=?, status=? WHERE id=?", (downloaded_size, status, self.db_id))
            conn.commit()
    def pause(self): self.is_paused.set()

# --- 4. UI 界面定义 ---
class DownloadsPage(QWidget):
    download_complete_signal = Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.workers = {}
        self.db_id_to_row = {}
        self.init_ui()
    def init_ui(self):
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        top_layout = QHBoxLayout(); top_layout.setContentsMargins(10, 5, 10, 5)
        self.toolbar = QToolBar("Downloads"); self.add_action = QAction(self); self.pause_resume_action = QAction(self); self.delete_action = QAction(self)
        self.toolbar.addAction(self.add_action); self.toolbar.addAction(self.pause_resume_action); self.toolbar.addAction(self.delete_action)
        self.search_box = QLineEdit(self, objectName="SearchBox"); self.search_box.textChanged.connect(self.filter_table)
        top_layout.addWidget(self.toolbar); top_layout.addStretch(); top_layout.addWidget(self.search_box)
        layout.addLayout(top_layout)
        self.table = QTableWidget(0, 5); self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.horizontalHeader().setStretchLastSection(True); self.table.verticalHeader().setVisible(False); self.table.setShowGrid(False); self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.table.customContextMenuRequested.connect(self.show_context_menu); self.table.cellDoubleClicked.connect(self.open_file_on_double_click); self.table.selectionModel().selectionChanged.connect(self.update_pause_resume_button)
        layout.addWidget(self.table)
        self.add_action.triggered.connect(self.show_add_url_dialog); self.pause_resume_action.triggered.connect(self.toggle_pause_resume); self.delete_action.triggered.connect(self.delete_task)
    def retranslate_ui(self):
        self.add_action.setText(lang_data.get("add_url_button")); self.add_action.setIcon(QIcon(os.path.join(ICON_PATH, "add.svg")))
        self.delete_action.setText(lang_data.get("delete_button")); self.delete_action.setIcon(QIcon(os.path.join(ICON_PATH, "delete.svg")))
        self.search_box.setPlaceholderText(lang_data.get("search_placeholder"))
        headers = [lang_data.get(k, k) for k in ["col_filename", "col_size", "col_progress", "col_speed", "col_status"]]
        self.table.setHorizontalHeaderLabels(headers)
        self.update_pause_resume_button()
    def load_history(self, status_filter=None):
        self.table.setRowCount(0)
        self.db_id_to_row.clear()
        query = "SELECT id, filename, total_size, downloaded_size, status FROM downloads"
        params = []
        if status_filter and status_filter != "All":
            query += " WHERE status=?"
            params.append(status_filter)
        query += " ORDER BY created_at DESC"
        with sqlite3.connect(DB_FILE) as conn:
            for row_data in conn.execute(query, params):
                self._add_or_update_row(*row_data)
    def _add_or_update_row(self, db_id, filename, total_size, downloaded_size, status):
        row_idx = self.db_id_to_row.get(db_id)
        if row_idx is None:
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)
            self.db_id_to_row[db_id] = row_idx
        filename_item = QTableWidgetItem(filename); filename_item.setData(Qt.ItemDataRole.UserRole, db_id)
        self.table.setItem(row_idx, 0, filename_item)
        size_str = f"{downloaded_size/1024**2:.2f}MB / {total_size/1024**2:.2f}MB" if total_size else "N/A"
        self.table.setItem(row_idx, 1, QTableWidgetItem(size_str))
        progress_bar = QProgressBar(); percent = int((downloaded_size / total_size) * 100) if total_size else 0
        progress_bar.setValue(percent)
        self.table.setCellWidget(row_idx, 2, progress_bar)
        self.table.setItem(row_idx, 3, QTableWidgetItem("N/A"))
        self.table.setItem(row_idx, 4, QTableWidgetItem(lang_data.get(f"status_{status.lower()}", status)))
    def show_add_url_dialog(self):
        dialog = QDialog(self); dialog.setWindowTitle(lang_data.get("add_url_button")); layout = QVBoxLayout(dialog)
        url_input = QLineEdit(placeholderText="Enter URL"); layout.addWidget(url_input)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec():
            url = url_input.text().strip()
            if url: self.start_new_download(url)
    def start_new_download(self, url):
        filename = url.split('/')[-1].split('?')[0] or "new_download"
        filepath = os.path.join(settings["download_path"], filename)
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM downloads WHERE url=?", (url,))
            existing = cursor.fetchone()
            if existing: db_id = existing[0]
            else:
                cursor.execute("INSERT INTO downloads (url, filename, filepath, status) VALUES (?, ?, ?, ?)", (url, filename, filepath, "Ready"))
                db_id = cursor.lastrowid
            conn.commit()
        self.load_history()
        self.resume_download(db_id)
    def resume_download(self, db_id):
        if len(self.workers) >= settings.get("max_concurrent", 3): return
        with sqlite3.connect(DB_FILE) as conn: data = conn.execute("SELECT url, filepath, downloaded_size FROM downloads WHERE id=?", (db_id,)).fetchone()
        if data:
            url, filepath, resume_from = data
            worker = DownloadWorker(db_id, url, filepath, resume_from)
            worker.progress.connect(self.update_download_progress); worker.finished.connect(self.on_download_finished)
            thread = threading.Thread(target=worker.run, daemon=True)
            self.workers[db_id] = (thread, worker)
            thread.start()
    def toggle_pause_resume(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows: return
        db_id = self.table.item(selected_rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        status = self.get_status_by_db_id(db_id)
        if status == "Downloading":
            if db_id in self.workers: self.workers[db_id][1].pause()
        elif status in ["Paused", "Error"]: self.resume_download(db_id)
    def delete_task(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows: return
        row = selected_rows[0].row()
        db_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if db_id in self.workers: self.workers[db_id][1].pause()
        with sqlite3.connect(DB_FILE) as conn: conn.execute("DELETE FROM downloads WHERE id=?", (db_id,))
        self.table.removeRow(row)
        for k, v in list(self.db_id_to_row.items()):
            if v == row: del self.db_id_to_row[k]
            elif v > row: self.db_id_to_row[k] = v - 1
        if db_id in self.workers: del self.workers[db_id]
    def update_pause_resume_button(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows: self.pause_resume_action.setEnabled(False); return
        status = self.table.item(selected_rows[0].row(), 4).text()
        if status == lang_data.get("status_downloading"):
            self.pause_resume_action.setEnabled(True); self.pause_resume_action.setText(lang_data.get("pause_button")); self.pause_resume_action.setIcon(QIcon(os.path.join(ICON_PATH, "pause.svg")))
        elif status in [lang_data.get("status_paused"), lang_data.get("status_error")]:
            self.pause_resume_action.setEnabled(True); self.pause_resume_action.setText(lang_data.get("resume_button")); self.pause_resume_action.setIcon(QIcon(os.path.join(ICON_PATH, "play.svg")))
        else: self.pause_resume_action.setEnabled(False); self.pause_resume_action.setText(lang_data.get("pause_button")); self.pause_resume_action.setIcon(QIcon(os.path.join(ICON_PATH, "pause.svg")))
    def update_download_progress(self, db_id, percent, size_str, speed_str, status):
        if db_id in self.db_id_to_row:
            row = self.db_id_to_row[db_id]
            if self.table.rowCount() > row:
                self.table.item(row, 1).setText(size_str); self.table.cellWidget(row, 2).setValue(percent); self.table.item(row, 3).setText(speed_str); self.table.item(row, 4).setText(lang_data.get(f"status_{status.lower()}"))
    def on_download_finished(self, db_id, status):
        if db_id in self.db_id_to_row:
            row = self.db_id_to_row[db_id]
            if self.table.rowCount() > row:
                filename = self.table.item(row, 0).text()
                self.table.item(row, 4).setText(lang_data.get(f"status_{status.lower()}", status))
                if status == "Complete":
                    self.table.cellWidget(row, 2).setValue(100)
                    self.download_complete_signal.emit(filename)
        if db_id in self.workers: del self.workers[db_id]
        self.update_pause_resume_button()
    def filter_table(self, text):
        for row in range(self.table.rowCount()): self.table.setRowHidden(row, text.lower() not in self.table.item(row, 0).text().lower())
    def show_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0: return
        db_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        with sqlite3.connect(DB_FILE) as conn: data = conn.execute("SELECT filepath, status FROM downloads WHERE id=?", (db_id,)).fetchone()
        if not data: return
        filepath, status = data
        menu = QMenu(); open_action = menu.addAction(lang_data.get("open_file")); open_action.setEnabled(status == "Complete"); folder_action = menu.addAction(lang_data.get("open_folder"))
        action = menu.exec(self.table.mapToGlobal(pos))
        try:
            if action == open_action:
                if sys.platform == "win32": os.startfile(filepath)
                else: subprocess.call(("open", filepath))
            elif action == folder_action:
                if sys.platform == "win32": os.startfile(os.path.dirname(filepath))
                else: subprocess.call(("open", os.path.dirname(filepath)))
        except Exception as e: print(f"Error opening file/folder: {e}")
    def open_file_on_double_click(self, row, col):
        db_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        with sqlite3.connect(DB_FILE) as conn: status = conn.execute("SELECT status FROM downloads WHERE id=?", (db_id,)).fetchone()[0]
        if status == "Complete": self.show_context_menu(self.table.visualItemRect(self.table.item(row, col)).center())
    def get_status_by_db_id(self, db_id):
        with sqlite3.connect(DB_FILE) as conn:
            result = conn.execute("SELECT status FROM downloads WHERE id=?", (db_id,)).fetchone()
            return result[0] if result else None
class SettingsPage(QWidget):
    settings_saved = Signal()
    def __init__(self, parent=None):
        super().__init__(parent); self.setObjectName("SettingsPage"); self.init_ui(); self.load_ui_from_settings()
    def init_ui(self):
        layout = QVBoxLayout(self); layout.setContentsMargins(40, 20, 40, 20); layout.setSpacing(15)
        self.title = QLabel(); self.title.setStyleSheet("font-size: 20px; font-weight: bold;"); layout.addWidget(self.title)
        self.path_label = QLabel(); self.path_edit = QLineEdit(); self.path_button = QPushButton(); self.path_button.clicked.connect(self.browse_path)
        path_layout = QHBoxLayout(); path_layout.addWidget(self.path_edit); path_layout.addWidget(self.path_button)
        layout.addLayout(path_layout)
        self.max_label = QLabel(); self.max_spinbox = QSpinBox(); self.max_spinbox.setRange(1, 10)
        layout.addWidget(self.max_label); layout.addWidget(self.max_spinbox)
        self.speed_label = QLabel(); self.speed_limit_spinbox = QSpinBox(); self.speed_limit_spinbox.setRange(0, 100000); self.speed_limit_spinbox.setSingleStep(100)
        layout.addWidget(self.speed_label); layout.addWidget(self.speed_limit_spinbox)
        self.lang_label = QLabel(); self.lang_combo = QComboBox(); self.lang_combo.addItems(["English", "中文"])
        layout.addWidget(self.lang_label); layout.addWidget(self.lang_combo)
        self.theme_label = QLabel(); self.theme_combo = QComboBox(); self.theme_combo.addItems(THEMES.keys())
        layout.addWidget(self.theme_label); layout.addWidget(self.theme_combo)
        self.tray_checkbox = QCheckBox(); layout.addWidget(self.tray_checkbox)
        layout.addStretch()
        self.save_button = QPushButton(); self.save_button.clicked.connect(self.save_ui_to_settings)
        layout.addWidget(self.save_button, 0, Qt.AlignmentFlag.AlignRight)
    def retranslate_ui(self):
        self.title.setText(lang_data.get("settings_title")); self.path_label.setText(lang_data.get("download_location")); self.path_button.setText(lang_data.get("browse"))
        self.max_label.setText(lang_data.get("max_concurrent_downloads")); self.speed_label.setText(lang_data.get("speed_limit")); self.speed_limit_spinbox.setSuffix(" KB/s")
        self.lang_label.setText(lang_data.get("language")); self.theme_label.setText(lang_data.get("theme")); self.save_button.setText(lang_data.get("save_settings"))
        self.tray_checkbox.setText(lang_data.get("minimize_to_tray"))
    def browse_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Folder", self.path_edit.text())
        if path: self.path_edit.setText(path)
    def load_ui_from_settings(self):
        self.path_edit.setText(settings.get("download_path", "")); self.max_spinbox.setValue(settings.get("max_concurrent", 3)); self.theme_combo.setCurrentText(settings.get("theme", "Dark Knight"))
        self.lang_combo.setCurrentIndex(1 if settings.get("language") == "zh" else 0); self.speed_limit_spinbox.setValue(settings.get("speed_limit_kb", 0))
        self.tray_checkbox.setChecked(settings.get("minimize_to_tray", True))
    def save_ui_to_settings(self):
        settings["download_path"] = self.path_edit.text(); settings["max_concurrent"] = self.max_spinbox.value(); settings["theme"] = self.theme_combo.currentText()
        settings["language"] = "zh" if self.lang_combo.currentIndex() == 1 else "en"; settings["speed_limit_kb"] = self.speed_limit_spinbox.value()
        settings["minimize_to_tray"] = self.tray_checkbox.isChecked()
        save_settings()
        self.settings_saved.emit()
class AboutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.setObjectName("AboutPage"); self.init_ui()
    def init_ui(self):
        layout = QVBoxLayout(self); layout.setContentsMargins(40, 40, 40, 40); layout.setSpacing(20); layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel(); self.title.setStyleSheet("font-size: 24px; font-weight: bold;"); self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.my_info = QLabel(); self.my_info.setStyleSheet("font-size: 16px;"); self.my_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.github_button = QPushButton()
        self.github_button.clicked.connect(lambda: webbrowser.open("https://github.com/Close245"))
        layout.addWidget(self.title); layout.addWidget(self.my_info); layout.addStretch(); layout.addWidget(self.github_button); layout.addStretch()
    def retranslate_ui(self):
        self.title.setText(lang_data.get("about_title")); self.my_info.setText(lang_data.get("about_me"))
        self.github_button.setText(lang_data.get("github_link")); self.github_button.setIcon(QIcon(os.path.join(ICON_PATH, "github.svg")))

class DownloaderApp(QMainWindow):
    add_download_task_signal = Signal(str)
    def __init__(self):
        super().__init__()
        self.load_language()
        self.init_tray_icon() # MUST be before init_ui
        self.init_ui()
        self.add_download_task_signal.connect(self.forward_download_task)

    def init_ui(self):
        self.setWindowTitle("SummerSun Downloader"); self.setGeometry(200, 200, 1000, 750)
        central_widget = QWidget(); self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget); main_layout.setSpacing(0); main_layout.setContentsMargins(0, 0, 0, 0)
        nav_panel = QWidget(); nav_panel.setFixedWidth(220); nav_layout = QVBoxLayout(nav_panel); nav_layout.setContentsMargins(0, 0, 0, 0); nav_layout.setSpacing(0)
        sidebar = QWidget(); sidebar.setObjectName("Sidebar"); sidebar_layout = QVBoxLayout(sidebar); sidebar_layout.setContentsMargins(0, 10, 0, 10); sidebar_layout.setSpacing(5)
        self.nav_downloads_btn = QPushButton(objectName="NavButton", checkable=True, checked=True); self.nav_settings_btn = QPushButton(objectName="NavButton", checkable=True); self.nav_about_btn = QPushButton(objectName="NavButton", checkable=True)
        sidebar_layout.addWidget(self.nav_downloads_btn); sidebar_layout.addWidget(self.nav_settings_btn); sidebar_layout.addWidget(self.nav_about_btn); sidebar_layout.addStretch()
        nav_layout.addWidget(sidebar)
        self.category_list = QListWidget(objectName="CategoryList"); self.category_list.setFixedWidth(220); self.category_list.currentItemChanged.connect(self.filter_downloads_by_category)
        nav_layout.addWidget(self.category_list)
        main_layout.addWidget(nav_panel)
        self.stacked_widget = QStackedWidget(); main_layout.addWidget(self.stacked_widget)
        self.downloads_page = DownloadsPage(); self.settings_page = SettingsPage(); self.about_page = AboutPage()
        self.stacked_widget.addWidget(self.downloads_page); self.stacked_widget.addWidget(self.settings_page); self.stacked_widget.addWidget(self.about_page)
        self.downloads_page.download_complete_signal.connect(self.show_tray_notification)
        self.nav_downloads_btn.clicked.connect(lambda: self.switch_view(0)); self.nav_settings_btn.clicked.connect(lambda: self.switch_view(1)); self.nav_about_btn.clicked.connect(lambda: self.switch_view(2))
        self.settings_page.settings_saved.connect(self.on_settings_saved)
        self.retranslate_ui()

    def init_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(os.path.join(ICON_PATH, "app_icon.ico")))
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        tray_menu = QMenu()
        self.show_action = QAction(self); self.show_action.triggered.connect(self.toggle_visibility)
        self.quit_action = QAction(self); self.quit_action.triggered.connect(self.quit_application)
        tray_menu.addAction(self.show_action); tray_menu.addSeparator(); tray_menu.addAction(self.quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def on_settings_saved(self):
        self.load_language()
        apply_theme(QApplication.instance())
        self.retranslate_ui()
        self.downloads_page.retranslate_ui()
        self.settings_page.retranslate_ui()
        self.about_page.retranslate_ui()
        QMessageBox.information(self, lang_data.get("settings_saved_title"), lang_data.get("settings_saved_body_instant"))

    def load_language(self):
        global lang_data; lang_code = settings.get("language", "en")
        path = os.path.join(LANG_PATH, f"{lang_code}.json")
        try:
            with open(path, 'r', encoding='utf-8') as f: lang_data = json.load(f)
        except Exception:
            with open(os.path.join(LANG_PATH, "en.json"), 'r', encoding='utf-8') as f: lang_data = json.load(f)

    def retranslate_ui(self):
        self.setWindowTitle(lang_data.get("window_title")); self.nav_downloads_btn.setText(f" {lang_data.get('downloads_nav')}"); self.nav_downloads_btn.setIcon(QIcon(os.path.join(ICON_PATH, "download.svg")))
        self.nav_settings_btn.setText(f" {lang_data.get('settings_nav')}"); self.nav_settings_btn.setIcon(QIcon(os.path.join(ICON_PATH, "settings.svg")))
        self.nav_about_btn.setText(f" {lang_data.get('about_nav')}"); self.nav_about_btn.setIcon(QIcon(os.path.join(ICON_PATH, "info.svg")))
        self.category_list.blockSignals(True); self.category_list.clear()
        self.categories = {"cat_all": "All", "cat_downloading": "Downloading", "cat_paused": "Paused", "cat_completed": "Complete", "cat_error": "Error"}
        for key, value in self.categories.items():
            item = QListWidgetItem(lang_data.get(key)); item.setData(Qt.ItemDataRole.UserRole, value); self.category_list.addItem(item)
        self.category_list.setCurrentRow(0); self.category_list.blockSignals(False)
        self.show_action.setText(lang_data.get("tray_show_hide")); self.quit_action.setText(lang_data.get("tray_quit"))

    def switch_view(self, index):
        if index == self.stacked_widget.currentIndex(): return
        self.nav_downloads_btn.setChecked(index == 0); self.nav_settings_btn.setChecked(index == 1); self.nav_about_btn.setChecked(index == 2)
        self.category_list.setVisible(index == 0)
        self.stacked_widget.setCurrentIndex(index)
    
    def filter_downloads_by_category(self, current, previous):
        if current:
            status_filter = current.data(Qt.ItemDataRole.UserRole)
            self.downloads_page.load_history(status_filter)

    def forward_download_task(self, url):
        self.activate_window();
        if self.stacked_widget.currentIndex() != 0: self.switch_view(0)
        self.downloads_page.start_new_download(url)

    def activate_window(self):
        self.showNormal(); self.activateWindow(); self.raise_()
        if sys.platform == "win32":
            try: ctypes.windll.user32.SetForegroundWindow(self.winId())
            except Exception as e: print(f"Could not bring window to front: {e}")

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger: self.toggle_visibility()

    def toggle_visibility(self):
        if self.isVisible(): self.hide()
        else: self.show(); self.activate_window()

    def closeEvent(self, event):
        if settings.get("minimize_to_tray", True):
            event.ignore(); self.hide(); self.tray_icon.showMessage(lang_data.get("tray_minimized_title"), lang_data.get("tray_minimized_body"), QSystemTrayIcon.MessageIcon.Information, 2000)
        else:
            self.quit_application()

    def quit_application(self):
        self.tray_icon.hide(); QApplication.instance().quit()

    def show_tray_notification(self, filename):
        self.tray_icon.showMessage(lang_data.get("tray_complete_title"), f"'{filename}' {lang_data.get('tray_complete_body')}", QSystemTrayIcon.MessageIcon.Information, 4000)

# --- 5. Flask服务与主程序入口 ---
flask_app = Flask(__name__)
main_app = None
@flask_app.route('/add_download', methods=['POST'])
def add_download_route():
    url = request.json.get('url')
    if url and main_app: main_app.add_download_task_signal.emit(url); return jsonify({"status": "success"}), 200
    return jsonify({"status": "error"}), 400
def run_flask():
    if not os.environ.get("WERKZEUG_RUN_MAIN"): print("Flask server started on http://127.0.0.1:5678")
    flask_app.run(port=5678, debug=False)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    QApplication.setQuitOnLastWindowClosed(False)
    try:
        splash_pix = QPixmap(resource_path("icons/splash.png"))
        splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint)
        splash.show()
    except Exception as e:
        print(f"Could not load splash screen (is splash.png in icons folder?): {e}")
        splash = None
    app.processEvents()
    init_db()
    load_settings()
    main_app = DownloaderApp()
    apply_theme(app)
    main_app.retranslate_ui() # Ensure all text is correct on first launch, including tray menu
    if splash:
        splash.finish(main_app)
    main_app.show()
    flask_thread = threading.Thread(target=run_flask, daemon=True); flask_thread.start()
    sys.exit(app.exec())