"""Desktop entry point and real GUI smoke test used by Windows packaging."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTimer, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

from .models import Outcome
from .runtime_info import runtime_identity
from .ui import MainWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aruba Client Live Tracker")
    parser.add_argument("--multi-demo", action="store_true", help="10대 독립 가상 데이터 모니터링")
    parser.add_argument("--demo", action="store_true", help="가상 데이터 모드")
    parser.add_argument("--smoke-test", action="store_true", help="GUI·데모·SQLite 검증 후 종료")
    parser.add_argument("--screenshot", type=Path, help="실행 화면 PNG 저장 경로")
    parser.add_argument("--data-dir", type=Path, help="로컬 데이터 경로")
    parser.add_argument("--smoke-result", type=Path, help="검증 결과 JSON 저장 경로")
    parser.add_argument("--soak-seconds", type=int, help="새 데이터 폴더에서 10대 데모 연속 검증(1~86400초)")
    args = parser.parse_args(argv)
    from .soak import validate_soak_args
    validate_soak_args(parser, args)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    translator = QTranslator(app)
    translator.load("qtbase_ko", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    app.installTranslator(translator)
    app.setApplicationName("Aruba Client Live Tracker")
    app.setOrganizationName("ArubaClientLiveTracker")
    def write_result(code: int, reason: str, metrics: dict | None = None) -> bool:
        if not args.smoke_result:
            return True
        try:
            args.smoke_result.parent.mkdir(parents=True, exist_ok=True)
            args.smoke_result.write_text(json.dumps(
                {"success": code == 0, "reason": reason, "runtime": runtime_identity(), **(metrics or {})}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            return False
        return True

    temporary = None
    try:
        temporary = tempfile.TemporaryDirectory(prefix="aruba-live-smoke-") if args.smoke_test and not args.data_dir else None
        data_path = args.data_dir or (Path(temporary.name) if temporary else None)
        window = MainWindow(data_path=data_path, demo=args.demo or args.multi_demo or args.smoke_test, multi=args.multi_demo)
    except (OSError, sqlite3.Error):
        reason = "로컬 데이터 폴더 또는 이력 파일을 열 수 없습니다. 폴더 접근 권한과 저장 공간을 확인하세요. 기존 파일을 보존하고 다른 데이터 폴더로 실행할 수 있습니다."
        write_result(6, reason)
        if not args.smoke_test and not args.soak_seconds and app.platformName() not in {'offscreen', 'minimal'}:
            QMessageBox.critical(None, "프로그램 시작 실패", reason)
        elif not args.smoke_test and not args.soak_seconds and QApplication.instance() is app and argv is not None:
            # Embedded invocations can provide their own dialog presentation.
            QMessageBox.critical(None, "프로그램 시작 실패", reason)
        if temporary:
            temporary.cleanup()
        return 6
    if args.screenshot and args.multi_demo:
        window.resize(1500, 1700)
    window.show()
    completed = False
    metrics = {}

    def finish(code: int, reason: str):
        nonlocal completed
        if completed:
            return
        completed = True
        window.stop_all()
        def exit_when_idle():
            nonlocal code, reason
            if window.coordinator.busy:
                QTimer.singleShot(25, exit_when_idle)
                return
            if not window.close() or not window._closed:
                code = 8
                reason = 'HISTORY_SHUTDOWN_FAILED: 이력 종료 기록 저장 또는 DB 닫기에 실패했습니다. 저장 공간과 권한을 확인하세요.'
            if args.soak_seconds and code == 0:
                from .soak import verify_soak_database
                try:
                    verify_soak_database(window.store.path, metrics)
                except (OSError, sqlite3.Error, ValueError):
                    code, reason = 9, 'SOAK_DB_VERIFICATION_FAILED'
            if not write_result(code, reason, metrics):
                code = 7
            app.exit(code)
        exit_when_idle()

    capture_pending = False
    refresh_timer = QTimer(window)
    refresh_timer.setInterval(120)

    def refresh_round():
        if not completed and not capture_pending and not window.coordinator.busy:
            window.refresh_all()

    refresh_timer.timeout.connect(refresh_round)

    def verify(result):
        nonlocal capture_pending
        if completed or capture_pending:
            return
        if result.outcome != Outcome.OK or result.observation is None or not result.observation.simulated:
            finish(2, "데모 관측을 확인하지 못했습니다")
            return
        contexts = list(window.coordinator.contexts.values())
        expected = 10 if args.multi_demo else 1
        ready = len(contexts) == expected and all(c.last_result is not None and len(c.samples) >= 5 for c in contexts)
        if not ready:
            return
        rows = {c.id: window.store.observations(c.session_id) for c in contexts}
        if any(len(values) < 5 for values in rows.values()):
            finish(3, "대상별 SQLite 관측 저장을 확인하지 못했습니다")
            return
        macs = {c.last_result.observation.mac for c in contexts}
        if len(macs) != expected:
            finish(3, "대상별 독립 MAC 관측을 확인하지 못했습니다")
            return
        metrics.update(target_count=expected, observation_count=sum(len(v) for v in rows.values()),
                       target_observations={c.target.value: len(rows[c.id]) for c in contexts},
                       independent_macs=len(macs))
        capture_pending = True
        refresh_timer.stop()
        window.pause_all()
        def capture():
            try:
                if args.screenshot:
                    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                    if not window.grab().save(str(args.screenshot), "PNG"):
                        finish(4, "화면 저장 실패")
                        return
            except OSError:
                finish(4, "화면 저장 경로를 사용할 수 없습니다")
                return
            finish(0, f"GUI 생성·{expected}대 백그라운드 데모 각 5회·대상별 SQLite 저장·정상 종료 확인")
        QTimer.singleShot(100, capture)

    def begin():
        if args.multi_demo:
            from .demo import DEMO_CLIENTS
            window.add_many_targets("\n".join(client.ip for client in DEMO_CLIENTS))
            window.start_all()
        else:
            window.start_tracking()

    if args.soak_seconds:
        from .soak import SoakMonitor
        def finish_soak(code, reason, values):
            metrics.update(values)
            finish(code, reason)
        soak = SoakMonitor(window, args.soak_seconds, args.smoke_result, finish_soak)
        window.interval.setCurrentIndex(window.interval.findData(10))
        window.scenario.setCurrentIndex(window.scenario.findData('normal'))
        QTimer.singleShot(0, begin)
        soak.start()
    elif args.smoke_test:
        window.poll_applied.connect(verify)
        QTimer.singleShot(0, begin)
        refresh_timer.start()
        QTimer.singleShot(30000, lambda: finish(5, "GUI 검증 제한 시간 초과"))
    elif args.demo or args.multi_demo:
        QTimer.singleShot(0, begin)
        if args.screenshot:
            def snapshot(result):
                QTimer.singleShot(200, lambda: window.grab().save(str(args.screenshot), "PNG"))
            window.poll_applied.connect(snapshot)
    result = app.exec()
    if args.soak_seconds and not completed:
        metrics.update(soak.snapshot())
        write_result(9, 'SOAK_INTERRUPTED: run ended before the requested duration', metrics)
        result = 9
    if temporary:
        temporary.cleanup()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
