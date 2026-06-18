import os
import shutil
import flet as ft
import threading
import logging
from pixiv_client import PixivClient
from database import Database
from core import run_backup, export_data

def main_window(page: ft.Page):
    page.title = "PixivVault"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 640
    page.window.height = 480

    # UIコンポーネント
    user_id_field = ft.TextField(label="PixivユーザーID", width=220, autofocus=True)
    mode_dropdown = ft.Dropdown(
        label="実行モード",
        width=200,
        options=[
            ft.DropdownOption(key="diff", text="差分ダウンロード"),
            ft.DropdownOption(key="full", text="完全ダウンロード"),
        ],
        value="diff"
    )

    run_btn    = ft.ElevatedButton("実行",     icon=ft.Icons.PLAY_ARROW)
    pause_btn  = ft.ElevatedButton("一時停止", icon=ft.Icons.PAUSE,   disabled=True)
    stop_btn   = ft.ElevatedButton("停止",     icon=ft.Icons.STOP,    disabled=True)
    export_btn = ft.ElevatedButton("エクスポート", icon=ft.Icons.ARCHIVE)

    progress_bar  = ft.ProgressBar(width=600, value=0, visible=False)
    progress_text = ft.Text("0 / 0", visible=False)
    log_area      = ft.ListView(expand=True, spacing=2, auto_scroll=True)

    # 制御用イベントフラグ
    stop_event  = threading.Event()
    pause_event = threading.Event()

    # ─── ログ / コールバック ──────────────────────────────────────────
    def append_log(msg: str, color: str = ft.Colors.WHITE):
        log_area.controls.append(ft.Text(msg, color=color, selectable=True, size=13))
        page.update()

    def handle_log(msg: str):
        append_log(msg)

    def handle_alert(msg: str):
        append_log(f"⚠️  {msg}", color=ft.Colors.RED_400)

    def handle_progress(current: int, total: int):
        progress_bar.value = current / total if total > 0 else 0
        progress_text.value = f"{current} / {total}"
        page.update()

    def set_ui_disabled(disabled: bool, is_running: bool = False):
        user_id_field.disabled = disabled
        mode_dropdown.disabled = disabled
        run_btn.disabled       = disabled
        export_btn.disabled    = disabled
        pause_btn.disabled     = not is_running
        stop_btn.disabled      = not is_running
        if not is_running:
            pause_btn.text = "一時停止"
            pause_btn.icon = ft.Icons.PAUSE
        page.update()

    # ─── Cookie インポートダイアログ ──────────────────────────────────
    # FilePicker は Service のサブクラスなので page.services に追加する
    file_picker = ft.FilePicker()
    page.services.append(file_picker)

    cookie_status_text = ft.Text("")

    cookie_dialog = ft.AlertDialog(
        title=ft.Text("Cookie の設定"),
        content=ft.Column([
            ft.Text("Pixivの作品をダウンロードするには、ブラウザのCookieが必要です。"),
            ft.Text("1. ChromeやEdgeでPixivにログインしてください。"),
            ft.Text("2. 拡張機能「Get cookies.txt LOCALLY」等でCookieをエクスポートします。"),
            ft.Text("3. 以下のボタンから、ダウンロードしたテキストファイルを選択してください。"),
            ft.Divider(),
            cookie_status_text,
        ], tight=True, width=420),
        actions=[
            ft.TextButton("ファイルを選択", icon=ft.Icons.UPLOAD_FILE, on_click=lambda _: on_pick_file_click()),
            ft.TextButton("閉じる", on_click=lambda _: page.pop_dialog()),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def on_pick_file_click():
        async def _pick():
            files = await file_picker.pick_files(allow_multiple=False)
            if files:
                source_path = files[0].path
                try:
                    shutil.copy2(source_path, "cookies.txt")
                    cookie_status_text.value = "✅ cookies.txt のインポートに成功しました。"
                    cookie_status_text.color = ft.Colors.GREEN_400
                    append_log("cookies.txt のインポートに成功しました。", color=ft.Colors.GREEN_400)
                except Exception as ex:
                    cookie_status_text.value = f"❌ インポートに失敗しました: {ex}"
                    cookie_status_text.color = ft.Colors.RED_400
                page.update()
        page.run_task(_pick)

    settings_btn = ft.IconButton(
        icon=ft.Icons.SETTINGS,
        tooltip="Cookie の設定",
        on_click=lambda _: page.show_dialog(cookie_dialog)
    )

    # ─── ダウンロードスレッド ─────────────────────────────────────────
    def run_backup_thread():
        user_id = user_id_field.value.strip()
        if not user_id:
            append_log("ユーザーIDを入力してください。", color=ft.Colors.ORANGE_300)
            return

        if not os.path.exists("cookies.txt"):
            handle_alert("cookies.txt が見つかりません。右上の設定ボタンからインポートしてください。")
            return

        is_full  = (mode_dropdown.value == "full")
        mode_str = "完全ダウンロード" if is_full else "差分ダウンロード"

        append_log(f"━━━ {mode_str} を開始します ━━━", color=ft.Colors.BLUE_300)
        progress_bar.value    = 0
        progress_bar.visible  = True
        progress_text.visible = True

        stop_event.clear()
        pause_event.clear()
        set_ui_disabled(True, is_running=True)

        try:
            client = PixivClient()
            db     = Database()
            run_backup(
                user_id=user_id, client=client, db=db, is_full=is_full,
                log_callback=handle_log, progress_callback=handle_progress,
                alert_callback=handle_alert,
                stop_event=stop_event, pause_event=pause_event,
            )
            append_log(f"━━━ {mode_str} が完了しました ━━━", color=ft.Colors.GREEN_400)
        except Exception as e:
            if stop_event.is_set():
                handle_alert("処理がユーザーによって中止されました。")
            else:
                handle_alert(f"エラーが発生しました: {e}")
        finally:
            progress_bar.visible  = False
            progress_text.visible = False
            set_ui_disabled(False, is_running=False)

    def run_export_thread():
        append_log("━━━ エクスポートを開始します ━━━", color=ft.Colors.BLUE_300)
        set_ui_disabled(True, is_running=False)
        try:
            db = Database()
            export_data(db=db, log_callback=handle_log)
            append_log("━━━ エクスポートが完了しました ━━━", color=ft.Colors.GREEN_400)
        except Exception as e:
            handle_alert(f"エクスポート中にエラーが発生しました: {e}")
        finally:
            set_ui_disabled(False, is_running=False)

    # ─── ボタンイベント ───────────────────────────────────────────────
    def on_run_click(e):
        threading.Thread(target=run_backup_thread, daemon=True).start()

    def on_pause_click(e):
        if pause_event.is_set():
            pause_event.clear()
            pause_btn.text = "一時停止"
            pause_btn.icon = ft.Icons.PAUSE
        else:
            pause_event.set()
            pause_btn.text = "再開"
            pause_btn.icon = ft.Icons.PLAY_ARROW
        page.update()

    def on_stop_click(e):
        stop_event.set()
        pause_event.clear()

    def on_export_click(e):
        threading.Thread(target=run_export_thread, daemon=True).start()

    run_btn.on_click    = on_run_click
    pause_btn.on_click  = on_pause_click
    stop_btn.on_click   = on_stop_click
    export_btn.on_click = on_export_click

    # ─── レイアウト ──────────────────────────────────────────────────
    page.add(
        ft.Row(
            [ft.Text("PixivVault", size=26, weight=ft.FontWeight.BOLD), settings_btn],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        ft.Divider(),
        ft.Row(
            [user_id_field, mode_dropdown, run_btn, pause_btn, stop_btn, export_btn],
            alignment=ft.MainAxisAlignment.START,
            wrap=True,
        ),
        ft.Row([progress_bar, progress_text]),
        ft.Container(
            content=log_area,
            border=ft.Border(
                top=ft.BorderSide(1, ft.Colors.OUTLINE),
                bottom=ft.BorderSide(1, ft.Colors.OUTLINE),
                left=ft.BorderSide(1, ft.Colors.OUTLINE),
                right=ft.BorderSide(1, ft.Colors.OUTLINE),
            ),
            border_radius=5,
            padding=10,
            expand=True,
            bgcolor="#1A1C1E",
        ),
    )
