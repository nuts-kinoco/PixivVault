import time
import random
import logging
from typing import List, Dict, Any

import requests

logger = logging.getLogger(__name__)

class PixivClient:
    def __init__(self):
        self.session = requests.Session()
        # PixivのAPIを叩くための基本的なヘッダーを設定します。
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Referer': 'https://www.pixiv.net/',
            'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        })
        self._load_cookies()

    def _load_cookies(self):
        import os
        import http.cookiejar
        
        cookie_file = 'cookies.txt'
        
        if not os.path.exists(cookie_file):
            logger.error(f"「{cookie_file}」が見つかりません。")
            raise Exception(
                "自動取得がWindowsのセキュリティにブロックされてしまうため、手動エクスポート方式に変更しました。\n"
                "1. Chrome等のブラウザでPixivにログインします。\n"
                "2. 拡張機能「Get cookies.txt LOCALLY」等を使ってCookieをエクスポートします。\n"
                f"3. ダウンロードしたファイルを '{cookie_file}' という名前で、main.py と同じフォルダに配置してください。"
            )
            
        try:
            cj = http.cookiejar.MozillaCookieJar(cookie_file)
            cj.load(ignore_discard=True, ignore_expires=True)
            self.session.cookies.update(cj)
            
            # PixivのCookieが入っているか軽く確認します
            has_pixiv = any('pixiv.net' in cookie.domain for cookie in cj)
            if not has_pixiv:
                logger.warning(f"「{cookie_file}」にPixivのCookieが含まれていない可能性があります。")
                
            logger.info(f"{cookie_file} からPixivのCookieを読み込みました。")
        except Exception as e:
            logger.error(f"Cookieファイルの読み込みに失敗しました: {e}")
            raise

    def _request_with_retry(self, url: str, params: dict = None, max_retries: int = 3) -> dict:
        """APIリクエストを送信し、エラー時は指数バックオフで再試行します。"""
        for attempt in range(max_retries):
            try:
                # サーバーへの配慮（1〜3秒のランダムスリープ）
                sleep_time = random.uniform(1.0, 3.0)
                logger.debug(f"リクエスト前に {sleep_time:.2f} 秒待機します。")
                time.sleep(sleep_time)

                response = self.session.get(url, params=params, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                if data.get('error'):
                    error_msg = data.get('message', '不明なエラー')
                    logger.error(f"Pixiv APIからエラーが返ってきました: {error_msg}")
                    raise Exception(f"Pixiv APIエラー: {error_msg}")
                
                return data
            
            except (requests.RequestException, ValueError, Exception) as e:
                logger.warning(f"通信に失敗しました（{attempt + 1}/{max_retries}回目）: {e}")
                if attempt == max_retries - 1:
                    logger.error("最大リトライ回数に達しました。")
                    raise
                
                # 指数バックオフ (2^attempt + 乱数)
                backoff_time = (2 ** attempt) + random.uniform(0, 1)
                logger.info(f"{backoff_time:.2f}秒後に再挑戦します。")
                time.sleep(backoff_time)

    def get_user_works(self, user_id: str) -> List[Dict[str, Any]]:
        """指定したユーザーIDの作品一覧を取得します。"""
        logger.info(f"ユーザーID「{user_id}」の作品一覧を取得します。")
        
        # 1. まずは全作品IDを一括で取得
        profile_url = f"https://www.pixiv.net/ajax/user/{user_id}/profile/all"
        profile_data = self._request_with_retry(profile_url)
        
        body = profile_data.get('body', {})
        if not isinstance(body, dict):
            logger.info("このユーザーは作品を公開していないか、非公開アカウントのようです。")
            return []

        illusts = body.get('illusts', {}) or {}
        manga = body.get('manga', {}) or {}
        
        # イラストとマンガのIDを統合して降順（新しい順）にソートします
        work_ids = list(illusts.keys()) + list(manga.keys())
        work_ids.sort(key=int, reverse=True)
        
        if not work_ids:
            logger.info("取得できる作品が見当たりませんでした。")
            return []
            
        logger.info(f"合計 {len(work_ids)} 件の作品IDが見つかりました。詳細情報を取得します。")
        
        # 2. ページネーションで詳細情報を取得 (Pixivの仕様上、一度に最大48件ずつ)
        works_list = []
        chunk_size = 48
        
        for i in range(0, len(work_ids), chunk_size):
            chunk_ids = work_ids[i:i + chunk_size]
            logger.info(f"進捗: {i + 1} 〜 {min(i + chunk_size, len(work_ids))} 件目を確認中...")
            
            illusts_url = f"https://www.pixiv.net/ajax/user/{user_id}/profile/illusts"
            params = {
                'work_category': 'illustManga',
                'is_first_page': 1 if i == 0 else 0,
            }
            # IDのリストを "ids[]" パラメータとして複数渡すための処理
            params['ids[]'] = chunk_ids
            
            details_data = self._request_with_retry(illusts_url, params=params)
            works = details_data.get('body', {}).get('works', {})
            
            for work_id in chunk_ids:
                work_info = works.get(str(work_id))
                if work_info:
                    works_list.append({
                        'id': work_info.get('id'),
                        'title': work_info.get('title'),
                        'type': work_info.get('illustType', 0),
                        'user_name': work_info.get('userName', 'Unknown'),
                        'page_count': work_info.get('pageCount', 1),
                        'create_date': work_info.get('createDate', ''),
                        'update_date': work_info.get('updateDate', '')
                    })
                    
        logger.info(f"全 {len(works_list)} 件の作品データを取得しました。")
        return works_list

    def get_image_urls(self, work_id: str) -> List[str]:
        """作品IDからオリジナル画像のURLリストを取得します。"""
        url = f"https://www.pixiv.net/ajax/illust/{work_id}/pages"
        data = self._request_with_retry(url)
        
        pages = data.get('body', [])
        urls = []
        for page in pages:
            original_url = page.get('urls', {}).get('original')
            if original_url:
                urls.append(original_url)
                
        return urls

    def download_image(self, url: str, save_path: str):
        """画像のURLからデータをダウンロードし、ローカルに保存します。"""
        import os
        tmp_path = save_path + ".tmp"
        for attempt in range(3):
            try:
                # 負荷対策のためのランダムスリープ（1〜3秒）
                sleep_time = random.uniform(1.0, 3.0)
                logger.debug(f"画像ダウンロード前に {sleep_time:.2f} 秒待機します。")
                time.sleep(sleep_time)

                # i.pximg.net からのダウンロードには Referer が必須
                headers = {'Referer': 'https://www.pixiv.net/'}
                
                response = self.session.get(url, headers=headers, stream=True, timeout=15)
                response.raise_for_status()
                
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                
                with open(tmp_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # ダウンロード完了後に本来の名前にリネーム（安全な保存）
                os.replace(tmp_path, save_path)
                
                logger.info(f"画像の保存に成功しました: {os.path.basename(save_path)}")
                return
                
            except (requests.RequestException, ValueError, Exception) as e:
                # 失敗時は一時ファイルをクリーンアップ
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                        
                logger.warning(f"画像のダウンロードに失敗しました（{attempt + 1}/3回目）: {e}")
                if attempt == 2:
                    logger.error("最大リトライ回数に達しました。")
                    raise
                
                backoff_time = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(backoff_time)
