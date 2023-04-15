import os
from datetime import datetime

import requests

from graph import GraphAPI


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
    users = api.get_users()
    e5_id = ''
    recipients = []
    user_drive = api.get_drive(config['user_id'])
    for u in users:
        print(u['displayName'])
        if u['displayName'] == 'e5 renew':
            e5_id = u['id']
        try:
            photo = api.get_user_photo(u['id'])
            file_path = datetime.now().strftime('root:/%Y/%m/%d/%H-%M-%S-%f.png:')
            api.upload_file('application/jpg', photo, drive_id=user_drive, file_path=file_path)
            recipients.append({"emailAddress": {"address": u['mail']}})
        except Exception as e:
            print(e)
    if e5_id != '':
        drive = api.get_drive(e5_id)
        print(drive)
        items = api.get_drive_item(drive)
        for item in items:
            if item['name'] == 'Public':
                for d in api.get_drive_item(drive, item['id']):
                    print(d['name'])
                    res = requests.get(d['@microsoft.graph.downloadUrl'])
                    file_path = datetime.now().strftime('root:/%Y/%m/%d/%H-%M-%S-%f.png:')
                    api.upload_file('application/png', res.content, drive_id=user_drive, file_path=file_path)
        api.send_mail(
            e5_id, {
                "message": {
                    "subject": "api test",
                    "body": {
                        "contentType": "Text",
                        "content": "test"
                    },
                    "toRecipients": recipients,
                }
            })


if __name__ == '__main__':
    main()
