import os
from datetime import datetime
from pathlib import Path
from typing import List

import requests

from graph import GraphAPI

TIME_FOAMAT = '/%Y/%m/%d/%H'
TMP = Path(__file__).parent / 'tmp'
TMP.mkdir(exist_ok=True)


def get_users(api: GraphAPI):
    users = api.get_users()
    for u in users:
        print('user_name', u['displayName'])
        try:
            photo = api.get_user_photo(u['id'])
            with open(TMP / f'{u["displayName"]}.png', 'wb') as f:
                f.write(photo)
        except Exception as e:
            print(e)


def get_groups(api: GraphAPI, user_id: str):
    groups = api.get_groups()
    for g in groups:
        print('group_name', g['displayName'])
        send_mail(api, user_id, [g['mail']])
        members = api.get_group_member(g['id'])
        send_mail(api, user_id, [m['mail'] for m in members])


def download_files(api: GraphAPI, user_id: str):
    drive = api.get_drive(user_id)
    print('drive_id', drive)
    items = api.get_drive_item(drive)
    for item in items:
        if item['name'] == 'Public':
            for d in api.get_drive_item(drive, item['id']):
                print('file_name', d['name'])
                res = requests.get(d['@microsoft.graph.downloadUrl'])
                with open(TMP / d["name"], 'wb') as f:
                    f.write(res.content)


def upload_files(api: GraphAPI, user_id: str):
    drive = api.get_drive(user_id)
    for p in TMP.glob('*'):
        folder = datetime.now().strftime(TIME_FOAMAT)
        file_path = 'root:' + folder + p.name + ':'
        with open(p, 'rb') as f:
            api.upload_file(f.read(), drive_id=drive, file_path=file_path)


def send_mail(api: GraphAPI, sender: str, to: List[str]):
    print('recipients', to)
    recipients = [{"emailAddress": {"address": a}} for a in to]
    api.send_mail(
        sender, {
            "message": {
                "subject": "api test",
                "body": {
                    "contentType": "Text",
                    "content": "test"
                },
                "toRecipients": recipients,
            }
        })


def main():
    config = {
        'client_id': os.getenv('client_id'),
        'tenant_id': os.getenv('tenant_id'),
        'secret': os.getenv('secret'),
        'user_id': os.getenv('user_id'),
    }
    for v in config.values():
        if not v:
            raise ValueError('config error')
    api = GraphAPI(config)
    get_users(api)
    get_groups(api, config['user_id'])
    download_files(api, config['user_id'])
    upload_files(api, config['user_id'])


if __name__ == '__main__':
    main()
