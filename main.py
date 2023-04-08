import os
import requests
from pathlib import Path

from graph import GraphAPI


def main():
    config = {
        'client_id': os.getenv('client_id'),
        'tenant_id': os.getenv('tenant_id'),
        'secret': os.getenv('secret'),
    }
    if config['client_id'] == '' or config['tenant_id'] == '' or config['secret'] == '':
        raise ValueError('config error')
    api = GraphAPI(config)
    users = api.get_users()
    e5_id = ''
    photo_path = Path(__file__).parent / 'photo'
    photo_path.mkdir(exist_ok=True)
    recipients = []
    for u in users:
        print(u['displayName'])
        if u['displayName'] == 'e5 renew':
            e5_id = u['id']
        recipients.append({"emailAddress": {"address": u['mail']}})
        try:
            photo = api.get_user_photo(u['id'])
            with open(photo_path / f'{u["displayName"]}.jpg', 'wb') as f:
                f.write(photo)
        except Exception as e:
            print(e)
    if e5_id != '':
        drive = api.get_drive(e5_id)
        print(drive)
        items = api.get_drive_item(drive)
        for item in items:
            if item['name'] == 'Public':
                for d in api.get_drive_item(drive, item['id']):
                    res = requests.get(d['@microsoft.graph.downloadUrl'])
                    with open(photo_path / {d["name"]}, 'wb') as f:
                        f.write(res.content)
        api.send_mail(
            e5_id, {
                "message": {
                    "subject": "api test",
                    "body": {
                        "contentType": "Text",
                        "content": "test"
                    },
                    "toRecipients": recipients,
                    "ccRecipients": [{
                        "emailAddress": {
                            "address": "qianbi@x1690.onmicrosoft.com"
                        }
                    }]
                }
            })


if __name__ == '__main__':
    main()
