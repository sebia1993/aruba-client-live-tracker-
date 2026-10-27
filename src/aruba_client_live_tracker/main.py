"""Desktop entry point and real GUI smoke test used by Windows packaging."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTimer, QTranslator
from PySide6.QtWidgets import QApplication

from .models import Outcome
from .ui import MainWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aruba Client Live Tracker")
    parser.add_argument("--demo", action="store_true", help="가상 데이터 모드")
    parser.add_argument("--smoke-test", action="store_true", help="GUI·데모·SQLite 검증 후 종료")
    parser.add_argument("--screenshot", type=Path, help="실행 화면 PNG 저장 경로")
    parser.add_argument("--data-dir", type=Path, help="로컬 데이터 경로")
    parser.add_argument("--smoke-result", type=Path, help="검증 결과 JSON 저장 경로")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    translator = QTranslator(app)
    translator.load("qtbase_ko", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    app.installTranslator(translator)
    app.setApplicationName("Aruba Client Live Tracker")
    app.setOrganizationName("ArubaClientLiveTracker")
    temporary = tempfile.TemporaryDirectory(prefix="aruba-live-smoke-") if args.smoke_test and not args.data_dir else None
    data_path = args.data_dir or (Path(temporary.name) if temporary else None)
    window = MainWindow(data_path=data_path, demo=args.demo or args.smoke_test)
    window.show()
    completed = False

    def finish(code: int, reason: str):
        nonlocal completed
        if completed:
            return
        completed = True
        if args.smoke_result:
            args.smoke_result.parent.mkdir(parents=True, exist_ok=True)
            args.smoke_result.write_text(json.dumps({"success": code == 0, "reason": reason}, ensure_ascii=False), encoding="utf-8")
        window.stop_tracking()
        def exit_when_idle():
            if window.worker is not None:
                QTimer.singleShot(25, exit_when_idle)
                return
            window.close()
            app.exit(code)
        exit_when_idle()

    count = 0

    def verify(result):
        nonlocal count
        if completed:
            return
        count += 1
        if result.outcome != Outcome.OK or result.observation is None or not result.observation.simulated:
            finish(2, "데모 관측을 확인하지 못했습니다")
            return
        sessions = window.store.sessions()
        if not sessions or not window.store.observations(sessions[0]["id"]):
            finish(3, "SQLite 관측 저장을 확인하지 못했습니다")
            return
        if count < 5:
            QTimer.singleShot(120, window.refresh_now)
            return
        def capture():
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                if not window.grab().save(str(args.screenshot), "PNG"):
                    finish(4, "화면 저장 실패")
                    return
            finish(0, "GUI 생성·백그라운드 데모 5회·SQLite 저장·정상 종료 확인")
        QTimer.singleShot(100, capture)

    if args.smoke_test:
        window.poll_applied.connect(verify)
        QTimer.singleShot(0, window.start_tracking)
        QTimer.singleShot(20000, lambda: finish(5, "GUI 검증 제한 시간 초과"))
    elif args.demo:
        QTimer.singleShot(0, window.start_tracking)
        if args.screenshot:
            def snapshot(result):
                QTimer.singleShot(200, lambda: window.grab().save(str(args.screenshot), "PNG"))
            window.poll_applied.connect(snapshot)
    result = app.exec()
    if temporary:
        temporary.cleanup()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
