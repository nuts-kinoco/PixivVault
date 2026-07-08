import sys
import json
import os
sys.path.append(os.getcwd())
from pixiv_client import PixivClient

def test_novel_images():
    client = PixivClient()
    user_id = '2172727'
    profile_url = f"https://www.pixiv.net/ajax/user/{user_id}/profile/all"
    profile_data = client._request_with_retry(profile_url)
    novels = profile_data.get('body', {}).get('novels', {})
    
    for nid in novels.keys():
        novel_url = f"https://www.pixiv.net/ajax/novel/{nid}"
        novel_data = client._request_with_retry(novel_url)
        body = novel_data.get('body', {})
        imgs = body.get('textEmbeddedImages')
        if imgs:
            print(f"Novel {nid} has embedded images:")
            print(json.dumps(imgs, indent=2, ensure_ascii=False))
            break
    print("Done checking novels for images.")

if __name__ == '__main__':
    test_novel_images()
