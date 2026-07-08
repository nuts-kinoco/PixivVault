import sys
import json
import os
sys.path.append(os.getcwd())
from pixiv_client import PixivClient

def test_novel_fetch():
    client = PixivClient()
    user_id = '2172727'
    print(f"Fetching profile for {user_id}...")
    
    profile_url = f"https://www.pixiv.net/ajax/user/{user_id}/profile/all"
    profile_data = client._request_with_retry(profile_url)
    body = profile_data.get('body', {})
    
    novels = body.get('novels', {})
    print(f"Found {len(novels)} novels.")
    
    if novels:
        novel_id = list(novels.keys())[0]
        print(f"Fetching novel details for {novel_id}...")
        novel_url = f"https://www.pixiv.net/ajax/novel/{novel_id}"
        novel_data = client._request_with_retry(novel_url)
        print("Novel Data Keys:", list(novel_data.keys()))
        print("Novel Body Keys:", list(novel_data['body'].keys()))
        
        content = novel_data['body'].get('content', '')
        print("Sample text:", content[:100])
        print("Text length:", len(content))
        
        seriesNavData = novel_data['body'].get('seriesNavData', {})
        print("Series info:", seriesNavData)

if __name__ == '__main__':
    test_novel_fetch()
