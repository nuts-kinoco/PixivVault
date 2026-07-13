import os
import shutil
import tempfile
import zipfile
import unittest
from database import Database
from core import verify_work_integrity
from pixiv_client import PixivClient

class TestPhase1(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_pixiv.db")
        self.db = Database(self.db_path)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_failed_queue_crud(self):
        # 1. 追加テスト
        self.db.add_failed_job("1001", "5001", "テスト作品1", "illust", "404 Not Found")
        jobs = self.db.get_failed_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["work_id"], "1001")
        self.assertEqual(jobs[0]["error_reason"], "404 Not Found")
        self.assertEqual(jobs[0]["retry_count"], 0)

        # 2. 上書き更新（リトライカウント増加）テスト
        self.db.add_failed_job("1001", "5001", "テスト作品1", "illust", "タイムアウト")
        jobs = self.db.get_failed_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["error_reason"], "タイムアウト")
        self.assertEqual(jobs[0]["retry_count"], 1)

        # 3. 複数件追加テスト
        self.db.add_failed_job("1002", "5002", "テスト作品2", "novel", "ZIP破損")
        jobs = self.db.get_failed_jobs()
        self.assertEqual(len(jobs), 2)

        # 4. 個別削除テスト
        self.db.remove_failed_job("1001")
        jobs = self.db.get_failed_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["work_id"], "1002")

        # 5. 全件削除テスト
        self.db.clear_failed_jobs()
        self.assertEqual(len(self.db.get_failed_jobs()), 0)

    def test_verify_work_integrity(self):
        # 1. 0バイトファイル検出
        zero_file = os.path.join(self.test_dir, "zero.txt")
        with open(zero_file, "w") as f:
            pass
        is_valid, reason = verify_work_integrity(zero_file)
        self.assertFalse(is_valid)
        self.assertIn("0バイトファイル検出", reason)

        # 2. 正常ZIP検証
        valid_zip = os.path.join(self.test_dir, "valid.zip")
        with zipfile.ZipFile(valid_zip, "w") as zf:
            zf.writestr("test.txt", "hello world")
        is_valid, reason = verify_work_integrity(valid_zip, is_zip=True)
        self.assertTrue(is_valid)
        self.assertIsNone(reason)

        # 3. 空ZIP検証
        empty_zip = os.path.join(self.test_dir, "empty.zip")
        with zipfile.ZipFile(empty_zip, "w") as zf:
            pass
        is_valid, reason = verify_work_integrity(empty_zip, is_zip=True)
        self.assertFalse(is_valid)
        self.assertIn("アーカイブ内部が空です", reason)

        # 4. 破損ZIP検証
        corrupt_zip = os.path.join(self.test_dir, "corrupt.zip")
        with open(corrupt_zip, "wb") as f:
            f.write(b"NOT A VALID ZIP DATA STR")
        is_valid, reason = verify_work_integrity(corrupt_zip, is_zip=True)
        self.assertFalse(is_valid)
        self.assertIn("ZIP破損検出", reason)

        # 5. フォルダ・ページ数不足検証
        work_dir = os.path.join(self.test_dir, "work1")
        os.makedirs(work_dir)
        with open(os.path.join(work_dir, "page1.jpg"), "w") as f:
            f.write("image data")
        is_valid, reason = verify_work_integrity(work_dir, expected_page_count=3)
        self.assertFalse(is_valid)
        self.assertIn("ページ不足", reason)

        is_valid, reason = verify_work_integrity(work_dir, expected_page_count=1)
        self.assertTrue(is_valid)

    def test_check_cookie_status_missing(self):
        missing_file = os.path.join(self.test_dir, "non_existent_cookies.txt")
        res = PixivClient.check_cookie_status(missing_file)
        self.assertEqual(res["status"], "missing")

if __name__ == "__main__":
    unittest.main()
