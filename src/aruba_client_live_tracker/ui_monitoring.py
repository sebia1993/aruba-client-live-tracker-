"""Main-thread multi-target controls and application-lifetime credential cache."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .ui import TOOLTIPS, _Dashboard, add_row, display_time, table


class MainWindow(_Dashboard):
    def __init__(self, data_path=None, demo=True, multi=False):
        self.coordinator = None
        self.selected_id = None
        self.pool = None
        self._credentials_value = None
        self._closed = False
        self._emitted_results = {}
        self._rendered_signature = None
        super().__init__(data_path=data_path, demo=demo)
        from .monitoring import MonitoringCoordinator
        self.coordinator = MonitoringCoordinator(self.store, self._collector_factory, interval=self.interval.currentData())
        root = self.centralWidget().widget().layout()
        controls = QHBoxLayout()
        self.monitor_kind = QComboBox()
        self.monitor_kind.addItem('단일 추적', False)
        self.monitor_kind.addItem('다중 모니터링 · 최대 10대', True)
        self.monitor_kind.setCurrentIndex(1 if multi else 0)
        self.monitor_kind.currentIndexChanged.connect(self._monitor_changed)
        controls.addWidget(self.monitor_kind)
        self.add_button = QPushButton('대상 추가')
        self.add_button.clicked.connect(self.add_target)
        controls.addWidget(self.add_button)
        self.paste_button = QPushButton('여러 줄 붙여넣기')
        self.paste_button.clicked.connect(self.paste_targets)
        controls.addWidget(self.paste_button)
        self.candidate_button = QPushButton('검색 결과 선택')
        self.candidate_button.clicked.connect(self.choose_candidate)
        controls.addWidget(self.candidate_button)
        self.remove_button = QPushButton('선택 대상 삭제')
        self.remove_button.clicked.connect(self.remove_selected)
        controls.addWidget(self.remove_button)
        root.insertLayout(3, controls)
        self.targets_table = table(['대상', '실행 상태', '연결 상태', 'IP', 'MAC', '현재 AP', '담당 MD', 'SNR', '마지막 정상 시각', '다음 조회 / 안내'])
        self.targets_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.targets_table.setMinimumHeight(355)
        self.targets_table.setMaximumHeight(355)
        self.targets_table.itemSelectionChanged.connect(self._selection_changed)
        root.insertWidget(4, self.targets_table)
        self.registration_errors = QLabel()
        self.registration_errors.setWordWrap(True)
        self.registration_errors.setTextFormat(Qt.TextFormat.PlainText)
        root.insertWidget(5, self.registration_errors)
        all_controls = QHBoxLayout()
        self.all_buttons = []
        for text, callback in [('전체 시작', self.start_all), ('전체 중지', self.stop_all),
            ('전체 일시 정지', self.pause_all), ('전체 재개', self.resume_all), ('전체 새로고침', self.refresh_all)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            all_controls.addWidget(button)
            self.all_buttons.append(button)
        root.insertLayout(6, all_controls)
        self._all_controls = all_controls
        self.timer.setInterval(100)
        # CLI and all device-supplied strings must never be interpreted as HTML.
        for label in self.findChildren(QLabel):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self._monitor_changed()
        self._button_state()

    def _collector_factory(self, context):
        if self.mode.currentData():
            from .demo import DemoCollector
            return DemoCollector(scenario=self.scenario.currentData())
        from .collector import LiveCollector
        return LiveCollector([d for d in self.devices if d.enabled and d.kind != "AUTO"], self._credentials_value, self.data_path / 'known_hosts',
                             command_runner=self.pool.for_owner(context.id))

    def _ensure_run(self):
        if self.mode.currentData():
            return True
        if self.pool is not None:
            return True
        if not any(device.enabled and device.kind != "AUTO" for device in self.devices):
            QMessageBox.warning(self, '장비 설정 필요', '장비 연결 설정에서 MM과 담당 MD를 등록하고 역할을 검사하세요. 판별 불가 (AUTO)는 추적에서 제외됩니다.')
            return False
        credentials = self._shared_credentials()
        if credentials is None:
            return False
        from .session_pool import SharedSessionPool
        self._credentials_value = credentials
        self.pool = SharedSessionPool(credentials, self.data_path / 'known_hosts')
        return True

    def _monitor_changed(self):
        if self.coordinator is None:
            return
        multi = bool(self.monitor_kind.currentData())
        self.targets_table.setVisible(multi)
        self.add_button.setVisible(multi)
        self.paste_button.setVisible(multi)
        self.remove_button.setVisible(multi)
        self.registration_errors.setVisible(multi)
        for button in self.all_buttons:
            button.setVisible(multi)
        self.start_button.setText('선택 대상 시작' if multi else '추적 시작 / 대상 전환')

    def add_many_targets(self, text):
        ids, errors = self.coordinator.add_many(text)
        self.registration_errors.setText('\n'.join(f'{line}행: {message}' for line, message in errors))
        if self.selected_id is None and ids:
            self.selected_id = ids[0]
        self._render_rows()
        self._render_selected()
        self._button_state()
        return ids, errors

    def add_target(self):
        return self.add_many_targets(self.query.text())

    def paste_targets(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('대상 여러 줄 등록 · 최대 10대')
        dialog.resize(540, 350)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('IPv4 또는 MAC 주소를 한 줄에 하나씩 입력하세요.'))
        text = QTextEdit()
        text.setAcceptRichText(False)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('등록')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.add_many_targets(text.toPlainText())

    def start_tracking(self):
        if self.coordinator is None:
            return
        if not self.monitor_kind.currentData():
            from .commands import parse_target
            try:
                target = parse_target(self.query.text())
            except ValueError as exc:
                QMessageBox.warning(self, '검색값 확인', str(exc))
                return
            existing = next((c for c in self.coordinator.contexts.values() if c.target == target), None)
            if existing is None:
                for identifier in list(self.coordinator.contexts):
                    self.coordinator.remove(identifier)
                self.selected_id = None
                ids, _ = self.add_many_targets(target.value)
                if not ids:
                    return
                self.selected_id = ids[0]
            else:
                self.selected_id = existing.id
        elif self.selected_id is None:
            ids, _ = self.add_target()
            if not ids:
                return
        if not self._ensure_run():
            return
        self._start_context(self.selected_id)
        self._tick()

    def _start_context(self, identifier):
        try:
            self.coordinator.start(identifier)
        except Exception:
            context = self.coordinator.contexts.get(identifier)
            if context:
                context.note = '추적 시작 실패: 장비 설정, 저장 공간과 접근 권한을 확인하세요. 다른 대상의 수집은 계속됩니다.'

    def stop_tracking(self, clear_pending=True):
        if self.coordinator is None:
            return
        if self.selected_id in self.coordinator.contexts:
            self.coordinator.stop(self.selected_id)
        self._tick()

    def start_all(self):
        if not self.coordinator.contexts or not self._ensure_run():
            return
        for identifier in list(self.coordinator.contexts):
            self._start_context(identifier)
        self._tick()

    def stop_all(self):
        if self.coordinator is None:
            return
        for identifier in list(self.coordinator.contexts):
            self.coordinator.stop(identifier)
        self._tick()

    def pause_all(self):
        for identifier in self.coordinator.contexts:
            self.coordinator.pause(identifier)
        self._tick()

    def resume_all(self):
        for identifier in self.coordinator.contexts:
            self.coordinator.resume(identifier)
        self._tick()

    def refresh_all(self):
        for identifier in self.coordinator.contexts:
            self.coordinator.refresh(identifier)
        self._tick()

    def toggle_pause(self):
        context = self.coordinator.contexts.get(self.selected_id)
        if context:
            (self.coordinator.resume if context.status == 'paused' else self.coordinator.pause)(context.id)
            self._tick()

    def refresh_now(self):
        if self.coordinator is None:
            return
        if self.selected_id in self.coordinator.contexts:
            self.coordinator.refresh(self.selected_id)
            self._tick()

    def remove_selected(self):
        if self.selected_id in self.coordinator.contexts:
            self.coordinator.remove(self.selected_id)
            self.selected_id = next(iter(self.coordinator.contexts), None)
            self._tick()
            self._render_selected()

    def _interval_changed(self):
        if self.coordinator is not None:
            self.coordinator.set_interval(self.interval.currentData())

    def _selection_changed(self):
        row = self.targets_table.currentRow()
        if row >= 0 and self.targets_table.item(row, 0):
            self.selected_id = self.targets_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            self._render_selected()
            self._button_state()

    def choose_candidate(self):
        context = self.coordinator.contexts.get(self.selected_id)
        if not context or not context.last_result or context.status != 'selection_required':
            return
        # This chooser is opened only by the affected row's explicit action.
        from PySide6.QtWidgets import QInputDialog
        candidates = context.last_result.candidates
        labels = [f'{c.ip} | {c.mac} | MD {c.current_switch}' for c in candidates]
        value, ok = QInputDialog.getItem(self, '클라이언트 선택', '추적할 클라이언트를 선택하세요.', labels, 0, False)
        if ok and value in labels and context.id in self.coordinator.contexts:
            self.coordinator.select_candidate(context.id, candidates[labels.index(value)].mac)
            self._tick()

    def _tick(self):
        if self.coordinator is None or self._closed:
            return
        changed = self.coordinator.tick()
        for identifier in set(self._emitted_results) - self.coordinator.contexts.keys():
            self._emitted_results.pop(identifier, None)
        self._render_rows()
        selected = self.coordinator.contexts.get(self.selected_id)
        signature = self._context_signature(selected)
        if signature != self._rendered_signature:
            self._render_selected()
        self._button_state()
        for identifier in changed:
            context = self.coordinator.contexts.get(identifier)
            if context and context.last_result and self._emitted_results.get(identifier) is not context.last_result:
                self._emitted_results[identifier] = context.last_result
                self.poll_applied.emit(context.last_result)
        if not self.coordinator.active and not self.coordinator.busy and self.pool is not None:
            self.pool.close()
            self.pool = None
        if self.pending_close and not self.coordinator.busy:
            self.close()

    def _render_rows(self):
        self.targets_table.blockSignals(True)
        self.targets_table.setRowCount(0)
        states = {'stopped':'중지', 'running':'실행 중', 'paused':'일시 정지',
                  'selection_required':'클라이언트 선택 필요', 'duplicate':'동일 MAC · 대기'}
        for row, context in enumerate(self.coordinator.contexts.values()):
            view, result = context.view, context.last_result
            observation = view.observation if view else None
            due = '조회 중' if context.in_flight else ('대기' if context.next_due is None else f'{max(0, context.next_due-time.monotonic()):.0f}초 후')
            note = context.note or (self._result_notice(result) if result else '')
            if note:
                due += ' · ' + note
            snr = observation.snr if observation else None
            if snr is not None and (view.stale or '이전 조회값' in observation.field_status.get('snr', '')):
                snr = f'{snr:g} · 이전값'
            add_row(self.targets_table, [context.target.value, states.get(context.status, context.status),
                view.state + (' · 이전값' if view.stale else '') if view else '대기',
                observation.ip if observation else None, observation.mac if observation else None,
                observation.ap_name if observation else None, observation.md if observation else None, snr,
                display_time(view.last_success) if view and view.last_success else '없음', due])
            self.targets_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, context.id)
            if context.id == self.selected_id:
                self.targets_table.selectRow(row)
        self.targets_table.blockSignals(False)

    @staticmethod
    def _context_signature(context):
        if context is None:
            return None
        return (context.id, context.status, context.in_flight, context.next_due, context.note,
                id(context.last_result), context.session_id)

    def _render_selected(self):
        context = self.coordinator.contexts.get(self.selected_id)
        self._rendered_signature = self._context_signature(context)
        self.last_result = context.last_result if context else None
        self.session_id = context.session_id if context else None
        self.collector = context.collector if context else None
        self.target = context.target if context else None
        self.tracker = context.tracker if context else self.tracker
        self.mm_label.setText('MM · 대기')
        self.md_label.setText('MD · 대기')
        self.status_note.setText('관측을 기다리는 대상입니다.')
        self.valid_time.setText('마지막 정상 조회: 없음 · 그래프 마지막 유효 관측: 없음 · 연결 상태 변경: 없음')
        self.chart.clear()
        self.events_table.setRowCount(0)
        self.roaming_table.setRowCount(0)
        for key, label in self.fields.items():
            label.setText('확인 불가')
            label.setToolTip(TOOLTIPS.get(key, ''))
        if not context:
            self.connection_state.setText('추적 대기')
            self.timing.setText('대상을 추가하거나 추적을 시작하세요.')
            return
        for observation, collected_at in context.samples:
            self.chart.append(observation, collected_at)
        view, result = context.view, context.last_result
        self.active = context.status != 'stopped'
        self.paused = context.status == 'paused'
        self.worker = context if context.in_flight else None
        self.next_due = context.next_due
        self.connection_state.setText(f'{context.target.value} · ' + (view.state + (' · 이전 조회값' if view.stale else '') if view else '추적 대기'))
        if context.status == 'stopped':
            self.connection_state.setText(context.target.value + ' · 추적 중지 · 마지막 관측 보존')
        elif context.status == 'paused':
            self.connection_state.setText(self.connection_state.text() + ' · 일시 정지')
        self.status_note.setText(context.note or (self._result_notice(result) if result else '') or '관측 사실을 표시합니다. 장애 원인은 인증·AP·무선 환경을 함께 확인하세요.')
        if result:
            self.mm_label.setText(f'MM · {result.mm_status}')
            self.md_label.setText(f'MD · {result.md_status}')
        observation = view.observation if view else None
        if observation:
            for key, label in self.fields.items():
                value = view.previous_ap if key == 'previous_ap' else getattr(observation, key, None)
                if key == 'channel' and observation.band:
                    value = f'{observation.channel or "확인 불가"} / {observation.band}'
                text = '확인 불가' if value is None else f'{value:g}' if isinstance(value, float) else str(value)
                status = observation.field_status.get(key, '')
                if '이전 조회값' in status:
                    text += '\n이전 조회값'
                elif value is None and status and status != '정상':
                    text += '\n' + status[:80]
                label.setText(text)
                label.setToolTip(TOOLTIPS.get(key, '') + '\n수집 상태: ' + status + '\n수집 근거: ' + observation.evidence.get(key, ''))
        self.valid_time.setText(f'마지막 정상 조회: {display_time(view.last_success) if view else "없음"} · 그래프 마지막 유효 관측: {display_time(self.chart.last_valid)} · 연결 상태 변경: {display_time(view.last_change) if view else "없음"}')
        for event in context.events:
            add_row(self.events_table, [display_time(event.at), event.severity, event.message, event.hypothesis, event.recommendation])
            if event.kind in {'roam', 'reconnected', 'md_changed'}:
                facts = event.facts
                def transition(before, after):
                    return f'{facts.get(before) if facts.get(before) is not None else "확인 불가"} → {facts.get(after) if facts.get(after) is not None else "확인 불가"}'
                add_row(self.roaming_table, [display_time(event.at), transition('previous_ap','new_ap'), transition('previous_bssid','new_bssid'), transition('snr_before','snr_after'), transition('role_before','role_after'), event.message])
        self.timing.setText(f'선택 대상: {context.target.value} · 마지막 수집: {display_time(result.collected_at) if result else "없음"} · 완료 후 {self.interval.currentData()}초 간격')

    def _button_state(self):
        if self.coordinator is None:
            return super()._button_state()
        context = self.coordinator.contexts.get(self.selected_id)
        locked = self.coordinator.active or self.coordinator.busy
        self.mode.setEnabled(not locked)
        self.monitor_kind.setEnabled(not locked)
        self.settings_button.setEnabled(not locked)
        self.account_button.setEnabled(not locked)
        self.scenario.setEnabled(bool(self.mode.currentData()) and not locked)
        self.stop_button.setEnabled(bool(context and (context.status != 'stopped' or context.in_flight)))
        self.pause_button.setEnabled(bool(context and context.status in {'running','paused'}))
        self.pause_button.setText('추적 재개' if context and context.status == 'paused' else '일시 정지')
        self.refresh_button.setEnabled(bool(context and context.status in {'running','paused'} and not context.in_flight))
        self.candidate_button.setEnabled(bool(context and context.status == 'selection_required'))
        self.remove_button.setEnabled(context is not None)
        self.active = bool(context and context.status != 'stopped')
        self.paused = bool(context and context.status == 'paused')
        self.worker = context if context and context.in_flight else None
        self.session_id = context.session_id if context else self.session_id

    def _shared_credentials(self):
        if self._credentials_value is None:
            self._credentials_value = self._credentials()
        return self._credentials_value

    def change_account(self):
        if self.coordinator is not None and (self.coordinator.active or self.coordinator.busy):
            return
        if self.pool is not None:
            self.pool.close()
            self.pool = None
        self._credentials_value = None
        self.collector = None
        self.status_note.setText('공통 SSH 계정을 지웠습니다. 다음 발견·추적 연결에서 새 계정을 입력하세요.')

    def open_settings(self):
        if self.coordinator.active or self.coordinator.busy:
            return
        super().open_settings()

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return
        self.pending_close = True
        done = self.coordinator.close(wait=False)
        if not done or self.coordinator.busy:
            self.status_note.setText('진행 중인 수집을 취소하고 연결을 정리하는 중입니다.')
            event.ignore()
            return
        self._closed = True
        self.timer.stop()
        if self.pool:
            self.pool.close()
            self.pool = None
        self._credentials_value = None
        self.collector = None
        self.store.close()
        event.accept()
