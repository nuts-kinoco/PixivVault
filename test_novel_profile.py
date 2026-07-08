import sys
import json
import os
sys.path.append(os.getcwd())
from pixiv_client import PixivClient

def test_novel_profile():
    client = PixivClient()
    user_id = '2172727'
    profile_url = f"https://www.pixiv.net/ajax/user/{user_id}/profile/all"
    profile_data = client._request_with_retry(profile_url)
    novels = profile_data.get('body', {}).get('novels', {})
    
    novel_ids = list(novels.keys())
    print("Novel IDs:", len(novel_ids))
    
    if novel_ids:
        chunk = novel_ids[:48]
        novels_url = f"https://www.pixiv.net/ajax/user/{user_id}/profile/novels"
        params = {
            'ids[]': chunk
        }
        res = client._request_with_retry(novels_url, params=params)
        print("Novels details keys:", list(res.get('body', {}).keys()))
        works = res.get('body', {}).get('works', {})
        print("Works fetched:", len(works))
        if works:
            sample = works[list(works.keys())[0]]
            print("Sample novel info:", json.dumps(sample, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    test_novel_profile()
