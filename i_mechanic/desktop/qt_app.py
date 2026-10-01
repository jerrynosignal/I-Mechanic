#!/usr/bin/env python3
"""PySide6 desktop workspace for I, Mechanic."""
import json
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import coach
from ..services import RaceEngineerService
from ..storage import Repository

THEMES = {
    "Light": {
        "background": "#f2f1eb", "text": "#202522", "topbar": "#171d1a", "rail": "#202824",
        "surface": "#fbfaf5", "subsurface": "#f5f4ed", "border": "#d9d9cf", "field": "#fffefa",
        "muted": "#778078", "eyebrow": "#768078", "button": "#e6e5dc", "button_hover": "#ddded1",
        "selection": "#d8eda8", "splitter": "#dfded5", "brand": "#e8eee5",
    },
    "Dark": {
        "background": "#171c19", "text": "#e2e8e1", "topbar": "#101512", "rail": "#1d2420",
        "surface": "#202824", "subsurface": "#252e28", "border": "#37433a", "field": "#151b17",
        "muted": "#a0aaa1", "eyebrow": "#a0aaa1", "button": "#303a33", "button_hover": "#3a463d",
        "selection": "#39453c", "splitter": "#303a33", "brand": "#e8eee5",
    },
}
ACCENTS = {
    "Lime": ("#b5e34d", "#c5ed69"),
    "Cyan": ("#68d8c2", "#83e8d3"),
    "Amber": ("#f0b45c", "#fac678"),
    "Blue": ("#82adff", "#9bbdff"),
}
PROVIDER_LABELS = (
    ("lmstudio", "LM Studio"),
    ("ollama", "Ollama"),
    ("openai", "OpenAI"),
    ("openrouter", "OpenRouter"),
    ("groq", "Groq"),
    ("together", "Together"),
)


def build_stylesheet(theme, accent, font_size, compact):
    if theme == "System":
        theme = "Dark" if QApplication.palette().color(QPalette.Window).lightness() < 128 else "Light"
    colors = THEMES.get(theme, THEMES["Dark"])
    accent_color, accent_hover = ACCENTS.get(accent, ACCENTS["Lime"])
    spacing = "6px 9px" if compact else "8px 12px"
    return f"""
QWidget {{ color: {colors['text']}; background: {colors['background']}; font-family: 'Segoe UI'; font-size: {font_size}pt; }}
QMainWindow, QDialog {{ background: {colors['background']}; }}
QFrame#topbar {{ background: {colors['topbar']}; border: 0; }}
QFrame#rail {{ background: {colors['rail']}; border: 0; }}
QFrame#surface {{ background: {colors['surface']}; border: 1px solid {colors['border']}; border-radius: 9px; }}
QFrame#subsurface {{ background: {colors['subsurface']}; border: 1px solid {colors['border']}; border-radius: 7px; }}
QLabel#brand {{ color: {colors['brand']}; font-size: 17pt; font-weight: 700; }}
QLabel#eyebrow {{ color: {colors['eyebrow']}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#hero {{ color: {colors['text']}; font-size: 23pt; font-weight: 700; }}
QLabel#muted {{ color: {colors['muted']}; }}
QLabel#metric {{ color: {colors['text']}; font-family: 'Consolas'; font-size: 12pt; font-weight: 700; }}
QLabel#lime {{ color: {accent_color}; font-weight: 700; }}
QLabel#coral {{ color: #e88772; font-weight: 700; }}
QPushButton {{ background: {colors['button']}; border: 1px solid {colors['border']}; border-radius: 6px; padding: {spacing}; font-weight: 600; }}
QPushButton:hover {{ background: {colors['button_hover']}; }}
QPushButton#primary {{ background: {accent_color}; border: 0; color: #1e2817; padding: 11px 16px; font-weight: 700; }}
QPushButton#primary:hover {{ background: {accent_hover}; }}
QPushButton#darkAction {{ background: #343d37; color: #f3f5ef; border: 0; }}
QComboBox, QLineEdit, QSpinBox {{ background: {colors['field']}; border: 1px solid {colors['border']}; border-radius: 5px; padding: {spacing}; selection-background-color: {accent_color}; }}
QComboBox#railCombo {{ background: #2d3731; color: #f3f5ef; border-color: #465148; }}
QPlainTextEdit, QListWidget {{ background: {colors['field']}; border: 1px solid {colors['border']}; border-radius: 6px; padding: 8px; selection-background-color: {colors['selection']}; }}
QListWidget#sessions {{ background: transparent; border: 0; color: #e5ebe3; padding: 2px; }}
QListWidget#sessions::item {{ padding: 10px 8px; border-radius: 5px; }}
QListWidget#sessions::item:selected {{ background: {colors['selection']}; color: {accent_color}; }}
QTabWidget::pane {{ border: 1px solid {colors['border']}; border-radius: 7px; background: {colors['surface']}; top: -1px; }}
QTabBar::tab {{ color: {colors['muted']}; background: transparent; padding: 10px 14px; margin-right: 4px; font-weight: 600; }}
QTabBar::tab:selected {{ color: {colors['text']}; border-bottom: 3px solid {accent_color}; }}
QSplitter::handle {{ background: {colors['splitter']}; width: 1px; }}
"""


