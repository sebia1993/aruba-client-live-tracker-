"""Korean Qt dashboard. Workers never read or mutate Qt widgets."""
from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .models import Credentials, Device, Observation, Outcome, PollResult, utc_now

STYLE = """
QWidget { background: #0e1421; color: #dce5f4; font-family: 'Malgun Gothic', 'Noto Sans CJK KR', sans-serif; font-size: 13px; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #0e1421; }
QLabel#title { font-size: 23px; font-weight: 700; color: #f5f8ff; }
QLabel#subtitle { color: #91a1ba; }
QLabel#banner { background: #2e2a16; color: #ffdb80; padding: 9px; border-radius: 6px; }
QLabel#state { color: #57dec1; font-size: 17px; font-weight: 700; }
QGroupBox { border: 1px solid #2b3952; border-radius: 8px; margin-top: 18px; padding: 13px 10px 10px; background: #151e2e; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0px 6px; color: #a9bddb; }
QGroupBox QLabel { background: transparent; }
QLabel#value { font-size: 17px; color: #f0f5ff; font-weight: 600; }
QLineEdit, QComboBox, QSpinBox, QTextEdit { background: #101b2e; border: 1px solid #3b4e6c; border-radius: 5px; padding: 7px; selection-background-color: #266e7b; }
QPushButton { background: #25364f; border: 1px solid #405571; border-radius: 5px; padding: 8px 13px; }
QPushButton:hover { background: #344c6a; border-color: #6b8eac; }
QPushButton:disabled { color: #68778b; background: #192334; }
QPushButton#primary { background: #117b70; border-color: #2bbaa5; color: white; font-weight: 700; }
QTableWidget { background: #121c2c; alternate-background-color: #192539; gridline-color: #293952; border: 1px solid #2b3952; border-radius: 4px; }
QHeaderView::section { background: #223149; padding: 7px; border: none; color: #bfd0e8; }
QTabWidget::pane { border: 1px solid #2b3952; }
QTabBar::tab { background: #172339; padding: 9px 16px; }
QTabBar::tab:selected { background: #29415b; color: #6ce5cd; }
QScrollBar:vertical { background: #111b2a; width: 13px; }
QScrollBar::handle:vertical { background: #405571; min-height: 30px; border-radius: 6px; }
QToolTip { background: #25364f; color: white; border: 1px solid #6b8eac; padding: 8px; }
"""

TOOLTIPS = {
    "snr": "SNR: 무선 신호와 잡음의 차이입니다. 일반적으로 높을수록 안정적인 무선 통신에 유리합니다. 마지막 수신 패킷의 관측값일 수 있습니다.",
    "rssi": "RSSI: 수신 신호 세기(dBm)입니다. 실제 현재 신호 출처가 있을 때만 표시하며, ClientMatch 과거 측정값은 사용하지 않습니다.",
    "role": "Role: 사용자 인증 후 적용되는 접근 권한 정책입니다.",
    "tx_rate": "Tx Rate: AP에서 단말 방향의 무선 PHY 링크 속도입니다. 실제 다운로드 속도(Throughput)와 다릅니다.",
    "rx_rate": "Rx Rate: 단말에서 AP 방향의 무선 PHY 링크 속도입니다. 실제 업로드 속도(Throughput)와 다릅니다.",
    "retry_pct": "재전송률: 연속된 유효 관측의 패킷/재전송 카운터 차분으로 계산 가능한 경우만 표시합니다. AP 변경·누락·초기화 시 확인 불가입니다.",
    "auth_result": "인증 결과: 장비가 명시적으로 제공한 값만 표시합니다. Role만으로 인증 성공을 단정하지 않습니다.",
    "bssid": "BSSID: 현재 연결된 AP 무선 인터페이스의 MAC 주소입니다.",
}


def display_time(value: str | None) -> str:
    if not value:
        return "확인 불가"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(value)


def table(headers: list[str]) -> QTableWidget:
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setAlternatingRowColors(True)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


