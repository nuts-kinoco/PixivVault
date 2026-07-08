import os
import shutil
import tkinter as tk
from tkinter import filedialog
import flet as ft
import threading
import logging
from datetime import datetime
from pixiv_client import PixivClient
from database import Database
from core import run_backup, export_data, run_batch_backup

def main_window(page: ft.Page):
    page.title = "PixivVault"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 800
    page.window.height = 600

    db = Database()

    # --- 共通コントロール ---
    stop_event  = threading.Event()
    pause_event = threading.Event()

    log_area = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    log_container = ft.Container(
        content=log_area,
        border=ft.Border(
            top=ft.BorderSide(1, ft.Colors.OUTLINE), bottom=ft.BorderSide(1, ft.Colors.OUTLINE),
            left=ft.BorderSide(1, ft.Colors.OUTLINE), right=ft.BorderSide(1, ft.Colors.OUTLINE),
        ),
        border_radius=5, padding=10, expand=True, bgcolor="#1A1C1E"
    )

    list_expanded = [False]
    def toggle_list_expansion(e=None):
        list_expanded[0] = not list_expanded[0]
        log_container.visible = not list_expanded[0]
        page.update()

    def append_log(msg: str, color: str = ft.Colors.WHITE):
        log_area.controls.append(ft.Text(msg, color=color, selectable=True, size=13))
        page.update()
    def handle_log(msg: str):
        append_log(msg)
    def handle_alert(msg: str):
        append_log(f"[!] {msg}", color=ft.Colors.RED_400)

    login_status_text = ft.Text("ログインチェック中...", color=ft.Colors.BLUE_200, size=12)

    # --- タブ1: 個別ダウンロードUI ---
    user_id_field = ft.TextField(label="PixivユーザーID", width=220)
    mode_dropdown = ft.Dropdown(
        label="実行モード", width=150,
        options=[
            ft.DropdownOption(key="diff", text="差分ダウンロード"),
            ft.DropdownOption(key="full", text="完全ダウンロード"),
        ],
        value="diff"
    )
    target_type_dropdown = ft.Dropdown(
        label="対象", width=160,
        options=[
            ft.DropdownOption(key="illust", text="イラスト・漫画"),
            ft.DropdownOption(key="novel", text="小説"),
            ft.DropdownOption(key="both", text="両方"),
        ],
        value="both"
    )
    run_btn    = ft.ElevatedButton("実行", icon=ft.Icons.PLAY_ARROW)
    pause_btn  = ft.ElevatedButton("一時停止", icon=ft.Icons.PAUSE, disabled=True)
    stop_btn   = ft.ElevatedButton("停止", icon=ft.Icons.STOP, disabled=True)
    export_btn = ft.ElevatedButton("エクスポート", icon=ft.Icons.ARCHIVE)

    progress_bar  = ft.ProgressBar(width=400, value=0, visible=False)
    progress_text = ft.Text("0 / 0", visible=False)
    remaining_time_text = ft.Text("", size=12, color=ft.Colors.BLUE_200)

    progress_history = []

    def handle_progress(current: int, total: int, elapsed_sec: float = 0):
        progress_bar.value = current / total if total > 0 else 0
        progress_text.value = f"{current} / {total}"
        
        if elapsed_sec > 0 and current < total:
            progress_history.append((current, elapsed_sec))
            if len(progress_history) > 10:
                progress_history.pop(0)
                
            if len(progress_history) >= 2:
                items_done = progress_history[-1][0] - progress_history[0][0]
                time_taken = progress_history[-1][1] - progress_history[0][1]
                if time_taken > 0 and items_done > 0:
                    speed = items_done / time_taken
                    remaining_items = total - current
                    eta_sec = remaining_items / speed
                    mins, secs = divmod(int(eta_sec), 60)
                    if mins > 0:
                        remaining_time_text.value = f"残り約{mins}分{secs}秒"
                    else:
                        remaining_time_text.value = f"残り約{secs}秒"
                else:
                    remaining_time_text.value = "残り時間計算中..."
            else:
                remaining_time_text.value = "残り時間計算中..."
        elif current == total:
            remaining_time_text.value = ""
            progress_history.clear()
            
        page.update()

    def set_ui_disabled_single(disabled: bool, is_running: bool = False):
        user_id_field.disabled = disabled
        mode_dropdown.disabled = disabled
        target_type_dropdown.disabled = disabled
        run_btn.disabled       = disabled
        export_btn.disabled    = disabled
        pause_btn.disabled     = not is_running
        stop_btn.disabled      = not is_running
        if not is_running:
            pause_btn.text = "一時停止"
            pause_btn.icon = ft.Icons.PAUSE
        page.update()

    def run_backup_thread():
        user_id = user_id_field.value.strip()
        if not user_id:
            append_log("ユーザーIDを入力してください。", color=ft.Colors.ORANGE_300)
            return
        if not os.path.exists("cookies.txt"):
            handle_alert("cookies.txt が見つかりません。設定ボタンからインポートしてください。")
            return

        is_full = (mode_dropdown.value == "full")
        target_type = target_type_dropdown.value
        append_log("--- 個別ダウンロードを開始します ---", color=ft.Colors.BLUE_300)
        progress_bar.value = 0
        progress_bar.visible = True
        progress_text.visible = True
        stop_event.clear()
        pause_event.clear()
        set_ui_disabled_single(True, is_running=True)

        try:
            client = PixivClient()
            run_backup(
                user_id=user_id, client=client, db=db, is_full=is_full, target_type=target_type,
                log_callback=handle_log, progress_callback=handle_progress,
                alert_callback=handle_alert, stop_event=stop_event, pause_event=pause_event
            )
            append_log("--- 個別ダウンロードが完了しました ---", color=ft.Colors.GREEN_400)
        except Exception as e:
            if stop_event.is_set():
                handle_alert("処理が中止されました。")
            else:
                handle_alert(f"エラー: {e}")
        finally:
            progress_bar.visible = False
            progress_text.visible = False
            remaining_time_text.value = ""
            progress_history.clear()
            set_ui_disabled_single(False, is_running=False)

    run_btn.on_click = lambda _: threading.Thread(target=run_backup_thread, daemon=True).start()

    tab1_content = ft.Column([
        ft.Row([user_id_field, mode_dropdown, target_type_dropdown, run_btn, pause_btn, stop_btn, export_btn], wrap=True),
        ft.Row([progress_bar, progress_text, remaining_time_text]),
    ])

    # --- タブ2: フォロー中一括ダウンロードUI ---
    follow_list_view = ft.ListView(expand=True, spacing=5)
    follow_checkboxes = {}

    batch_target_type_dropdown = ft.Dropdown(
        label="対象", width=160,
        options=[
            ft.DropdownOption(key="illust", text="イラスト・漫画"),
            ft.DropdownOption(key="novel", text="小説"),
            ft.DropdownOption(key="both", text="両方"),
        ],
        value="both"
    )
    
    sort_dropdown = ft.Dropdown(
        label="ソート", width=140,
        options=[
            ft.DropdownOption(key="default", text="同期順"),
            ft.DropdownOption(key="name_asc", text="名前 (昇順)"),
            ft.DropdownOption(key="name_desc", text="名前 (降順)"),
        ],
        value="default"
    )
    batch_run_btn    = ft.ElevatedButton("一括ダウンロード実行", icon=ft.Icons.PLAY_ARROW)
    batch_pause_btn  = ft.ElevatedButton("一時停止", icon=ft.Icons.PAUSE, disabled=True)
    batch_stop_btn   = ft.ElevatedButton("停止", icon=ft.Icons.STOP, disabled=True)
    select_all_btn   = ft.TextButton("すべて選択")
    deselect_all_btn = ft.TextButton("選択解除")

    batch_progress_bar  = ft.ProgressBar(width=400, value=0, visible=False)
    batch_progress_text = ft.Text("0 / 0", visible=False)
    batch_remaining_time_text = ft.Text("", size=12, color=ft.Colors.BLUE_200)

    def load_follow_list_ui():
        follow_list_view.controls.clear()
        follow_checkboxes.clear()
        users = db.get_following_users()
        
        sort_val = sort_dropdown.value
        if sort_val == "name_asc":
            users.sort(key=lambda u: u['name'].lower())
        elif sort_val == "name_desc":
            users.sort(key=lambda u: u['name'].lower(), reverse=True)

        def toggle_zip(e, uid):
            btn = e.control
            is_zipped = btn.icon == ft.Icons.ARCHIVE
            new_val = not is_zipped
            db.set_zipped(uid, new_val)
            btn.icon = ft.Icons.ARCHIVE if new_val else ft.Icons.ARCHIVE_OUTLINED
            btn.icon_color = ft.Colors.BLUE_400 if new_val else ft.Colors.GREY_500
            page.update()

        for u in users:
            label = f"{u['name']} (ID:{u['user_id']})"
            if u.get('last_downloaded'):
                label += f" [最終: {u['last_downloaded'][:10]}]"
                
            cb = ft.Checkbox(value=False)
            follow_checkboxes[u['user_id']] = cb
            
            def on_label_tap(e, cb_ref=cb):
                cb_ref.value = not cb_ref.value
                page.update()
                
            gd_content = ft.Container(
                content=ft.Text(label),
                padding=10,
                alignment=ft.alignment.center_left,
            )
            gd = ft.GestureDetector(
                content=gd_content,
                on_tap=on_label_tap,
                on_double_tap=toggle_list_expansion,
                mouse_cursor=ft.MouseCursor.CLICK,
                expand=True
            )
            
            is_zipped = u.get('is_zipped', 0)
            zip_btn = ft.IconButton(
                icon=ft.Icons.ARCHIVE if is_zipped else ft.Icons.ARCHIVE_OUTLINED,
                icon_color=ft.Colors.BLUE_400 if is_zipped else ft.Colors.GREY_500,
                tooltip="個別Zip化",
                on_click=lambda e, uid=u['user_id']: toggle_zip(e, uid)
            )
            row = ft.Row([cb, gd, zip_btn])
            follow_list_view.controls.append(row)
        page.update()
        
    sort_dropdown.on_change = lambda _: load_follow_list_ui()

    def set_ui_disabled_batch(disabled: bool, is_running: bool = False):
        batch_run_btn.disabled    = disabled
        batch_target_type_dropdown.disabled = disabled
        select_all_btn.disabled   = disabled
        deselect_all_btn.disabled = disabled
        for cb in follow_checkboxes.values():
            cb.disabled = disabled
        batch_pause_btn.disabled = not is_running
        batch_stop_btn.disabled  = not is_running
        if not is_running:
            batch_pause_btn.text = "一時停止"
            batch_pause_btn.icon = ft.Icons.PAUSE
        page.update()

    batch_progress_history = []

    def handle_batch_progress(idx: int, total: int, user_id: str, elapsed_sec: float = 0):
        batch_progress_bar.value  = idx / total if total > 0 else 0
        batch_progress_text.value = f"作者 {idx} / {total}"
        
        if elapsed_sec > 0 and idx < total:
            batch_progress_history.append((idx, elapsed_sec))
            if len(batch_progress_history) > 5:
                batch_progress_history.pop(0)
                
            if len(batch_progress_history) >= 2:
                items_done = batch_progress_history[-1][0] - batch_progress_history[0][0]
                time_taken = batch_progress_history[-1][1] - batch_progress_history[0][1]
                if time_taken > 0 and items_done > 0:
                    speed = items_done / time_taken
                    remaining_items = total - idx
                    eta_sec = remaining_items / speed
                    mins, secs = divmod(int(eta_sec), 60)
                    if mins > 0:
                        batch_remaining_time_text.value = f"残り約{mins}分{secs}秒"
                    else:
                        batch_remaining_time_text.value = f"残り約{secs}秒"
                else:
                    batch_remaining_time_text.value = "残り時間計算中..."
            else:
                batch_remaining_time_text.value = "残り時間計算中..."
        elif idx == total:
            batch_remaining_time_text.value = ""
            batch_progress_history.clear()

        page.update()

    def run_batch_thread():
        selected_ids = [uid for uid, cb in follow_checkboxes.items() if cb.value]
        if not selected_ids:
            append_log("ダウンロードする作者を選択してください。", color=ft.Colors.ORANGE_300)
            return
        if not os.path.exists("cookies.txt"):
            handle_alert("cookies.txt が見つかりません。")
            return

        append_log(f"--- {len(selected_ids)}人の一括ダウンロードを開始します ---", color=ft.Colors.BLUE_300)
        batch_progress_bar.value   = 0
        batch_progress_bar.visible = True
        batch_progress_text.visible = True
        stop_event.clear()
        pause_event.clear()
        set_ui_disabled_batch(True, is_running=True)

        try:
            client = PixivClient()
            target_type = batch_target_type_dropdown.value
            run_batch_backup(
                user_ids=selected_ids, client=client, db=db, is_full=False, target_type=target_type,
                log_callback=handle_log, progress_callback=None, alert_callback=handle_alert,
                stop_event=stop_event, pause_event=pause_event, batch_progress_callback=handle_batch_progress
            )
            append_log("--- 一括ダウンロードが完了しました ---", color=ft.Colors.GREEN_400)
        except Exception as e:
            if stop_event.is_set():
                handle_alert("一括処理が中止されました。")
            else:
                handle_alert(f"エラー: {e}")
        finally:
            batch_progress_bar.visible  = False
            batch_progress_text.visible = False
            batch_remaining_time_text.value = ""
            batch_progress_history.clear()
            set_ui_disabled_batch(False, is_running=False)
            load_follow_list_ui()

    batch_run_btn.on_click = lambda _: threading.Thread(target=run_batch_thread, daemon=True).start()

    def on_batch_pause(e):
        if pause_event.is_set():
            pause_event.clear()
            batch_pause_btn.text = "一時停止"
            batch_pause_btn.icon = ft.Icons.PAUSE
        else:
            pause_event.set()
            batch_pause_btn.text = "再開"
            batch_pause_btn.icon = ft.Icons.PLAY_ARROW
        page.update()

    batch_pause_btn.on_click = on_batch_pause
    batch_stop_btn.on_click  = lambda _: stop_event.set()
    select_all_btn.on_click   = lambda _: [setattr(cb, 'value', True) for cb in follow_checkboxes.values()] or page.update()
    deselect_all_btn.on_click = lambda _: [setattr(cb, 'value', False) for cb in follow_checkboxes.values()] or page.update()

    batch_actions_row = ft.Row([
        select_all_btn,
        deselect_all_btn,
        ft.VerticalDivider(),
        batch_target_type_dropdown,
        sort_dropdown,
        batch_run_btn,
        batch_pause_btn,
        batch_stop_btn
    ], wrap=True)

    tab2_content = ft.Column([
        batch_actions_row,
        ft.Row([batch_progress_bar, batch_progress_text, batch_remaining_time_text]),
        ft.Container(
            content=follow_list_view, expand=True,
            border=ft.Border(
                top=ft.BorderSide(1, ft.Colors.OUTLINE), bottom=ft.BorderSide(1, ft.Colors.OUTLINE),
                left=ft.BorderSide(1, ft.Colors.OUTLINE), right=ft.BorderSide(1, ft.Colors.OUTLINE)
            ),
            padding=5, border_radius=5
        )
    ], expand=True)

    # タブ1 共通イベント
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
    pause_btn.on_click = on_pause_click
    stop_btn.on_click  = lambda _: stop_event.set()

    def run_export_thread():
        append_log("--- エクスポートを開始します ---", color=ft.Colors.BLUE_300)
        try:
            export_data(db=db, log_callback=handle_log)
            append_log("--- エクスポートが完了しました ---", color=ft.Colors.GREEN_400)
        except Exception as e:
            handle_alert(f"エラー: {e}")
    export_btn.on_click = lambda _: threading.Thread(target=run_export_thread, daemon=True).start()

    # --- 設定ダイアログ ---
    cookie_status_text = ft.Text("", selectable=True, visible=False, size=12)
    sync_status_text   = ft.Text("", selectable=True, visible=False, size=12)
    save_path_text     = ft.Text(
        f"現在の保存先: {db.get_setting('save_path', 'Images')}",
        selectable=True, color=ft.Colors.BLUE_200, size=12
    )

    # --- ファイル/フォルダー選択 (tkinterのネイティブダイアログを使用) ---
    def _run_cookie_file_picker():
        """cookies.txt のファイル選択ダイアログをバックグラウンドスレッドで実行"""
        try:
            root = tk.Tk()
            root.withdraw()
            root.wm_attributes("-topmost", True)
            file_path = filedialog.askopenfilename(
                parent=root,
                title="cookies.txt を選択",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
            )
            root.destroy()
            if file_path:
                shutil.copy2(file_path, "cookies.txt")
                cookie_status_text.value = "[完了] cookies.txt をインポートしました。"
                cookie_status_text.color = ft.Colors.GREEN_400
                cookie_status_text.visible = True
                threading.Thread(target=check_login_status, daemon=True).start()
            else:
                cookie_status_text.value = "キャンセルされました。"
                cookie_status_text.color = ft.Colors.GREY_400
                cookie_status_text.visible = True
        except Exception as ex:
            cookie_status_text.value = f"[失敗] {ex}"
            cookie_status_text.color = ft.Colors.RED_400
            cookie_status_text.visible = True
        page.update()

    def _run_folder_picker():
        """保存先フォルダー選択ダイアログをバックグラウンドスレッドで実行"""
        try:
            root = tk.Tk()
            root.withdraw()
            root.wm_attributes("-topmost", True)
            folder_path = filedialog.askdirectory(
                parent=root,
                title="画像の保存先フォルダーを選択"
            )
            root.destroy()
            if folder_path:
                db.set_setting("save_path", folder_path)
                save_path_text.value = f"現在の保存先: {folder_path}"
                append_log(f"保存先フォルダーを {folder_path} に変更しました。")
            else:
                append_log("フォルダー選択がキャンセルされました。")
        except Exception as ex:
            append_log(f"フォルダー選択エラー: {ex}", color=ft.Colors.RED_400)
        page.update()

    def sync_follow_list():
        sync_status_text.value = "Pixivから同期中..."
        sync_status_text.color = ft.Colors.BLUE_400
        sync_status_text.visible = True
        page.update()
        try:
            client = PixivClient()
            my_id  = client.get_my_user_id()
            users  = client.get_following_users(my_user_id=my_id, rest_type="show", log_callback=handle_log)
            users.extend(client.get_following_users(my_user_id=my_id, rest_type="hide", log_callback=handle_log))
            db.save_following_users(users)
            db.set_setting("last_sync_date", datetime.now().isoformat())
            sync_status_text.value = f"[完了] 同期完了 ({len(users)}人の作者)"
            sync_status_text.color = ft.Colors.GREEN_400
            sync_status_text.visible = True
            load_follow_list_ui()
        except Exception as e:
            sync_status_text.value = f"[失敗] 同期失敗: {e}"
            sync_status_text.color = ft.Colors.RED_400
            sync_status_text.visible = True
        page.update()

    def on_zip_all_change(e):
        db.set_setting("zip_all_after_download", "1" if e.control.value else "0")

    zip_all_checkbox = ft.Checkbox(
        label="すべての作者に対しダウンロード完了後zipにする",
        value=db.get_setting("zip_all_after_download", "0") == "1",
        on_change=on_zip_all_change
    )
    
    advanced_settings = ft.ExpansionTile(
        title=ft.Text("Advanced / 高度な設定", weight=ft.FontWeight.BOLD),
        controls=[zip_all_checkbox]
    )

    settings_dialog = ft.AlertDialog(
        title=ft.Text("設定"),
        content=ft.Column([
            ft.Text("1. Cookie のインポート", weight=ft.FontWeight.BOLD),
            ft.Text("Pixivのログイン状態を引き継ぐための cookies.txt を選択してください。", size=12, color=ft.Colors.GREY_400),
            ft.ElevatedButton("ファイルを選択", icon=ft.Icons.UPLOAD_FILE,
                              on_click=lambda _: threading.Thread(target=_run_cookie_file_picker, daemon=True).start()),
            cookie_status_text,
            ft.Divider(),
            ft.Text("2. フォロー中リストの同期", weight=ft.FontWeight.BOLD),
            ft.Text("Pixivからフォロー中の作者情報を取得し、DBに保存します。", size=12, color=ft.Colors.GREY_400),
            ft.ElevatedButton("リストを同期", icon=ft.Icons.SYNC,
                              on_click=lambda _: threading.Thread(target=sync_follow_list, daemon=True).start()),
            sync_status_text,
            ft.Divider(),
            ft.Text("3. 保存フォルダーの設定", weight=ft.FontWeight.BOLD),
            ft.Text("画像のダウンロード先フォルダーを指定します（再起動後も保持）。", size=12, color=ft.Colors.GREY_400),
            ft.ElevatedButton("フォルダーを選択", icon=ft.Icons.FOLDER_OPEN,
                              on_click=lambda _: threading.Thread(target=_run_folder_picker, daemon=True).start()),
            save_path_text,
            ft.Divider(),
            advanced_settings,
            ft.Row([
                ft.Text("v2.0 build 260707", size=11, color=ft.Colors.GREY_600)
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([
                ft.TextButton("閉じる", on_click=lambda _: page.pop_dialog())
            ], alignment=ft.MainAxisAlignment.END),
        ], tight=True, width=500, height=420, scroll=ft.ScrollMode.AUTO, spacing=8),
    )

    settings_btn = ft.IconButton(
        icon=ft.Icons.SETTINGS, tooltip="設定",
        on_click=lambda _: page.show_dialog(settings_dialog)
    )

    # --- タブ切り替え ---
    tab1_container = ft.Container(content=tab1_content, padding=10, visible=True)
    tab2_container = ft.Container(content=tab2_content, padding=10, visible=False, expand=True)

    def on_tab_change(e):
        idx = e.control.selected_index
        tab1_container.visible = (idx == 0)
        tab2_container.visible = (idx == 1)
        page.update()

    tabs = ft.Tabs(
        length=2,
        selected_index=0,
        on_change=on_tab_change,
        content=ft.TabBar(tabs=[
            ft.Tab(label="個別ダウンロード", icon=ft.Icons.PERSON),
            ft.Tab(label="フォロー中一括",   icon=ft.Icons.GROUP),
        ]),
        expand=False
    )

    page.add(
        ft.Row([
            ft.Column([
                ft.Text("PixivVault", size=26, weight=ft.FontWeight.BOLD),
                login_status_text
            ]),
            settings_btn
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        tabs,
        tab1_container,
        tab2_container,
        log_container
    )

    # --- 起動時バックグラウンド処理 ---
    def run_auto_sync_thread(my_id):
        try:
            client = PixivClient()
            users  = client.get_following_users(my_user_id=my_id, rest_type="show", log_callback=None)
            users.extend(client.get_following_users(my_user_id=my_id, rest_type="hide", log_callback=None))
            db.save_following_users(users)
            db.set_setting("last_sync_date", datetime.now().isoformat())
            append_log(f"起動時自動同期完了 ({len(users)}人の作者)", color=ft.Colors.GREEN_400)
            load_follow_list_ui()
        except Exception as e:
            append_log(f"自動同期失敗: {e}", color=ft.Colors.RED_400)

    def trigger_auto_sync(my_id):
        last_sync = db.get_setting("last_sync_date")
        should_sync = True
        if last_sync:
            try:
                delta = (datetime.now() - datetime.fromisoformat(last_sync)).total_seconds()
                should_sync = delta > 24 * 3600
            except Exception:
                pass
        if should_sync:
            append_log("起動時フォローリスト自動同期を開始します...", color=ft.Colors.BLUE_300)
            threading.Thread(target=run_auto_sync_thread, args=(my_id,), daemon=True).start()

    def check_login_status():
        if not os.path.exists("cookies.txt"):
            login_status_text.value = "[警告] cookies.txt が見つかりません。設定からインポートしてください。"
            login_status_text.color = ft.Colors.RED_400
            page.update()
            return
        try:
            client = PixivClient()
            my_id  = client.get_my_user_id()
            login_status_text.value = f"[ログイン中] ユーザーID: {my_id}"
            login_status_text.color = ft.Colors.GREEN_400
            page.update()
            trigger_auto_sync(my_id)
        except Exception:
            login_status_text.value = "[警告] Cookie期限切れまたは無効です。再インポートしてください。"
            login_status_text.color = ft.Colors.RED_400
            page.update()

    # 初期化
    load_follow_list_ui()
    threading.Thread(target=check_login_status, daemon=True).start()
