import os
import sqlite3
import tempfile
import pytest
from unittest.mock import MagicMock
from database import Database
from pixiv_client import PixivClient
import core

def test_author_settings_crud():
    """Phase 3: 作者個別設定(author_settings)のCRUD動作テスト"""
    db = Database(db_path=":memory:")
    
    # 未設定時はデフォルト値が返ること
    assert db.get_author_setting("12345", "target_type", "default") == "default"
    
    # 設定の保存
    db.set_author_setting("12345", "target_type", "novel")
    db.set_author_setting("12345", "auto_archive", "1")
    
    assert db.get_author_setting("12345", "target_type") == "novel"
    assert db.get_author_setting("12345", "auto_archive") == "1"
    
    # 全設定取得
    all_settings = db.get_all_author_settings("12345")
    assert all_settings == {"target_type": "novel", "auto_archive": "1"}
    
    # 更新
    db.set_author_setting("12345", "target_type", "illust")
    assert db.get_author_setting("12345", "target_type") == "illust"
    
    # 削除
    db.delete_author_setting("12345", "target_type")
    assert db.get_author_setting("12345", "target_type", None) is None
    assert db.get_author_setting("12345", "auto_archive") == "1"


def test_pixiv_client_rate_settings():
    """Phase 4: PixivClientがDatabaseの設定を正しく読み取れるかテスト"""
    db = Database(db_path=":memory:")
    db.set_setting("download_interval", "2.5")
    db.set_setting("api_retry_count", "5")
    db.set_setting("api_retry_wait", "10.0")
    
    client = PixivClient(db=db)
    interval, max_retries, retry_wait = client.get_rate_settings()
    assert interval == 2.5
    assert max_retries == 5
    assert retry_wait == 10.0


def test_run_backup_author_override():
    """Phase 3: run_backup実行時に作者個別オーバーライドが全体設定より優先適用されるかテスト"""
    db = Database(db_path=":memory:")
    db.set_author_setting("999", "target_type", "novel")
    
    client = MagicMock()
    client.get_user_works.return_value = []
    client.get_user_novels.return_value = []
    
    # 全体設定は "illust" でも、作者個別設定の "novel" が適用されて get_user_novels が呼ばれること
    core.run_backup("999", client, db, is_full=False, target_type="illust")
    
    client.get_user_novels.assert_called_once()
    client.get_user_works.assert_not_called()