def add_row(widget: QTableWidget, values: list, maximum: int = 500) -> None:
    row = widget.rowCount()
    widget.insertRow(row)
    for column, value in enumerate(values):
        item = QTableWidgetItem(str(value) if value is not None else "확인 불가")
        item.setToolTip(item.text())
        widget.setItem(row, column, item)
    while widget.rowCount() > maximum:
        widget.removeRow(0)
    widget.scrollToBottom()


class SignalChart(QWidget):
    """Bounded two-panel chart; failures create real gaps instead of zeroes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples: deque = deque(maxlen=240)
        self.last_valid: str | None = None
        self.setMinimumHeight(220)
        self.setToolTip("위: SNR(dB), 아래: Tx/Rx PHY Rate(Mbps). 공백은 조회 실패 또는 유효 값 없음입니다. 가로축은 수집 시각입니다.")

    def append(self, observation: Observation | None, collected_at: str | None = None) -> None:
        timestamp = collected_at or (observation.collected_at if observation else utc_now())
        self.samples.append((timestamp, observation.snr if observation else None,
                             observation.tx_rate if observation else None,
                             observation.rx_rate if observation else None))
        if observation and any(v is not None for v in (observation.snr, observation.tx_rate, observation.rx_rate)):
            self.last_valid = observation.collected_at
        self.update()

    def clear(self):
        self.samples.clear()
        self.last_valid = None
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        panel_height = max(50.0, (height - 66) / 2)
        rows = list(self.samples)
        times = []
        for i, row in enumerate(rows):
            try:
                times.append(datetime.fromisoformat(row[0]).timestamp())
            except ValueError:
                times.append(float(i))
        duration = max(1.0, times[-1] - times[0]) if times else 1.0
        rate_values = [v for row in rows for v in row[2:4] if v is not None]
        rate_max = max(100.0, max(rate_values, default=100.0) * 1.12)
        for panel, maximum, columns in ((0, 60.0, (1,)), (1, rate_max, (2, 3))):
            rect = QRectF(54, 15 + panel * (panel_height + 16), max(10, width - 70), panel_height)
            painter.fillRect(rect, QColor("#0e1828"))
            painter.setPen(QPen(QColor("#2a3a51"), 1))
            for ratio in (0.0, 0.5, 1.0):
                y = rect.bottom() - ratio * rect.height()
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
                painter.setPen(QColor("#8297b6"))
                painter.drawText(QRectF(0, y - 9, 47, 20), Qt.AlignmentFlag.AlignRight, f"{maximum * ratio:.0f}")
                painter.setPen(QPen(QColor("#2a3a51"), 1))
            for column in columns:
                color = {1: "#52dec0", 2: "#62a7ff", 3: "#c099ff"}[column]
                painter.setPen(QPen(QColor(color), 2))
                path = QPainterPath()
                active = False
                for i, row in enumerate(rows):
                    value = row[column]
                    if value is None:
                        active = False
                        continue
                    x = rect.left() + ((times[i] - times[0]) / duration * rect.width() if len(rows) > 1 else 0)
                    y = rect.bottom() - min(max(float(value), 0), maximum) / maximum * rect.height()
                    if active:
                        path.lineTo(x, y)
                    else:
                        path.moveTo(x, y)
                    painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
                    active = True
                painter.drawPath(path)
            painter.setPen(QColor("#b0c1da"))
            painter.drawText(QPointF(rect.left() + 8, rect.top() + 15), "SNR · dB" if panel == 0 else "Tx / Rx PHY Rate · Mbps")
        painter.setPen(QColor("#8ea2c2"))
        if rows:
            painter.drawText(QPointF(54, height - 12), display_time(rows[0][0]))
            painter.drawText(QRectF(width - 180, height - 28, 160, 23), Qt.AlignmentFlag.AlignRight, display_time(rows[-1][0]))
        else:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "추적을 시작하면 시간별 관측값을 표시합니다")
        painter.end()


class DeviceDialog(QDialog):
    def __init__(self, parent=None, device: Device | None = None):
        super().__init__(parent)
        self.setWindowTitle("장비 등록 / 수정")
        self.resize(460, 360)
        layout = QFormLayout(self)
        self.name_edit = QLineEdit(device.name if device else "")
        self.host_edit = QLineEdit(device.host if device else "")
        self.port_edit = QSpinBox()
        self.port_edit.setRange(1, 65535)
        self.port_edit.setValue(device.port if device else 22)
        self.kind_edit = QComboBox()
        for label, value in (("MM Primary", "MM_PRIMARY"), ("MM Standby", "MM_STANDBY"), ("MD", "MD")):
            self.kind_edit.addItem(label, value)
        self.kind_edit.setCurrentIndex(self.kind_edit.findData(device.kind if device else "MD"))
        self.enabled_edit = QCheckBox("이 장비 사용")
        self.enabled_edit.setChecked(device.enabled if device else True)
        self.mappings_edit = QLineEdit(", ".join(device.mappings) if device else "")
        self.mappings_edit.setPlaceholderText("MM Current switch 값, 여러 값은 쉼표로 구분")
        for label, widget in (("장비 이름", self.name_edit), ("관리 IP", self.host_edit), ("SSH 포트", self.port_edit),
                              ("장비 유형", self.kind_edit), ("사용 여부", self.enabled_edit), ("담당 MD 매핑", self.mappings_edit)):
            layout.addRow(label, widget)
        note = QLabel("매핑은 MM이 반환하는 Current switch 값입니다. SSH 관리 IP와 다르면 MD에 매핑을 추가하세요.")
        note.setWordWrap(True)
        layout.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def device(self) -> Device:
        return Device(self.name_edit.text().strip(), self.host_edit.text().strip(), self.kind_edit.currentData(),
                      self.port_edit.value(), self.enabled_edit.isChecked(),
                      tuple(v.strip() for v in self.mappings_edit.text().split(",") if v.strip()))


class SettingsDialog(QDialog):
    def __init__(self, devices: list[Device], settings_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("장비 연결 설정")
        self.resize(900, 420)
        self.devices = list(devices)
        self.settings_path = settings_path
        layout = QVBoxLayout(self)
        notice = QLabel("SSH 계정과 비밀번호는 추적 시작 시 입력하며 파일에 저장하지 않습니다. 신뢰한 서버 키는 이 PC에 저장됩니다.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.grid = table(["장비 이름", "관리 IP", "포트", "유형", "사용", "담당 MD 매핑"])
        layout.addWidget(self.grid)
        controls = QHBoxLayout()
        for label, callback in (("등록", self.add_device), ("수정", self.edit_device), ("삭제", self.delete_device), ("저장 후 닫기", self.save)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.render()

    def render(self):
        self.grid.setRowCount(0)
        for device in self.devices:
            add_row(self.grid, [device.name, device.host, device.port, device.kind, "사용" if device.enabled else "중지", ", ".join(device.mappings)])

    def add_device(self):
        dialog = DeviceDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.devices.append(dialog.device())
            self.render()

    def edit_device(self):
        index = self.grid.currentRow()
        if index < 0:
            return
        dialog = DeviceDialog(self, self.devices[index])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.devices[index] = dialog.device()
            self.render()

    def delete_device(self):
        index = self.grid.currentRow()
        if index >= 0:
            self.devices.pop(index)
            self.render()

    def save(self):
        from .config import save_devices
        try:
            save_devices(self.settings_path, self.devices)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "설정 확인", str(exc))
            return
        self.accept()


class HistoryDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.setWindowTitle("추적 이력 · 로컬 보고서")
        self.resize(1000, 600)
        self.store = store
        layout = QVBoxLayout(self)
        self.grid = table(["번호", "검색 조건", "모드", "시작 시각", "종료 시각"])
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.grid)
        for session in store.sessions():
            add_row(self.grid, [session["id"], session["query"], "가상 데이터" if session["simulated"] else "장비 조회",
                                display_time(session["started_at"]), display_time(session["ended_at"])])
        period = QFormLayout()
        self.start_edit = QLineEdit()
        self.end_edit = QLineEdit()
        for edit in (self.start_edit, self.end_edit):
            edit.setPlaceholderText("전체 기간: 비워 두세요 · 예: 2026-10-27T00:00:00+00:00")
        period.addRow("기간 시작 (ISO 시각)", self.start_edit)
        period.addRow("기간 끝 (ISO 시각)", self.end_edit)
        layout.addLayout(period)
        controls = QHBoxLayout()
        for label, callback in (("선택 이력 보기", self.show_history), ("CSV 내보내기", lambda: self.export("csv")), ("HTML 내보내기", lambda: self.export("html"))):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)

    def selection(self):
        row = self.grid.currentRow()
        if row < 0:
            QMessageBox.information(self, "이력 선택", "조회하거나 내보낼 추적 이력을 선택하세요.")
            return None
        start, end = self.start_edit.text().strip() or None, self.end_edit.text().strip() or None
        try:
            for value in (start, end):
                if value:
                    parsed = datetime.fromisoformat(value)
                    if parsed.tzinfo is None:
                        raise ValueError
            if start and end and datetime.fromisoformat(start) > datetime.fromisoformat(end):
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "기간 확인", "시작/끝을 시간대가 포함된 ISO 시각으로 입력하세요. 시작은 끝보다 늦을 수 없습니다.")
            return None
        rows = sorted({index.row() for index in self.grid.selectionModel().selectedRows()}) or [row]
        return [int(self.grid.item(index, 0).text()) for index in rows], start, end

    def show_history(self):
        selected = self.selection()
        if not selected:
            return
        session, start, end = selected
        observations = [dict(row, session_id=sid) for sid in session for row in self.store.observations(sid, start, end)]
        events = [dict(row, session_id=sid) for sid in session for row in self.store.events(sid, start, end)]
        observations.sort(key=lambda row: row.get("collected_at", ""))
        events.sort(key=lambda row: row.get("at", ""))
        text = [f"관측 {len(observations)}건 · 이벤트 {len(events)}건", "시각은 저장된 ISO 시각이며 원인은 별도 검증이 필요합니다."]
        for row in observations[-200:]:
            text.append(f"세션 {row['session_id']} | {display_time(row.get('collected_at'))} | {row.get('outcome')} | AP {row.get('ap_name') or '확인 불가'} | SNR {row.get('snr', '확인 불가')} | {row.get('error', '')}")
        for event in events[-200:]:
            text.append(f"세션 {event['session_id']} | {display_time(event.get('at'))} | {event.get('message')} | 추정: {event.get('hypothesis')} | 추가 확인: {event.get('recommendation')}")
        self.preview.setPlainText("\n".join(text))

    def export(self, extension: str):
        selected = self.selection()
        if not selected:
            return
        path, _ = QFileDialog.getSaveFileName(self, "로컬 보고서 저장", f"ArubaClientReport.{extension}", f"{extension.upper()} (*.{extension})")
        if not path:
            return
        session, start, end = selected
        try:
            getattr(self.store, f"export_many_{extension}")(session, Path(path), start=start, end=end)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "내보내기 실패", str(exc))
            return
        QMessageBox.information(self, "내보내기 완료", "보고서를 선택한 PC 경로에 저장했습니다. 외부로 전송하지 않았습니다.")


class _Dashboard(QMainWindow):
    poll_applied = Signal(object)
    host_key_requested = Signal(object)

    def __init__(self, data_path: Path | None = None, demo: bool = True):
        super().__init__()
        from .config import data_dir, load_devices
        from .storage import HistoryStore
        from .tracker import Tracker
        self.data_path = data_path or data_dir()
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.data_path / "settings.json"
        settings_error = ""
        try:
            self.devices = load_devices(self.settings_path)
        except (ValueError, OSError):
            self.devices = []
            settings_error = "장비 설정을 읽을 수 없습니다. 원본 파일은 보존했습니다. 장비 연결 설정에서 내용을 확인해 저장하세요."
        self.store = HistoryStore(self.data_path / "history.sqlite3")
        self.tracker = Tracker()
        self.worker = None
        self.collector = None
        self.cancel_event = threading.Event()
        self.generation = 0
        self.active = False
        self.paused = False
        self.pending_start = False
        self.selection_pending = False
        self.pending_close = False
        self.session_id: int | None = None
        self.last_result: PollResult | None = None
        self.selected_mac: str | None = None
        self.target = None
        self.next_due: float | None = None
        self.fields: dict[str, QLabel] = {}
        self.setWindowTitle("Aruba Client Live Tracker")
        self.resize(1280, 900)
        self.setMinimumSize(760, 560)
        self.setStyleSheet(STYLE)
        self._build(demo)
        if settings_error:
            self.status_note.setText(settings_error)
        self.host_key_requested.connect(self._approve_key)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _build(self, demo):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.setCentralWidget(scroll)
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Aruba Client Live Tracker")
        title.setObjectName("title")
        title_box.addWidget(title)
        subtitle = QLabel("클라이언트 접속 · 무선 품질 · 로밍 관측")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        self.mm_label = QLabel("MM · 대기")
        self.md_label = QLabel("MD · 대기")
        header.addWidget(self.mm_label)
        header.addSpacing(12)
        header.addWidget(self.md_label)
        root.addLayout(header)
        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        root.addWidget(self.banner)
        controls = QGridLayout()
        self.mode = QComboBox()
        self.mode.addItem("데모 모드", True)
        self.mode.addItem("장비 연결 모드", False)
        self.mode.setCurrentIndex(0 if demo else 1)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.query = QLineEdit("192.0.2.100" if demo else "")
        self.query.setPlaceholderText("추적 대상 IPv4 또는 MAC 주소")
        self.query.returnPressed.connect(self.start_tracking)
        self.start_button = QPushButton("추적 시작 / 대상 전환")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.start_tracking)
        self.stop_button = QPushButton("추적 중지")
        self.stop_button.clicked.connect(self.stop_tracking)
        self.pause_button = QPushButton("일시 정지")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.refresh_button = QPushButton("즉시 새로고침")
        self.refresh_button.clicked.connect(self.refresh_now)
        self.interval = QComboBox()
        for seconds in (10, 15, 30, 60):
            self.interval.addItem(f"{seconds}초", seconds)
        self.interval.setCurrentIndex(1)
        self.interval.currentIndexChanged.connect(self._interval_changed)
        controls.addWidget(self.mode, 0, 0)
        controls.addWidget(self.query, 0, 1, 1, 3)
        controls.addWidget(self.start_button, 0, 4, 1, 2)
        controls.addWidget(self.stop_button, 1, 0)
        controls.addWidget(self.pause_button, 1, 1)
        controls.addWidget(self.refresh_button, 1, 2)
        controls.addWidget(QLabel("조회 주기"), 1, 3)
        controls.addWidget(self.interval, 1, 4)
        self.scenario = QComboBox()
        from .demo import SCENARIOS
        for key, label in SCENARIOS.items():
            self.scenario.addItem(label, key)
        if self.scenario.findData("cycle") >= 0:
            self.scenario.setCurrentIndex(self.scenario.findData("cycle"))
        self.scenario.setToolTip("가상 시나리오 변경은 다음 추적 시작부터 적용됩니다.")
        controls.addWidget(self.scenario, 1, 5)
        controls.setColumnStretch(1, 1)
        controls.setColumnStretch(2, 1)
        root.addLayout(controls)
        self.timing = QLabel("마지막 조회: 없음 · 다음 조회: 추적 대기")
        self.timing.setWordWrap(True)
        root.addWidget(self.timing)
        self.connection_state = QLabel("추적 대기")
        self.connection_state.setObjectName("state")
        root.addWidget(self.connection_state)
        self.status_note = QLabel("조회는 선택한 주기로 실행됩니다. 실제 주기는 장비 응답 시간에 따라 길어질 수 있습니다.")
        self.status_note.setWordWrap(True)
        root.addWidget(self.status_note)
        self._group(root, "현재 접속 · 인증 정보", [
            ("ip", "IP 주소"), ("mac", "MAC 주소"), ("ssid", "SSID"), ("ap_name", "현재 AP"),
            ("bssid", "BSSID"), ("md", "담당 MD"), ("role", "Role"), ("vlan", "VLAN"),
            ("auth_method", "인증 방식"), ("auth_result", "인증 결과"), ("channel", "채널 / 대역"), ("previous_ap", "이전 AP"),
        ], 4)
        self._group(root, "무선 품질 · PHY 링크 속도", [
            ("snr", "SNR · dB"), ("rssi", "RSSI · dBm"), ("tx_rate", "Tx PHY · Mbps"),
            ("rx_rate", "Rx PHY · Mbps"), ("retry_pct", "재전송률 · %"), ("retries", "재전송 횟수"),
            ("tx_packets", "송신 패킷"), ("rx_packets", "수신 패킷"),
        ], 4)
        graph_group = QGroupBox("시간별 관측 · SNR / Tx / Rx")
        graph_layout = QVBoxLayout(graph_group)
        legend = QLabel("● SNR (민트)     ● Tx PHY (파랑)     ● Rx PHY (보라)     |     PHY 속도는 실제 Throughput이 아닙니다")
        legend.setWordWrap(True)
        graph_layout.addWidget(legend)
        self.chart = SignalChart()
        graph_layout.addWidget(self.chart)
        self.valid_time = QLabel("마지막 유효 관측: 없음")
        graph_layout.addWidget(self.valid_time)
        root.addWidget(graph_group)
        tabs = QTabWidget()
        self.roaming_table = table(["감지 시각", "이전 AP → 현재 AP", "BSSID 전 → 후", "SNR 전 → 후", "Role 전 → 후", "관측 내용"])
        self.events_table = table(["발생 시각", "중요도", "관측 내용", "추정 원인", "추가 확인"])
        tabs.addTab(self.roaming_table, "로밍 · AP 변경 이력")
        tabs.addTab(self.events_table, "이벤트 기록")
        tabs.setMinimumHeight(240)
        root.addWidget(tabs)
        footer = QHBoxLayout()
        self.settings_button = QPushButton("장비 연결 설정")
        self.settings_button.clicked.connect(self.open_settings)
        footer.addWidget(self.settings_button)
        for label, callback in (("추적 이력 / 내보내기", self.open_history), ("CLI 원문 / 진단", self.open_diagnostics), ("사용자 도움말", self.open_help)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            footer.addWidget(button)
        footer.addStretch()
        font_button = QPushButton("글꼴 크기")
        font_button.clicked.connect(self.change_font_size)
        footer.addWidget(font_button)
        root.addLayout(footer)
        scroll.setWidget(central)
        self._mode_changed()
        self._button_state()

    def _group(self, root, title, entries, columns):
        group = QGroupBox(title)
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        for i, (key, label) in enumerate(entries):
            layout = QVBoxLayout()
            heading = QLabel(label)
            heading.setObjectName("subtitle")
            value = QLabel("확인 불가")
            value.setObjectName("value")
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if key in TOOLTIPS:
                value.setToolTip(TOOLTIPS[key])
                heading.setToolTip(TOOLTIPS[key])
            layout.addWidget(heading)
            layout.addWidget(value)
            self.fields[key] = value
            grid.addLayout(layout, i // columns, i % columns)
            grid.setColumnStretch(i % columns, 1)
        root.addWidget(group)

    def _mode_changed(self):
        demo = self.mode.currentData()
        if demo and hasattr(self, "query") and not self.query.text().strip():
            self.query.setText("192.0.2.100")
        self.banner.setText("데모 모드 · 모든 주소·SSID·이벤트는 가상 데이터입니다. SSH 연결을 사용하지 않습니다." if demo else
                            "장비 연결 모드 · 조회 전용 SSH · 수집 데이터는 이 PC에 저장됩니다.")
        if hasattr(self, "scenario"):
            self.scenario.setEnabled(bool(demo) and not self.active)

    def _button_state(self):
        self.stop_button.setEnabled(self.active or self.worker is not None)
        self.pause_button.setEnabled(self.active)
        self.refresh_button.setEnabled(self.active and self.worker is None and not self.selection_pending)
        self.settings_button.setEnabled(not self.active and self.worker is None and not self.selection_pending)
        self.mode.setEnabled(not self.active and self.worker is None and not self.selection_pending)
        self.scenario.setEnabled(bool(self.mode.currentData()) and not self.active)
        self.pause_button.setText("추적 재개" if self.paused else "일시 정지")

    def _credentials(self) -> Credentials | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("SSH 계정 입력 · 이번 실행에서만 사용")
        layout = QFormLayout(dialog)
        username = QLineEdit()
        password = QLineEdit()
        password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("사용자 이름", username)
        layout.addRow("비밀번호", password)
        layout.addRow(QLabel("계정과 비밀번호는 설정 파일이나 로그에 저장하지 않습니다."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("연결")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        if not username.text().strip() or not password.text():
            QMessageBox.warning(self, "계정 확인", "SSH 사용자 이름과 비밀번호를 입력하세요.")
            return None
        return Credentials(username.text().strip(), password.text())

    def _consume_result(self, result: PollResult):
        view = self.tracker.apply(result)
        result = view.result
        self.last_result = result
        if self.session_id is not None:
            stored_result = replace(result, observation=view.observation) if result.outcome == Outcome.OK else result
            self.store.save_poll(self.session_id, stored_result, view.events)
        self.mm_label.setText(f"MM · {result.mm_status}")
        self.md_label.setText(f"MD · {result.md_status}")
        self.connection_state.setText(f"{view.state}" + (" · 이전 조회값" if view.stale else ""))
        self.status_note.setText(result.error or "관측 사실을 표시합니다. 장애 원인은 인증·AP·무선 환경을 함께 확인해야 합니다.")
        observation = view.observation
        if observation:
            for key, label in self.fields.items():
                value = view.previous_ap if key == "previous_ap" else getattr(observation, key, None)
                if key == "channel" and observation.band:
                    value = f"{observation.channel or '확인 불가'} / {observation.band}"
                text = "확인 불가" if value is None else f"{value:g}" if isinstance(value, float) else str(value)
                if "이전 조회값" in observation.field_status.get(key, ""):
                    text += "\n이전 조회값"
                status = observation.field_status.get(key, "")
                if value is None and status and status != "정상":
                    text += "\n" + status[:80]
                label.setText(text)
                tooltip = TOOLTIPS.get(key, "")
                if key in observation.field_status:
                    tooltip += f"\n수집 상태: {observation.field_status[key]}"
                if key in observation.evidence:
                    tooltip += f"\n수집 근거: {observation.evidence[key]}"
                label.setToolTip(tooltip)
        self.chart.append(result.observation if result.outcome == Outcome.OK else None, result.collected_at)
        self.valid_time.setText(f"마지막 정상 조회: {display_time(view.last_success)} · 그래프 마지막 유효 관측: {display_time(self.chart.last_valid)} · 연결 상태 변경: {display_time(view.last_change)}")
        for event in view.events:
            add_row(self.events_table, [display_time(event.at), event.severity, event.message, event.hypothesis, event.recommendation])
            if event.kind in {"roam", "reconnected", "md_changed"}:
                facts = event.facts
                def transition(before, after):
                    return f"{facts.get(before) if facts.get(before) is not None else '확인 불가'} → {facts.get(after) if facts.get(after) is not None else '확인 불가'}"
                add_row(self.roaming_table, [display_time(event.at), transition("previous_ap", "new_ap"),
                    transition("previous_bssid", "new_bssid"), transition("snr_before", "snr_after"),
                    transition("role_before", "role_after"), event.message])
        self.poll_applied.emit(result)

    def open_settings(self):
        dialog = SettingsDialog(self.devices, self.settings_path, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.devices = dialog.devices

    def open_history(self):
        HistoryDialog(self.store, self).exec()

    def open_diagnostics(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("CLI 원문 및 수집 진단 · 이 PC에서만 표시")
        dialog.resize(950, 650)
        layout = QVBoxLayout(dialog)
        note = QLabel("원문에는 장비·사용자 정보가 포함될 수 있습니다. 공개 저장소에 게시하지 마세요. '지원하지 않음'과 '조회 실패'는 연결 해제를 의미하지 않습니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 10))
        if self.last_result:
            raw = self.last_result.raw
            sections = [f"수집 시각: {self.last_result.collected_at}\n상태: {self.last_result.outcome}\n안내: {self.last_result.error}"]
            if self.last_result.observation:
                sections.append("항목별 수집 상태 / 근거\n" + json.dumps({"상태": self.last_result.observation.field_status, "근거": self.last_result.observation.evidence}, ensure_ascii=False, indent=2))
            sections.extend(f"조회: {command}\n{output}" for command, output in raw.items())
            text.setPlainText("\n\n".join(sections) if raw or sections else "CLI 원문이 없습니다.")
        else:
            text.setPlainText("추적을 시작하면 최근 조회의 CLI 원문과 진단이 표시됩니다.")
        layout.addWidget(text)
        dialog.exec()

    def open_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("초급 엔지니어 사용 도움말")
        dialog.resize(760, 580)
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText("사용 순서\n\n1. 처음에는 데모 모드를 선택하고 추적 시작을 누르세요. 모든 데이터는 가상입니다.\n2. 실제 조회는 장비 연결 설정에서 MM Primary·Standby와 MD를 등록하세요. Current switch와 관리 IP가 다르면 매핑을 등록합니다.\n3. 장비 연결 모드를 선택하고 IPv4 또는 MAC을 입력하세요. SSH 계정은 실행 중에만 사용합니다.\n4. 최초 접속 시 서버 키 SHA-256 지문을 별도 신뢰 경로로 확인하세요. 변경된 키는 자동 승인하지 않습니다.\n5. 다중 모니터링에서는 최대 10개 대상을 등록하거나 여러 줄로 붙여넣습니다. 목록의 행을 선택하면 해당 대상의 기존 상세와 그래프가 표시됩니다. 선택 대상 또는 전체 시작·중지·일시 정지·재개·새로고침을 사용할 수 있습니다.\n6. 여러 클라이언트가 검색된 행은 검색 결과 선택 버튼을 눌러 직접 결정하세요. 다른 대상은 계속 수집합니다.\n7. 데모/장비 연결 모드와 단일/다중 추적, 시나리오, 장비 설정은 전체 중지 후 변경하세요. 이력에서 여러 세션을 선택해 통합 보고서를 저장할 수 있습니다.\n\n지표 읽기\n\nSNR은 신호와 잡음의 차이입니다. 마지막 패킷 시각의 값일 수 있으며 높은 값이 일반적으로 유리합니다.\nRSSI는 실제 신호 출처가 있을 때만 표시합니다. ClientMatch 과거값은 현재 RSSI로 사용하지 않습니다.\nTx/Rx PHY Rate는 무선 링크 속도이며 실제 다운로드/업로드 속도가 아닙니다.\nRole은 인증 이후 적용되는 접근 정책입니다. Role만으로 인증 성공이나 장애 원인을 단정하지 않습니다.\n\n실패와 연결 해제\n\n조회 실패 시 이전 조회값을 보존합니다. 그래프의 공백은 유효 관측이 없다는 뜻입니다. SSH 실패는 로밍·연결 해제로 기록하지 않습니다. 여러 정상 관측의 단말 부재로 연결 해제를 판단합니다.\n\n이력과 개인정보\n\nSQLite와 설정, 신뢰한 서버 키는 사용자별 로컬 데이터 폴더에 저장합니다. 추적 이력에서 기간을 선택해 CSV/HTML로 내보낼 수 있습니다. 원문·보고서에는 사용자 정보가 포함될 수 있으므로 공개 GitHub에 업로드하지 마세요. 외부 분석/자동 업로드 기능은 없습니다.\n\n검증 범위\n\nArubaOS CLI 지원과 권한, 출력 형식은 버전·실행 위치에 따라 다릅니다. 자동 테스트는 가상 출력 기반이며 실제 ArubaOS 8.10 장비 검증은 사용자가 수행해야 합니다.")
        layout.addWidget(text)
        dialog.exec()

    def change_font_size(self):
        size, ok = QInputDialog.getInt(self, "글꼴 크기", "기본 글꼴 크기 (픽셀)", 13, 11, 20)
        if ok:
            self.setStyleSheet(STYLE.replace("font-size: 13px", f"font-size: {size}px"))

# The public dashboard coordinates both single and multiple target monitoring.
def __getattr__(name):
    if name == 'MainWindow':
        from .ui_monitoring import MainWindow
        return MainWindow
    raise AttributeError(name)
