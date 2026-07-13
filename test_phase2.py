import unittest
import os
import shutil
import tempfile
from unittest.mock import MagicMock
from database import Database
from core import run_backup

class TestPhase2UpdateStatistics(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_phase2.db")
        self.db = Database(db_path=self.db_path)
        self.db.set_setting("save_path", self.test_dir)
        self.db.set_setting("use_work_folder", "0")

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_run_backup_new_and_skipped(self):
        """新規作品と既存スキップ作品が混在する場合の集計テスト"""
        mock_client = MagicMock()
        mock_client.get_user_works.return_value = [
            {
                "id": 101,
                "title": "New Work",
                "user_name": "Artist A",
                "user_id": 1000,
                "page_count": 1,
                "create_date": "2026-01-01",
                "update_date": "2026-01-01",
                "type": "illust"
            },
            {
                "id": 102,
                "title": "Existing Work",
                "user_name": "Artist A",
                "user_id": 1000,
                "page_count": 1,
                "create_date": "2026-01-01",
                "update_date": "2026-01-01",
                "type": "illust"
            }
        ]
        mock_client.get_image_urls.return_value = ["https://example.com/test.jpg"]
        
        # ダミー画像ダウンロード成功のモック
        def mock_download(url, save_path):
            with open(save_path, "wb") as f:
                f.write(b"dummy image bytes")
        mock_client.download_image.side_effect = mock_download

        # 作品102はあらかじめDBに入れておく（最新状態）
        self.db.upsert_work("102", "1000", "Existing Work", 1, "2026-01-01", "2026-01-01")

        stats = run_backup(
            user_id="1000",
            client=mock_client,
            db=self.db,
            is_full=False,
            target_type="illust",
            new_only=False
        )

        self.assertEqual(stats["new_count"], 1)      # 101は新規
        self.assertEqual(stats["skipped_count"], 1)  # 102は変更なしスキップ
        self.assertEqual(stats["updated_count"], 0)
        self.assertEqual(stats["deleted_count"], 0)

    def test_run_backup_updated_and_restored(self):
        """更新作品(△)および削除復帰作品(↺)の集計テスト"""
        mock_client = MagicMock()
        mock_client.get_user_works.return_value = [
            {
                "id": 201,
                "title": "Updated Work",
                "user_name": "Artist B",
                "user_id": 2000,
                "page_count": 1,
                "create_date": "2026-01-01",
                "update_date": "2026-02-01",  # 更新日が変わっている
                "type": "illust"
            },
            {
                "id": 202,
                "title": "Restored Work",
                "user_name": "Artist B",
                "user_id": 2000,
                "page_count": 1,
                "create_date": "2026-01-01",
                "update_date": "2026-01-01",
                "type": "illust"
            }
        ]
        mock_client.get_image_urls.return_value = ["https://example.com/test.jpg"]

        def mock_download(url, save_path):
            with open(save_path, "wb") as f:
                f.write(b"dummy image bytes")
        mock_client.download_image.side_effect = mock_download

        # 201は古い更新日で保存済み
        self.db.upsert_work("201", "2000", "Updated Work", 1, "2026-01-01", "2026-01-01")
        # 202は削除済みフラグで保存済み
        self.db.upsert_work("202", "2000", "Restored Work", 1, "2026-01-01", "2026-01-01")
        self.db.mark_as_deleted("202")

        stats = run_backup(
            user_id="2000",
            client=mock_client,
            db=self.db,
            is_full=False,
            target_type="illust",
            new_only=False
        )

        self.assertEqual(stats["updated_count"], 1)   # 201は更新
        self.assertEqual(stats["restored_count"], 1)  # 202は復帰

    def test_run_backup_deleted_detection(self):
        """Pixiv側からの作品削除検知(×)の集計テスト"""
        mock_client = MagicMock()
        mock_client.get_user_works.return_value = []  # 現在の作品0件

        # DB側には作品301が存在
        self.db.upsert_work("301", "3000", "Deleted Work", 1, "2026-01-01", "2026-01-01")

        stats = run_backup(
            user_id="3000",
            client=mock_client,
            db=self.db,
            is_full=False,
            target_type="illust",
            new_only=False
        )

        self.assertEqual(stats["deleted_count"], 1)   # 301が削除判定
        work = self.db.get_work("301")
        self.assertEqual(work["is_deleted"], 1)

if __name__ == "__main__":
    unittest.main()
