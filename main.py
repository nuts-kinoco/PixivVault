import flet as ft
from gui import main_window
from tray import run_tray
from database import Database
from scheduler import Scheduler
import sys
import os
import logging
from logging.handlers import RotatingFileHandler

# カスタムURIスキーム経由で起動された際、CwdがSystem32等になるのを防ぐため、
# 実行ファイル(またはスクリプト)が存在するフォルダにカレントディレクトリを強制変更します。
if getattr(sys, 'frozen', False):
    app_path = os.path.dirname(os.path.abspath(sys.executable))
else:
    app_path = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(app_path)


def setup_logging():
    """gui.py/server.py/core.py 等の logger.error()/logger.exception() が実際にファイルへ
    残るよう、アプリ全体で共有するファイルハンドラをここで一元設定する。
    サイズ上限付きのローテーションにより gui_error_log.txt が無制限に肥大化するのを防ぐ。
    """
    handler = RotatingFileHandler("gui_error_log.txt", maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)
    root_logger.addHandler(handler)


_instance_lock_socket = None

def check_single_instance(port=25011):
    import socket
    import sys
    global _instance_lock_socket
    try:
        _instance_lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # ソケットオプションを設定して再利用できるようにする
        _instance_lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _instance_lock_socket.bind(('127.0.0.1', port))
        _instance_lock_socket.listen(1)
    except socket.error:
        try:
            from win11toast import toast
            toast("PixivVault", "PixivVaultは既に起動しています。", app_id="PixivVault")
        except Exception:
            pass
        sys.exit(0)

def main():
    setup_logging()
    check_single_instance()
    db = Database()
    
    # スケジューラの初期化と開始
    scheduler = Scheduler(db, log_callback=None)
    scheduler.start()
    
    # 拡張機能連携用ローカルサーバーの起動
    from pixiv_client import PixivClient
    from server import start_server
    import threading
    
    client = PixivClient()
    server_thread = threading.Thread(target=start_server, args=(25010, db, client), daemon=True)
    server_thread.start()

    import sys
    def get_asset_path(filename):
        if hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, 'assets', filename)
        return os.path.join(os.path.abspath("."), 'assets', filename)

    def app_target(page: ft.Page):
        # 画面サイズの設定 (16:9比率)
        page.window.width = 1152
        page.window.height = 648
        # アイコンの設定はFletから行わず、EXEのアイコンをそのまま使わせる
        # (page.window.iconを指定するとFletが上書きして魚になる問題の回避)
        
        # メインUIの構築
        main_window(page)
        
        # ウィンドウの「×」ボタンで閉じないようにする
        page.window.prevent_close = True
        
        _tray_icon = None

        def on_window_event(e):
            if e.type == ft.WindowEventType.CLOSE:
                import gui
                is_downloading = gui.is_downloading_active[0]
                
                msg = "ダウンロードが実行中です。アプリを終了しますか？" if is_downloading else "アプリを終了します。よろしいですか？"
                
                def handle_yes(e):
                    page.pop_dialog()
                    if is_downloading and gui.request_stop_all[0]:
                        gui.request_stop_all[0]()
                    
                    scheduler.stop()
                    try:
                        if _tray_icon:
                            _tray_icon.stop()
                    except Exception:
                        pass
                    page.run_task(page.window.destroy)

                def handle_no(e):
                    page.pop_dialog()

                confirm_dialog = ft.AlertDialog(
                    modal=True,
                    title=ft.Text("終了確認"),
                    content=ft.Text(msg),
                    actions=[
                        ft.TextButton("はい", on_click=handle_yes),
                        ft.TextButton("いいえ", on_click=handle_no),
                    ],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
                page.show_dialog(confirm_dialog)
            elif e.type == ft.WindowEventType.MINIMIZE:
                if db.get_setting("minimize_to_tray", "1") == "1":
                    page.window.visible = False
                    page.update()
        
        page.window.on_event = on_window_event

        # タスクトレイのアクション
        def on_show_clicked():
            page.window.visible = True
            page.window.to_front()
            page.update()

        def on_exit_clicked():
            # アプリの完全終了
            scheduler.stop()
            page.run_task(page.window.destroy)

        # トレイアイコンをバックグラウンドで開始
        _tray_icon = run_tray(on_show_clicked, on_exit_clicked)

    ft.run(app_target, assets_dir="assets")

if __name__ == '__main__':
    main()
