import sqlite3
from datetime import datetime

class Database:
    def __init__(self, db_path="pixiv_vault.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS works (
                    work_id TEXT PRIMARY KEY,
                    title TEXT,
                    page_count INTEGER,
                    create_date TEXT,
                    update_date TEXT,
                    last_backup TEXT,
                    is_deleted BOOLEAN DEFAULT 0
                )
            """)
            try:
                self.conn.execute("ALTER TABLE works ADD COLUMN user_id TEXT")
            except sqlite3.OperationalError:
                pass
            
            try:
                self.conn.execute("ALTER TABLE works ADD COLUMN content_type TEXT DEFAULT 'illust'")
            except sqlite3.OperationalError:
                pass

            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS following_users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT,
                    account TEXT,
                    profile_img TEXT,
                    last_downloaded TEXT,
                    is_zipped BOOLEAN DEFAULT 0
                )
            """)
            try:
                self.conn.execute("ALTER TABLE following_users ADD COLUMN is_zipped BOOLEAN DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

    def get_user_work_ids(self, user_id):
        """指定したユーザーの作品IDを取得します"""
        cursor = self.conn.execute("SELECT work_id FROM works WHERE user_id = ?", (user_id,))
        return {row['work_id'] for row in cursor.fetchall()}

    def get_work(self, work_id):
        """指定した作品IDのレコードを取得します"""
        cursor = self.conn.execute("SELECT * FROM works WHERE work_id = ?", (work_id,))
        return cursor.fetchone()

    def mark_as_deleted(self, work_id):
        """作品がPixivから削除されたことを記録します"""
        with self.conn:
            self.conn.execute("UPDATE works SET is_deleted = 1 WHERE work_id = ?", (work_id,))

    def upsert_work(self, work_id, user_id, title, page_count, create_date, update_date, content_type='illust'):
        """作品情報を新規登録、または更新します"""
        now = datetime.now().isoformat()
        with self.conn:
            self.conn.execute("""
                INSERT INTO works (work_id, user_id, title, page_count, create_date, update_date, last_backup, is_deleted, content_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(work_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    title = excluded.title,
                    page_count = excluded.page_count,
                    create_date = excluded.create_date,
                    update_date = excluded.update_date,
                    last_backup = excluded.last_backup,
                    is_deleted = 0,
                    content_type = excluded.content_type
            """, (work_id, user_id, title, page_count, create_date, update_date, now, content_type))

    def save_following_users(self, users_list):
        """フォローしているユーザー一覧をデータベースに保存/更新します"""
        with self.conn:
            for user in users_list:
                self.conn.execute("""
                    INSERT INTO following_users (user_id, name, account, profile_img, last_downloaded)
                    VALUES (?, ?, ?, ?, (SELECT last_downloaded FROM following_users WHERE user_id = ?))
                    ON CONFLICT(user_id) DO UPDATE SET
                        name = excluded.name,
                        account = excluded.account,
                        profile_img = excluded.profile_img
                """, (user['user_id'], user['name'], user['account'], user['profile_img'], user['user_id']))

    def get_following_users(self):
        """保存されているフォローユーザー一覧を取得します"""
        cursor = self.conn.execute("SELECT * FROM following_users")
        return [dict(row) for row in cursor.fetchall()]

    def update_following_last_downloaded(self, user_id):
        """特定のフォローユーザーの最終ダウンロード日時を更新します"""
        now = datetime.now().isoformat()
        with self.conn:
            self.conn.execute("""
                UPDATE following_users 
                SET last_downloaded = ? 
                WHERE user_id = ?
            """, (now, user_id))

    def get_setting(self, key, default=None):
        """設定値を取得します"""
        cursor = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row['value'] if row else default

    def set_setting(self, key, value):
        """設定値を保存/更新します"""
        with self.conn:
            self.conn.execute("""
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, str(value)))

    def set_zipped(self, user_id, is_zipped):
        """特定のユーザーのZip圧縮対象状態を更新します"""
        with self.conn:
            self.conn.execute("UPDATE following_users SET is_zipped = ? WHERE user_id = ?", (int(is_zipped), user_id))