def load_coach_module():
    return coach


class TaskThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def run(self):
        try:
            result = self.callback(self.progress.emit)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class ProjectDialog(QDialog):
    def __init__(self, project=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Project details")
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.fields = {}
        values = {
            "Project name": project.get("name", "") if project else "",
            "Game": project.get("game", "Assetto Corsa Competizione") if project else "Assetto Corsa Competizione",
            "Car": project.get("car", "") if project else "",
            "Track": project.get("track", "") if project else "",
        }
        for label, value in values.items():
            field = QLineEdit(value)
            field.setPlaceholderText(label)
            self.fields[label] = field
            form.addRow(label, field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {label: field.text().strip() for label, field in self.fields.items()}


class SettingsDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        heading = QLabel("APPEARANCE")
        heading.setObjectName("eyebrow")
        layout.addWidget(heading)
        form = QFormLayout()

        self.theme_box = QComboBox()
        self.theme_box.addItems(("Dark", "Light", "System"))
        self.theme_box.setCurrentText(preferences["theme"])
        form.addRow("Theme", self.theme_box)

        self.accent_box = QComboBox()
        self.accent_box.addItems(ACCENTS)
        self.accent_box.setCurrentText(preferences["accent"])
        form.addRow("Accent color", self.accent_box)

        self.font_size = QSpinBox()
        self.font_size.setRange(9, 16)
        self.font_size.setSuffix(" pt")
        self.font_size.setValue(preferences["font_size"])
        form.addRow("Text size", self.font_size)

        self.compact_check = QCheckBox("Use compact spacing")
        self.compact_check.setChecked(preferences["compact"])
        form.addRow("Layout", self.compact_check)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {
            "theme": self.theme_box.currentText(),
            "accent": self.accent_box.currentText(),
            "font_size": self.font_size.value(),
            "compact": self.compact_check.isChecked(),
        }


class RaceEngineerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("I, Mechanic")
        self.resize(1500, 930)
        self.setMinimumSize(1120, 720)
        self.coach = load_coach_module()
        self.repository = Repository()
        self.service = RaceEngineerService(self.repository, self.coach)
        self.projects = []
        self.project_id = None
        self.sessions = []
        self.current_session_id = None
        self.worker = None
        self._close_pending = False
        self.preferences_store = QSettings("Sim Pit House", "I, Mechanic")
        self.preferences = self._load_preferences()
        self._apply_preferences()
        self._build_ui()
        self._load_projects()

    def _load_preferences(self):
        theme = self.preferences_store.value("appearance/theme", "Dark")
        accent = self.preferences_store.value("appearance/accent", "Lime")
        return {
            "theme": theme if theme in ("Dark", "Light", "System") else "Dark",
            "accent": accent if accent in ACCENTS else "Lime",
            "font_size": self.preferences_store.value("appearance/font_size", 10, type=int),
            "compact": self.preferences_store.value("appearance/compact", False, type=bool),
        }

    def _apply_preferences(self):
        app = QApplication.instance()
        app.setFont(QFont("Segoe UI", self.preferences["font_size"]))
        self.setStyleSheet(build_stylesheet(**{
            "theme": self.preferences["theme"],
            "accent": self.preferences["accent"],
            "font_size": self.preferences["font_size"],
            "compact": self.preferences["compact"],
        }))

    def _open_settings(self):
        dialog = SettingsDialog(self.preferences, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.preferences = dialog.values()
        for key, value in self.preferences.items():
            self.preferences_store.setValue(f"appearance/{key}", value)
        self.preferences_store.sync()
        self._apply_preferences()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
            self.status_label.setText("WAITING FOR LOCAL MODEL REQUEST TO FINISH…")
            if not self._close_pending:
                self._close_pending = True
                self.worker.finished.connect(self.close)
            return
        self.repository.close()
        event.accept()

    def _build_ui(self):
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_topbar())

        workspace = QSplitter(Qt.Horizontal)
        workspace.setChildrenCollapsible(False)
        self.rail = self._build_rail()
        workspace.addWidget(self.rail)
        workspace.addWidget(self._build_main_area())
        workspace.addWidget(self._build_chat_panel())
        workspace.setSizes([250, 830, 370])
        root_layout.addWidget(workspace, 1)
        self.setCentralWidget(root)

        self.status_label = QLabel("LOCAL WORKSPACE  /  READY")
        self.status_label.setObjectName("muted")
        self.status_label.setContentsMargins(18, 6, 18, 6)
        self.statusBar().addWidget(self.status_label, 1)

    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(76)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(22, 10, 22, 10)
        name = QLabel("I, MECHANIC")
        name.setObjectName("brand")
        layout.addWidget(name)
        stripe = QLabel("TELEMETRY INTELLIGENCE")
        stripe.setObjectName("lime")
        layout.addSpacing(20)
        layout.addWidget(stripe)
        layout.addStretch(1)
        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self._open_settings)
        layout.addWidget(settings_button)
        self.provider_box = QComboBox()
        for provider, label in PROVIDER_LABELS:
            self.provider_box.addItem(label, provider)
        self.provider_box.currentIndexChanged.connect(self._provider_changed)
        defaults = self.coach.provider_defaults(self.provider_box.currentData())
        self.model_edit = QLineEdit(defaults["model"])
        self.model_edit.setFixedWidth(190)
        self.model_edit.setPlaceholderText("Model identifier")
        self.url_edit = QLineEdit(defaults["base_url"])
        self.url_edit.setFixedWidth(230)
        self.url_edit.setPlaceholderText("Provider URL")
        refresh = QPushButton("↻  Models")
        self.refresh_button = refresh
        refresh.clicked.connect(self._refresh_models)
        layout.addWidget(self.provider_box)
        layout.addWidget(self.model_edit)
        layout.addWidget(self.url_edit)
        layout.addWidget(refresh)
        return bar

    def _build_rail(self):
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setMinimumWidth(220)
        rail.setMaximumWidth(330)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(16, 20, 16, 18)
        layout.setSpacing(12)

        self._label(layout, "ACTIVE PROJECT", "eyebrow")
        self.project_box = QComboBox()
        self.project_box.setObjectName("railCombo")
        self.project_box.currentIndexChanged.connect(self._project_changed)
        layout.addWidget(self.project_box)
        project_actions = QHBoxLayout()
        new_project = QPushButton("＋  New")
        new_project.clicked.connect(self._new_project)
        edit_project = QPushButton("Edit")
        edit_project.clicked.connect(self._edit_project)
        project_actions.addWidget(new_project)
        project_actions.addWidget(edit_project)
        layout.addLayout(project_actions)
        self.project_identity_label = QLabel("Choose a project")
        self.project_identity_label.setWordWrap(True)
        self.project_identity_label.setObjectName("muted")
        layout.addWidget(self.project_identity_label)

        self._label(layout, "SESSION TIMELINE", "eyebrow")
        self.session_list = QListWidget()
        self.session_list.setObjectName("sessions")
        self.session_list.currentRowChanged.connect(self._session_changed)
        layout.addWidget(self.session_list, 1)
        self._label(layout, "DRIVER NOTES", "eyebrow")
        self.feedback_edit = QPlainTextEdit()
        self.feedback_edit.setPlaceholderText("Where in the corner? What does the car do? How repeatable is it?")
        self.feedback_edit.setFixedHeight(118)
        layout.addWidget(self.feedback_edit)
        self.file_label = QLabel("No telemetry file selected")
        self.file_label.setWordWrap(True)
        self.file_label.setObjectName("muted")
        layout.addWidget(self.file_label)
        file_actions = QHBoxLayout()
        browse = QPushButton("Select .ld")
        browse.clicked.connect(self._choose_file)
        file_actions.addWidget(browse)
        self.ask_ai_button = QPushButton("AI enabled")
        self.ask_ai_button.setCheckable(True)
        self.ask_ai_button.setChecked(True)
        self.ask_ai_button.clicked.connect(self._toggle_ai_label)
        file_actions.addWidget(self.ask_ai_button)
        layout.addLayout(file_actions)
        self.analyze_button = QPushButton("ANALYZE SESSION  →")
        self.analyze_button.setObjectName("primary")
        self.analyze_button.clicked.connect(self._analyze)
        layout.addWidget(self.analyze_button)
        return rail

    def _build_main_area(self):
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(22, 20, 18, 18)
        layout.setSpacing(15)

        header = QHBoxLayout()
        title_stack = QVBoxLayout()
        self.eyebrow = QLabel("PROJECT / SESSION OVERVIEW")
        self.eyebrow.setObjectName("eyebrow")
        self.hero = QLabel("Set up your next run")
        self.hero.setObjectName("hero")
        self.session_meta = QLabel("Choose a project, add feedback, then analyze a telemetry file.")
        self.session_meta.setObjectName("muted")
        title_stack.addWidget(self.eyebrow)
        title_stack.addWidget(self.hero)
        title_stack.addWidget(self.session_meta)
        header.addLayout(title_stack, 1)
        self.quality_badge = QLabel("NO SESSION")
        self.quality_badge.setObjectName("coral")
        header.addWidget(self.quality_badge, 0, Qt.AlignTop)
        layout.addLayout(header)

        self.metric_row = QHBoxLayout()
        self.metric_labels = {}
        for key, label in (("time", "DRIVING WINDOW"), ("speed", "AVG / PEAK SPEED"), ("tyres", "TYRE PRESSURE"), ("confidence", "DATA CONFIDENCE")):
            panel = QFrame()
            panel.setObjectName("surface")
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(14, 10, 14, 10)
            self._label(panel_layout, label, "eyebrow")
            value = QLabel("—")
            value.setObjectName("metric")
            panel_layout.addWidget(value)
            self.metric_labels[key] = value
            self.metric_row.addWidget(panel)
        layout.addLayout(self.metric_row)

        self.tabs = QTabWidget()
        self.overview_page = self._build_overview_page()
        self.telemetry_page = self._build_text_page("Telemetry detail", "Waiting for a telemetry analysis.")
        self.assessment_page = self._build_text_page("Engineer report", "Setup recommendations will appear here.")
        self.tabs.addTab(self.overview_page, "Overview")
        self.tabs.addTab(self.telemetry_page, "Telemetry")
        self.tabs.addTab(self.assessment_page, "Engineer report")
        layout.addWidget(self.tabs, 1)
        return area

    def _build_overview_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        split = QSplitter(Qt.Vertical)
        top = QSplitter(Qt.Horizontal)
        self.issue_box = self._text_panel("SIGNALS TO WATCH", "No session assessment yet.")
        self.setup_box = self._text_panel("SETUP TEST PLAN", "Analyze a session to get a conservative next-step plan.")
        top.addWidget(self.issue_box)
        top.addWidget(self.setup_box)
        top.setSizes([1, 1])
        self.summary_box = self._text_panel("ENGINEER'S READ", "Your project summary and recent findings will appear here.")
        split.addWidget(top)
        split.addWidget(self.summary_box)
        split.setSizes([450, 210])
        layout.addWidget(split)
        return page

    def _build_chat_panel(self):
        panel = QFrame()
        panel.setObjectName("surface")
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(520)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(10)
        self._label(layout, "RACE ENGINEER / LIVE THREAD", "eyebrow")
        title = QLabel("Keep the conversation going")
        title.setStyleSheet("font-size: 15pt; font-weight: 700;")
        layout.addWidget(title)
        self.chat_log = QPlainTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setPlaceholderText("Project notes and follow-up questions will stay together here.")
        layout.addWidget(self.chat_log, 1)
        self.chat_entry = QPlainTextEdit()
        self.chat_entry.setPlaceholderText("Ask about this setup, the last run, or what to test next...")
        self.chat_entry.setFixedHeight(92)
        layout.addWidget(self.chat_entry)
        send = QPushButton("SEND TO ENGINEER  ↗")
        send.setObjectName("darkAction")
        self.send_button = send
        send.clicked.connect(self._send_chat)
        layout.addWidget(send)
        return panel

    def _build_text_page(self, title, placeholder):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        self._label(layout, title.upper(), "eyebrow")
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlaceholderText(placeholder)
        view.setFont(QFont("Consolas", 10))
        layout.addWidget(view, 1)
        if title == "Telemetry detail":
            self.telemetry_view = view
        else:
            self.assessment_view = view
        return page

    def _text_panel(self, heading, placeholder):
        panel = QFrame()
        panel.setObjectName("subsurface")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        self._label(layout, heading, "eyebrow")
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlaceholderText(placeholder)
        view.setFrameShape(QFrame.NoFrame)
        view.setStyleSheet("background: transparent; border: 0; padding: 0;")
        layout.addWidget(view, 1)
        if heading == "SIGNALS TO WATCH":
            self.issue_view = view
        elif heading == "SETUP TEST PLAN":
            self.setup_view = view
        else:
            self.summary_view = view
        return panel

    @staticmethod
    def _label(layout, text, name=None):
        label = QLabel(text)
        if name:
            label.setObjectName(name)
        layout.addWidget(label)
        return label

    def _load_projects(self):
        self.projects = self.repository.list_projects()
        if not self.projects:
            project = self.repository.create_project("ACC setup workspace", game="Assetto Corsa Competizione")
            self.projects = [project]
        self.project_box.blockSignals(True)
        self.project_box.clear()
        for project in self.projects:
            self.project_box.addItem(project["name"], project["id"])
        self.project_box.blockSignals(False)
        self.project_box.setCurrentIndex(0)
        self._activate_project(self.projects[0])

    def _activate_project(self, project):
        self.project_id = project["id"]
        identity = "  /  ".join(value for value in (project["game"], project["car"], project["track"]) if value)
        self.project_identity_label.setText(identity or "Set game, car and track in project details")
        self.hero.setText(project["name"])
        self.eyebrow.setText("PROJECT / " + (project["game"] or "RACE ENGINEERING").upper())
        self._load_project_history()

    def _project_changed(self, index):
        if index >= 0:
            project_id = self.project_box.itemData(index)
            project = next((item for item in self.projects if item["id"] == project_id), None)
            if project:
                self._activate_project(project)

    def _load_project_history(self):
        self.sessions = self.repository.list_sessions(self.project_id, limit=50)
        self.session_list.blockSignals(True)
        self.session_list.clear()
        for session in self.sessions:
            timestamp = session["created_at"].replace("T", " ")[:16]
            filename = Path(session["telemetry_path"]).name
            self.session_list.addItem(f"{timestamp}\n{session['status'].replace('_', ' ').upper()}  ·  {filename}")
        self.session_list.blockSignals(False)
        if self.sessions:
            self.session_list.setCurrentRow(0)
            self._show_session(self.sessions[0])
        else:
            self.current_session_id = None
            self.file_label.setText("No telemetry file selected")
            self.session_meta.setText("No sessions yet  ·  Import a MoTeC .ld file to begin")
        messages = self.repository.list_messages(self.project_id)
        lines = []
        for message in messages:
            speaker = "YOU" if message["role"] == "user" else "ENGINEER"
            lines.append(f"{speaker}\n{message['content']}")
        self.chat_log.setPlainText("\n\n".join(lines))

    def _show_session(self, session):
        self.current_session_id = session["id"]
        filename = Path(session["telemetry_path"]).name
        self.file_label.setText(filename)
        self.feedback_edit.setPlainText(session["feedback"])
        timestamp = session["created_at"].replace("T", " ")[:16]
        self.session_meta.setText(f"{timestamp}  ·  {filename}  ·  {session['status'].replace('_', ' ').title()}")
        brief = session.get("brief_json") or {}
        self._render_brief(brief)
        assessment = session.get("assessment_json") or {}
        self._render_assessment(assessment)

    def _session_changed(self, row):
        if 0 <= row < len(self.sessions):
            self._show_session(self.sessions[row])

    def _render_brief(self, brief):
        if not brief:
            self.metric_labels["time"].setText("—")
            self.metric_labels["speed"].setText("—")
            self.metric_labels["tyres"].setText("—")
            self.metric_labels["confidence"].setText("—")
            self.telemetry_view.setPlainText("No telemetry brief is stored for this session.")
            return
        quality = brief.get("data_quality", {})
        self.metric_labels["time"].setText(f"{brief.get('driving_time_s', '—')} s")
        self.metric_labels["speed"].setText(f"{brief.get('speed_kmh_avg', '—')} / {brief.get('speed_kmh_max', '—')} km/h")
        tyres = brief.get("tyres", {})
        pressure_values = [value.get("press_psi_mean") for value in tyres.values() if value.get("press_psi_mean") is not None]
        self.metric_labels["tyres"].setText(f"{sum(pressure_values) / len(pressure_values):.1f} psi avg" if pressure_values else "—")
        confidence = quality.get("confidence", "unknown").upper()
        self.metric_labels["confidence"].setText(confidence)
        self.quality_badge.setText("DATA " + confidence)
        self.quality_badge.setObjectName("lime" if confidence in {"PROVISIONAL", "HIGH"} else "coral")
        self.telemetry_view.setPlainText(json.dumps(brief, indent=2, ensure_ascii=False))
        tyres_lines = ["PRESSURES / TYRE TEMPS"]
        for corner, values in tyres.items():
            tyres_lines.append(f"{corner:<4}  {values.get('press_psi_mean', '—'):>5} psi     {values.get('temp_c_mean', '—'):>5} °C")
        inputs = brief.get("inputs", {})
        if inputs:
            tyres_lines.extend(("", "DRIVER INPUTS"))
            tyres_lines.extend(f"{key.replace('_', ' ').title():<30} {value}" for key, value in inputs.items())
        self.summary_view.setPlainText("\n".join(tyres_lines))

    def _render_assessment(self, assessment):
        if not assessment:
            self.issue_view.setPlainText("No issues recorded for this session.")
            self.setup_view.setPlainText("Analysis recommendations will appear here.")
            self.assessment_view.setPlainText("No engineer assessment is stored for this session.")
            return
        summary = assessment.get("session_summary", "No summary returned.")
        issues = assessment.get("issues_found", [])
        changes = assessment.get("setup_changes", [])
        issue_lines = [summary, ""]
        for issue in issues:
            issue_lines.append("• " + issue.get("issue", "Unspecified issue"))
            issue_lines.append("  Evidence: " + issue.get("telemetry_evidence", "Not provided"))
        setup_lines = []
        for index, change in enumerate(changes, 1):
            setup_lines.extend((
                f"{index:02d}  {change.get('parameter', 'Parameter')}  /  {change.get('change_direction', 'Review')} {change.get('magnitude_hint', '')}",
                "     " + change.get("addresses_symptom", ""),
                "     WHY  " + change.get("reasoning", ""),
                "     NEXT " + change.get("test_next", ""),
                "",
            ))
        self.issue_view.setPlainText("\n".join(issue_lines).strip())
        self.setup_view.setPlainText("\n".join(setup_lines).strip() or "No setup changes proposed.")
        self.assessment_view.setPlainText(json.dumps(assessment, indent=2, ensure_ascii=False))

    def _new_project(self):
        dialog = ProjectDialog(parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        project = self.repository.create_project(
            values["Project name"], values["Game"], values["Car"], values["Track"]
        )
        self.projects.insert(0, project)
        self._reload_project_choices(project["id"])

    def _edit_project(self):
        project = self.repository.get_project(self.project_id)
        if not project:
            return
        dialog = ProjectDialog(project, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        updated = self.repository.update_project(
            self.project_id,
            name=values["Project name"],
            game=values["Game"],
            car=values["Car"],
            track=values["Track"],
        )
        if updated:
            self.projects = [updated if item["id"] == updated["id"] else item for item in self.projects]
            self._reload_project_choices(updated["id"])

    def _reload_project_choices(self, selected_id):
        self.project_box.blockSignals(True)
        self.project_box.clear()
        for project in self.projects:
            self.project_box.addItem(project["name"], project["id"])
        index = self.project_box.findData(selected_id)
        self.project_box.setCurrentIndex(max(index, 0))
        self.project_box.blockSignals(False)
        project = next(item for item in self.projects if item["id"] == selected_id)
        self._activate_project(project)

    def _choose_file(self):
        selected, _kind = QFileDialog.getOpenFileName(self, "Choose MoTeC telemetry", "", "MoTeC telemetry (*.ld);;All files (*)")
        if selected:
            self.file_label.setText(selected)

    def _provider_changed(self, _index):
        defaults = self.coach.provider_defaults(self.provider_box.currentData())
        self.url_edit.setText(defaults["base_url"])
        self.model_edit.setText(defaults["model"])

    def _toggle_ai_label(self, checked):
        self.ask_ai_button.setText("AI enabled" if checked else "Brief only")

    def _refresh_models(self):
        self.status_label.setText("Checking provider models…")
        self._start_worker(lambda _progress: self.coach.list_models(self.provider_box.currentData(), self.url_edit.text()), self._models_loaded)

    def _models_loaded(self, models):
        if models:
            self.model_edit.setText(models[0])
            self.status_label.setText(f"CONNECTED  /  {len(models)} model(s) found")
        else:
            self.status_label.setText("Provider reachable, but no models returned")

    def _analyze(self):
        if self.worker and self.worker.isRunning():
            self.status_label.setText("PLEASE WAIT FOR THE CURRENT REQUEST TO FINISH")
            return
        path = self.file_label.text()
        if not path or path == "No telemetry file selected" or not Path(path).exists():
            QMessageBox.warning(self, "Telemetry required", "Choose an existing .ld telemetry file first.")
            return
        if not self.project_id:
            QMessageBox.warning(self, "Project required", "Create or select a project first.")
            return
        feedback = self.feedback_edit.toPlainText().strip()
        session = self.repository.create_session(self.project_id, path, feedback)
        self.analyze_button.setEnabled(False)
        self.status_label.setText("PARSING TELEMETRY…")

        def work(progress):
            return self.service.analyze_session(
                session["id"],
                model=self.model_edit.text(),
                base_url=self.url_edit.text(),
                provider=self.provider_box.currentData(),
                ask_ai=self.ask_ai_button.isChecked(),
                on_progress=progress,
            )

        self._start_worker(work, self._analysis_loaded, self._analysis_failed)

    def _start_worker(self, callback, on_success, on_failure=None):
        if self.worker and self.worker.isRunning():
            self.status_label.setText("PLEASE WAIT FOR THE CURRENT REQUEST TO FINISH")
            return False
        self.worker = TaskThread(callback)
        self.worker.progress.connect(self.status_label.setText)
        self.worker.succeeded.connect(on_success)
        self.worker.failed.connect(on_failure or self._show_failure)
        self.worker.finished.connect(self._worker_finished)
        self.analyze_button.setEnabled(False)
        self.send_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.worker.start()
        return True

    def _worker_finished(self):
        self.analyze_button.setEnabled(True)
        self.send_button.setEnabled(True)
        self.refresh_button.setEnabled(True)

    def _analysis_loaded(self, session):
        self.status_label.setText("ANALYSIS COMPLETE")
        self._load_project_history()
        self.tabs.setCurrentWidget(self.overview_page if session.get("assessment_json") else self.telemetry_page)

    def _analysis_failed(self, message):
        self.status_label.setText("ANALYSIS FAILED  /  SESSION SAVED")
        self._load_project_history()
        QMessageBox.warning(self, "Analysis failed", message)

    def _send_chat(self):
        content = self.chat_entry.toPlainText().strip()
        if not content or not self.project_id:
            return
        self.chat_entry.clear()
        self._append_chat("YOU", content)
        project_id = self.project_id
        session_id = self.current_session_id
        self._start_worker(
            lambda _progress: self.service.chat(
                project_id,
                content,
                model=self.model_edit.text(),
                base_url=self.url_edit.text(),
                provider=self.provider_box.currentData(),
                session_id=session_id,
            ),
            self._chat_loaded,
        )

    def _append_chat(self, speaker, content):
        prefix = self.chat_log.toPlainText()
        block = f"{speaker}\n{content}"
        self.chat_log.setPlainText((prefix + "\n\n" + block).strip())
        self.chat_log.verticalScrollBar().setValue(self.chat_log.verticalScrollBar().maximum())

    def _chat_loaded(self, result):
        response = result["response"]
        content = response.get("session_summary") or json.dumps(response, ensure_ascii=False)
        self._append_chat("ENGINEER", content)
        self.status_label.setText("PROJECT THREAD UPDATED")

    def _show_failure(self, message):
        self.status_label.setText("PROVIDER ERROR")
        QMessageBox.warning(self, "Race engineer request failed", message)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("I, Mechanic")
    window = RaceEngineerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
