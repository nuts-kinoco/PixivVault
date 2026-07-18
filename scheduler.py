import time
import threading
from datetime import datetime, timedelta
import win11toast
from pixiv_client import PixivClient
from database import Database
from core import run_batch_backup

class Scheduler:
    def __init__(self, db: Database, log_callback=None):
        self.db = db
        self.log_callback = log_callback
        self.running = False
        self.thread = None
        self.stop_event = threading.Event()

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.stop_event.set()  # wait() を即座に割り込んでスレッドを起こす

    def on_settings_changed(self):
        """設定変更時に待機を割り込んで間隔などの変更を即座に適用します"""
        if self.running:
            self.stop_event.set()

    def notify(self, title, body):
        if self.db.get_setting("enable_notifications", "1") == "1":
            try:
                win11toast.toast(title, body)
            except Exception as e:
                if self.log_callback:
                    self.log_callback(f"通知エラー: {e}")

    def _loop(self):
        # 起動時チェックの判定（定期チェック間隔が0=自動チェックしないの場合でも起動時チェックONなら実施）
        check_on_startup = self.db.get_setting("check_on_startup", "0") == "1"
        if check_on_startup:
            self.stop_event.wait(5)  # 起動直後のネットワーク・ GUI 初期化待機
            if self.running:
                self._run_check()

        last_check_time = datetime.now()
        while self.running:
            self.stop_event.wait(60)  # 1分ごとに設定をチェック（stopやon_settings_changedで即座に起きる）
            if not self.running:
                break
            self.stop_event.clear()  # 次の wait のためにリセット
            
            interval_str = self.db.get_setting("auto_check_interval_hours", "24")
            try:
                interval = int(interval_str)
            except ValueError:
                interval = 24
            
            if interval <= 0:
                continue

            if datetime.now() - last_check_time > timedelta(hours=interval):
                self._run_check()
                last_check_time = datetime.now()

    def _run_check(self):
        favs = self.db.get_favorite_users()
        if not favs:
            if self.log_callback:
                self.log_callback("☆ お気に入り自動チェック: 対象の作者（☆お気に入り）が登録されていません。")
            return

        user_ids = [u['user_id'] for u in favs]
        
        if self.log_callback:
            self.log_callback(f"☆ お気に入り自動チェックを開始します ({len(user_ids)}人の作者)")

        try:
            client = PixivClient(db=self.db)
            check_start_time = datetime.now().isoformat()
            
            # pause_eventは定期チェックでは不要だがAPIの互換性のためダミーを使用
            pause_event = threading.Event()

            # 一括バックアップ実行
            run_batch_backup(
                user_ids=user_ids, 
                client=client, 
                db=self.db, 
                is_full=False, 
                target_type="both",
                log_callback=self.log_callback, 
                progress_callback=None, 
                alert_callback=self.log_callback,
                stop_event=self.stop_event, 
                pause_event=pause_event, 
                batch_progress_callback=None
            )

            # 更新された作品数をカウント
            with self.db.lock:
                cursor = self.db.conn.execute(
                    "SELECT COUNT(*) as c FROM works WHERE last_backup >= ?", 
                    (check_start_time,)
                )
                row = cursor.fetchone()
                downloaded_count = row['c'] if row else 0

            if downloaded_count > 0:
                self.notify(
                    "PixivVault 定期チェック", 
                    f"お気に入りの作者から {downloaded_count} 件の作品を保存しました！"
                )
            
            if self.log_callback:
                self.log_callback(f"☆ お気に入り自動チェック完了: {downloaded_count}件の作品を保存しました。")

        except Exception as e:
            if self.log_callback:
                self.log_callback(f"☆ お気に入り自動チェック中にエラーが発生しました: {e}")
