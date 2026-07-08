import os
import re
import json
import shutil
import logging
import time
import zipfile
from datetime import datetime
from database import Database
from pixiv_client import PixivClient

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', '_', name)

def append_to_zip(author_dir: str, zip_path: str, log_callback=None):
    """ディレクトリ内のファイルをZIPファイルの末尾に追加し、追加した元ファイルを削除します"""
    if not os.path.exists(author_dir):
        return
        
    try:
        if log_callback:
            log_callback(f"Zipファイルに追加しています: {os.path.basename(zip_path)}", "INFO")
        
        # 'a' (Append) モードでZIPを開く。ファイルが無い場合は自動作成される。
        with zipfile.ZipFile(zip_path, 'a', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(author_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, author_dir)
                    zipf.write(file_path, arcname)
                    
        # ZIP追加が成功したら元フォルダを削除
        shutil.rmtree(author_dir)
        if log_callback:
            log_callback(f"Zip化が完了し、一時フォルダを削除しました。", "INFO")
    except Exception as e:
        if log_callback:
            log_callback(f"Zip化に失敗しました: {e}", "ERROR")

def run_backup(user_id: str, client: PixivClient, db: Database, is_full: bool = False, target_type: str = "both", log_callback=None, progress_callback=None, alert_callback=None, stop_event=None, pause_event=None):
    logger = logging.getLogger(__name__)
    
    def log(msg, level="INFO"):
        if level == "INFO":
            logger.info(msg)
        elif level == "WARNING":
            logger.warning(msg)
        elif level == "ERROR":
            logger.error(msg)
        elif level == "DEBUG":
            logger.debug(msg)
            return
        
        if log_callback:
            log_callback(msg)
            
    def alert(msg):
        logger.warning(msg)
        if alert_callback:
            alert_callback(msg)
        elif log_callback:
            log_callback(f"⚠️ {msg}")

    def check_state():
        if stop_event and stop_event.is_set():
            raise Exception("処理がユーザーによって中止されました。")
        if pause_event and pause_event.is_set():
            log("処理を一時停止しています...", "INFO")
            while pause_event.is_set():
                if stop_event and stop_event.is_set():
                    raise Exception("処理がユーザーによって中止されました。")
                pause_event.wait(timeout=1.0)
            log("処理を再開します。", "INFO")

    check_state()
    # 【フェーズA】Pixivから最新の作品一覧を取得
    log(f"【フェーズA】Pixivから最新の作品一覧({target_type})を取得します。")
    current_works = []
    if target_type in ("illust", "both"):
        current_works.extend(client.get_user_works(user_id))
    if target_type in ("novel", "both"):
        current_works.extend(client.get_user_novels(user_id))
    
    if not current_works:
        log("保存対象の作品がありませんでした。")
        return
        
    current_work_ids = {str(w['id']) for w in current_works}
    
    check_state()
    # 【フェーズB】削除検知
    log("【フェーズB】DBと比較し、Pixivから削除された作品がないか検知します。")
    db_work_ids = db.get_user_work_ids(user_id)
    deleted_ids = db_work_ids - current_work_ids
    
    for d_id in deleted_ids:
        work_record = db.get_work(d_id)
        if work_record and not work_record['is_deleted']:
            db.mark_as_deleted(d_id)
            alert(f"以下の作品がPixivから削除されている可能性があります: {work_record['title']} (ID: {d_id})")
            
    check_state()
    # 【フェーズC】新規・更新分（または全件）ダウンロード
    log("【フェーズC】画像のダウンロードとDBの更新を行います。")
    base_img_dir = db.get_setting("save_path", "Images")
    total = len(current_works)
    
    start_time = time.perf_counter()
    
    for idx, work in enumerate(current_works, 1):
        check_state()
        if progress_callback:
            elapsed = time.perf_counter() - start_time
            progress_callback(idx, total, elapsed)
            
        work_id = str(work['id'])
        title = work.get('title', '無題')
        user_name = work.get('user_name', 'Unknown')
        page_count = work.get('page_count', 1)
        create_date = work.get('create_date', '')
        update_date = work.get('update_date', '')
        
        db_record = db.get_work(work_id)
        needs_download = False
        
        if is_full:
            log(f"[{idx}/{total}] 完全チェック: ID: {work_id} 「{title}」")
            needs_download = True
        else:
            if not db_record:
                log(f"[{idx}/{total}] 新規作品を発見！ ID: {work_id} 「{title}」")
                needs_download = True
            elif db_record['update_date'] != update_date:
                log(f"[{idx}/{total}] 更新された作品を発見！ ID: {work_id} 「{title}」")
                needs_download = True
            elif db_record['is_deleted']:
                log(f"[{idx}/{total}] 削除状態から復帰した作品を発見！ ID: {work_id} 「{title}」")
                needs_download = True
            else:
                continue
            
        if needs_download:
            try:
                work_type = work.get('type', 'illust')
                safe_title = sanitize_filename(title)
                safe_user_name = sanitize_filename(user_name)
                author_dir_name = f"{safe_user_name}({user_id})"
                work_img_dir = os.path.join(base_img_dir, author_dir_name)
                os.makedirs(work_img_dir, exist_ok=True)
                
                if work_type == 'novel':
                    novel_data = client.get_novel_text(work_id)
                    content = novel_data.get('content', '')
                    
                    # 挿絵の処理とダウンロード
                    embedded_images = novel_data.get('textEmbeddedImages', {})
                    if embedded_images:
                        novel_img_dir = os.path.join(work_img_dir, "images")
                        os.makedirs(novel_img_dir, exist_ok=True)
                        for img_id, img_info in embedded_images.items():
                            original_url = img_info.get('urls', {}).get('original')
                            if original_url:
                                ext = os.path.splitext(original_url.split('?')[0])[1] or '.jpg'
                                img_filename = f"{img_id}{ext}"
                                save_path = os.path.join(novel_img_dir, img_filename)
                                if not os.path.exists(save_path):
                                    client.download_image(original_url, save_path)
                                content = content.replace(f"[uploadedimage:{img_id}]", f"[挿絵: images/{img_filename}]")
                    
                    # ルビの変換 [[rb:漢字 > かんじ]] → 漢字《かんじ》
                    content = re.sub(r'\[\[rb:(.*?) > (.*?)\]\]', r'\1《\2》', content)
                    
                    file_name = f"{work_id}_{safe_title}.txt"
                    file_path = os.path.join(work_img_dir, file_name)
                    
                    with open(file_path, 'w', encoding='utf-8-sig') as f:
                        f.write(content)
                        
                    db.upsert_work(work_id, user_id, title, page_count, create_date, update_date, content_type='novel')
                    log(f"小説の保存に成功しました: {file_name}", "DEBUG")
                    
                else:
                    img_urls = client.get_image_urls(work_id)
                    if not img_urls:
                        log(f"作品ID: {work_id} の画像URLが見つかりませんでした。", "WARNING")
                        continue
                    
                    for page_idx, img_url in enumerate(img_urls):
                        check_state()
                        ext = os.path.splitext(img_url.split('?')[0])[1]
                        if not ext:
                            ext = '.jpg'
                            
                        if len(img_urls) == 1:
                            filename = f"{safe_title}{ext}"
                        else:
                            filename = f"{safe_title}_{page_idx + 1}{ext}"
                            
                        save_path = os.path.join(work_img_dir, filename)
                        
                        if os.path.exists(save_path):
                            log(f"画像は既に存在するためスキップします: {filename}", "DEBUG")
                        else:
                            client.download_image(img_url, save_path)
                            log(f"画像の保存に成功しました: {filename}", "DEBUG")
                    
                    # 全ページの確認・ダウンロードが成功したらDBを更新 (upsert_work内部でcommitされる)
                    db.upsert_work(work_id, user_id, title, page_count, create_date, update_date, content_type='illust')
                
            except Exception as e:
                if stop_event and stop_event.is_set():
                    raise
                log(f"作品ID: {work_id} の処理中にエラーが発生しました: {e}", "ERROR")
                continue

    # 【フェーズD】ダウンロード完了後のZip化判定と実行
    zip_all = db.get_setting("zip_all_after_download", "0") == "1"
    is_zipped = False
    cursor = db.conn.execute("SELECT is_zipped FROM following_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row['is_zipped']:
        is_zipped = True

    if zip_all or is_zipped:
        # DBなどからuserNameが取得できている場合は使う。そうでなければ user_id。
        # ここではループ内の最後の work から user_name を拾うか、取得済みの author_dir_name があれば使う。
        if 'author_dir_name' in locals():
            zip_target_dir = os.path.join(base_img_dir, author_dir_name)
            zip_target_path = os.path.join(base_img_dir, f"{author_dir_name}.zip")
            if os.path.exists(zip_target_dir):
                log(f"Zip圧縮（追記）を実行します: {zip_target_path}")
                append_to_zip(zip_target_dir, zip_target_path, log_callback=log)

def run_batch_backup(user_ids: list[str], client: PixivClient, db: Database, is_full: bool = False, target_type: str = "both",
                     log_callback=None, progress_callback=None, alert_callback=None, 
                     stop_event=None, pause_event=None, batch_progress_callback=None):
    logger = logging.getLogger(__name__)
    
    def log(msg, level="INFO"):
        if level == "INFO":
            logger.info(msg)
        elif level == "ERROR":
            logger.error(msg)
        if log_callback:
            log_callback(msg)
            
    def check_state():
        if stop_event and stop_event.is_set():
            raise Exception("一括処理がユーザーによって中止されました。")
        if pause_event and pause_event.is_set():
            log("一括処理を一時停止しています...")
            while pause_event.is_set():
                if stop_event and stop_event.is_set():
                    raise Exception("一括処理がユーザーによって中止されました。")
                pause_event.wait(timeout=1.0)
            log("一括処理を再開します。")

    total_users = len(user_ids)
    batch_start_time = time.perf_counter()
    for idx, user_id in enumerate(user_ids, 1):
        check_state()
        if batch_progress_callback:
            elapsed = time.perf_counter() - batch_start_time
            batch_progress_callback(idx, total_users, user_id, elapsed)
            
        log(f"--- [{idx}/{total_users}] ユーザーID: {user_id} の処理を開始します ---")
        try:
            run_backup(
                user_id=user_id, client=client, db=db, is_full=is_full, target_type=target_type,
                log_callback=log_callback, progress_callback=progress_callback,
                alert_callback=alert_callback, stop_event=stop_event, pause_event=pause_event
            )
            # 完了したらDBに最終ダウンロード日時を記録
            db.update_following_last_downloaded(user_id)
            
        except Exception as e:
            if stop_event and stop_event.is_set():
                raise
            log(f"ユーザーID: {user_id} の処理中にエラーが発生しました: {e}", "ERROR")
            
        # 次のユーザーへ移行する前に3〜5秒スリープしてサーバー負荷を軽減
        if idx < total_users:
            check_state()
            sleep_time = 3.0
            log(f"サーバー負荷軽減のため {sleep_time} 秒待機します...")
            time.sleep(sleep_time)
            
    log("一括ダウンロードがすべて完了しました！")

def export_data(db: Database, log_callback=None):
    logger = logging.getLogger(__name__)
    
    def log(msg, level="INFO"):
        if level == "INFO":
            logger.info(msg)
        elif level == "ERROR":
            logger.error(msg)
            
        if log_callback:
            log_callback(msg)
            
    log("エクスポート処理を開始します。")
    
    timestamp = datetime.now().strftime("%Y%m%d")
    export_dir = f"PixivVault_Backup_{timestamp}"
    zip_name = f"{export_dir}.zip"
    
    try:
        os.makedirs(export_dir, exist_ok=True)
        
        log("メタデータのJSONダンプを作成しています...")
        works_data = []
        cursor = db.conn.execute("SELECT * FROM works")
        for row in cursor.fetchall():
            works_data.append(dict(row))
            
        json_path = os.path.join(export_dir, "metadata.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(works_data, f, ensure_ascii=False, indent=4)
            
        log("データベースファイルをコピーしています...")
        if os.path.exists("pixiv_vault.db"):
            shutil.copy2("pixiv_vault.db", os.path.join(export_dir, "pixiv_vault.db"))
            
        log("画像フォルダをコピーしています（これには時間がかかる場合があります）...")
        if os.path.exists("Images"):
            shutil.copytree("Images", os.path.join(export_dir, "Images"), dirs_exist_ok=True)
            
        log(f"アーカイブ {zip_name} を作成しています...")
        shutil.make_archive(export_dir, 'zip', export_dir)
        
        log(f"エクスポートが完了しました: {zip_name}")
        
    finally:
        if os.path.exists(export_dir):
            shutil.rmtree(export_dir)
