import sqlite3
from datetime import datetime

class Database:
    def __init__(self, db_path="pixiv_vault.db"):
        self.conn = sqlite3.connect(db_path)
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

    def upsert_work(self, work_id, user_id, title, page_count, create_date, update_date):
        """作品情報を新規登録、または更新します"""
        now = datetime.now().isoformat()
        with self.conn:
            self.conn.execute("""
                INSERT INTO works (work_id, user_id, title, page_count, create_date, update_date, last_backup, is_deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(work_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    title = excluded.title,
                    page_count = excluded.page_count,
                    create_date = excluded.create_date,
                    update_date = excluded.update_date,
                    last_backup = excluded.last_backup,
                    is_deleted = 0
            """, (work_id, user_id, title, page_count, create_date, update_date, now))
