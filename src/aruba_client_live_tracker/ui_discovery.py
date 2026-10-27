"""MM discovery UI; background workers own services and never access Qt objects."""
from __future__ import annotations

import queue
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from .models import DIAGNOSTIC_STAGE_LABELS, Diagnostic
from .ui import add_row, fit_dialog_to_screen, table


def diagnostic_text(diagnostics):
    return '\n'.join(
        f"[{DIAGNOSTIC_STAGE_LABELS.get(d.stage, d.stage)} / {d.code}] "
        f"{d.device_name} {d.endpoint} {d.command}\n{d.message}" for d in diagnostics)


class DiscoveryDialog(QDialog):
    def __init__(self, seed, existing, credentials, known_hosts, parent=None, service_factory=None, initial_devices=None):
        super().__init__(parent)
        from .discovery import DiscoveryService
        self.setWindowTitle('MM에서 장비 찾기 · 선택 장비 검사 / 등록')
        self.resize(1120, 650)
        self.seed = seed
        self.existing = list(existing)
        self.devices = []
        self.candidates = []
        self.diagnostics = []
        self._operation_history = []
        self._probe_count = 0
        self._discovery_errors = False
        self._probed = False
        self._busy = False
        self._closed = False
        self._generation = 0
        self._cancel = threading.Event()
        self._results = queue.SimpleQueue()
        self._credentials = credentials
        self._known_hosts = known_hosts
        self._service_factory = service_factory or DiscoveryService
        self._service_holder = [None]
        self._service_lock = threading.Lock()
        layout = QVBoxLayout(self)
        self.notice = QLabel('MM의 장비 목록을 가져옵니다. 기본 선택은 입력한 MM이며, 선택한 장비만 추가로 연결해 역할을 검사합니다.')
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.all_selected = QCheckBox('전체 선택')
        self.all_selected.toggled.connect(self.select_all)
        layout.addWidget(self.all_selected)
        self.grid = table(['선택', '장비 이름', '관리 IP / SSH 포트', '역할', '모델', '버전', '검사 상태'])
        self.grid.itemChanged.connect(self._selection_changed)
        layout.addWidget(self.grid, 1)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)
        self.details.setPlaceholderText('발견·역할 판별·설정 병합 진단을 표시합니다.')
        layout.addWidget(self.details)
        controls = QHBoxLayout()
        self.probe_button = QPushButton('선택 장비 검사')
        self.probe_button.clicked.connect(self.probe_selected)
        self.register_button = QPushButton('선택 장비 등록')
        self.register_button.setObjectName('primary')
        self.register_button.clicked.connect(self.register_selected)
        self.cancel_button = QPushButton('취소 / 닫기')
        self.cancel_button.clicked.connect(self.reject)
        for button in (self.probe_button, self.register_button, self.cancel_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._drain)
        self.timer.start()
        if initial_devices is None:
            self._launch('discover', seed)
        else:
            self.candidates = list(initial_devices)
            self._render({(d.host, d.port) for d in initial_devices})
            self.probe_selected()
        fit_dialog_to_screen(self, 1120, 650)

    def _launch(self, operation, payload):
        if self._closed or self._busy:
            return
        self._busy = True
        self._probed = False
        self._generation += 1
        generation, cancel, results = self._generation, self._cancel, self._results
        factory, credentials, known_hosts = self._service_factory, self._credentials, self._known_hosts
        holder, service_lock = self._service_holder, self._service_lock
        if operation == 'probe':
            self._probe_count += 1
        label = 'MM 목록 조회' if operation == 'discover' else f'선택 장비 검사 {self._probe_count}회'
        self._operation_history.append({'label': label, 'summary': '진행 중', 'diagnostics': []})
        self._render_operation_history()
        self._buttons()
        self._set_notice(f'{label} 진행 중…')
        # Capture plain Python data only; worker never retains or touches widgets.
        def work():
            service = None
            try:
                service = factory(credentials, known_hosts)
                with service_lock:
                    holder[0] = service
                if cancel.is_set():
                    return
                result = getattr(service, operation)(payload, cancel=cancel)
                if not cancel.is_set():
                    results.put((generation, operation, result))
            except Exception:
                if not cancel.is_set():
                    results.put((generation, 'error', Diagnostic('discovery', 'DISCOVERY_FAILED',
                        '장비 조회를 완료하지 못했습니다. 연결 주소, 계정 권한과 장비 CLI 지원을 확인하세요.')))
            finally:
                try:
                    if service is not None:
                        service.close()
                finally:
                    with service_lock:
                        if holder[0] is service:
                            holder[0] = None
        threading.Thread(target=work, name=f'discovery-{operation}', daemon=True).start()

    @staticmethod
    def _diagnostic_summary(diagnostics):
        if not diagnostics:
            return '진단 없음'
        counts = [(severity, sum(d.severity == severity for d in diagnostics))
                  for severity in ('오류', '주의')]
        counts.append(('안내', len(diagnostics) - sum(count for _, count in counts)))
        return ' · '.join(f'{severity} {count}건' for severity, count in counts if count)

    def _set_notice(self, text):
        if self._discovery_errors and self._operation_history[-1]['label'] != 'MM 목록 조회':
            text += ' 이전 MM 목록 조회 오류가 남아 있습니다. 아래 이전 작업 진단을 확인하세요.'
        self.notice.setText(text)

    def _render_operation_history(self):
        sections = []
        for index in range(len(self._operation_history)-1, -1, -1):
            record = self._operation_history[index]
            scope = '현재 작업' if index == len(self._operation_history)-1 else '이전 작업'
            sections.append(f"{scope} · {record['label']} · {record['summary']}\n" +
                            (diagnostic_text(record['diagnostics']) or
                             ('결과 대기 중' if record['summary'] == '진행 중' else '추가 진단 없음')))
        self.details.setPlainText('\n\n'.join(sections))

    def _drain(self):
        while not self._results.empty():
            generation, operation, value = self._results.get()
            if generation != self._generation or self._closed:
                continue
            self._busy = False
            record = self._operation_history[-1]
            if operation == 'error':
                self.diagnostics.append(value)
                record['diagnostics'] = [value]
                record['summary'] = '실패'
                if record['label'] == 'MM 목록 조회':
                    self._discovery_errors = True
                self._set_notice(f"{record['label']} 실패 · 아래 현재 작업 진단을 확인하세요.")
            else:
                operation_diagnostics = list(value.diagnostics)
                self.diagnostics.extend(operation_diagnostics)
                if operation == 'discover':
                    self._discovery_errors = any(d.severity == '오류' for d in operation_diagnostics)
                    self.candidates = list(value.devices)
                    self._render({(self.seed.host, self.seed.port)})
                    self._set_notice(f'MM 목록 조회 완료 · {self._diagnostic_summary(operation_diagnostics)} · '
                        f'확인 가능한 후보 {len(self.candidates)}대. 검사할 장비를 선택하세요. 입력한 MM이 기본 선택됩니다.')
                else:
                    selected = {(d.host, d.port) for d in value.devices}
                    updates = {(d.host, d.port): d for d in value.devices}
                    self.candidates = [updates.get((d.host, d.port), d) for d in self.candidates]
                    self._render(selected)
                    self._probed = True
                    operation_diagnostics.extend(self._preview_merge())
                    unresolved = sum(d.kind == 'AUTO' for d in self.selected_devices())
                    self._set_notice(f"{record['label']} 완료 · {self._diagnostic_summary(operation_diagnostics)} · "
                        f'선택 {len(selected)}대 · 판별 불가 {unresolved}대. 진단 확인 후 등록하세요. 판별 불가는 추적에서 제외됩니다.')
                record['diagnostics'] = operation_diagnostics
                record['summary'] = '완료 · ' + self._diagnostic_summary(operation_diagnostics)
            self._render_operation_history()
            self._buttons()

    def _render(self, selected):
        self.grid.blockSignals(True)
        self.grid.setRowCount(0)
        for device in self.candidates:
            identity = device.identity
            add_row(self.grid, ['', device.name, f'{device.host}:{device.port}',
                ('판별 불가 (AUTO)' if device.kind == 'AUTO' else device.kind) +
                (f' · {identity.reported_role}' if identity and identity.reported_role else ''),
                identity.model if identity and identity.model else '확인 불가',
                identity.version if identity and identity.version else '확인 불가',
                '역할 판별 필요 · 추적 제외' if device.kind == 'AUTO' else '역할 확인'],
                maximum=max(1000, len(self.candidates)), scroll=False)
            item = self.grid.item(self.grid.rowCount()-1, 0)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if (device.host, device.port) in selected else Qt.CheckState.Unchecked)
        self.grid.blockSignals(False)

    def selected_devices(self):
        return [device for index, device in enumerate(self.candidates)
                if self.grid.item(index, 0).checkState() == Qt.CheckState.Checked]

    def select_all(self, checked):
        if self._busy:
            return
        for row in range(self.grid.rowCount()):
            self.grid.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _selection_changed(self, item):
        if item.column() == 0:
            self._probed = False
            self._buttons()

    def _buttons(self):
        selected = bool(self.selected_devices())
        self.grid.setEnabled(not self._busy)
        self.all_selected.setEnabled(not self._busy)
        self.probe_button.setEnabled(not self._busy and selected)
        self.register_button.setEnabled(not self._busy and self._probed and selected)

    def probe_selected(self):
        selected = self.selected_devices()
        if selected and not self._busy:
            self._launch('probe', selected)

    def _preview_merge(self):
        from .discovery import merge_discovered
        merged, diagnostics = merge_discovered(self.existing, self.selected_devices())
        self._merged = merged
        self.diagnostics.extend(diagnostics)
        return diagnostics

    def register_selected(self):
        if self._busy or not self._probed or not self.selected_devices():
            return
        self.devices = self._merged
        self.accept()

    def done(self, code):
        if not self._closed:
            self._closed = True
            self._generation += 1
            self._cancel.set()
            self.timer.stop()
            with self._service_lock:
                service = self._service_holder[0]
                self._service_holder[0] = None
            if service is not None:
                threading.Thread(target=service.close, name='discovery-close', daemon=True).start()
            self._credentials = None
        super().done(code)
