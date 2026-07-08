import flet as ft
from gui import main_window
from tray import run_tray
from database import Database
from scheduler import Scheduler
import sys

def main():
    db = Database()
    
    # スケジューラの初期化と開始
    scheduler = Scheduler(db, log_callback=None)
    scheduler.start()

    def app_target(page: ft.Page):
        # メインUIの構築
        main_window(page)
        
        # ウィンドウの「×」ボタンで閉じないようにする
        page.window.prevent_close = True

        def on_window_event(e):
            if e.data == "close":
                page.window.visible = False
                page.update()
        
        page.on_window_event = on_window_event

        # タスクトレイのアクション
        def on_show_clicked():
            page.window.visible = True
            page.window.to_front()
            page.update()

        def on_exit_clicked():
            # アプリの完全終了
            scheduler.stop()
            page.window.destroy()
            sys.exit(0)

        # トレイアイコンをバックグラウンドで開始
        run_tray(on_show_clicked, on_exit_clicked)

    ft.app(target=app_target)

if __name__ == '__main__':
    main()
