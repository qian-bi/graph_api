import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List

import requests

from baidu import BaiduAPI
from graph import GraphAPI
from utils import decrypt, encrypt, extract_files

TIME_FOAMAT = '/%Y/%m/%d/%H/'
TMP = Path(__file__).parent / 'tmp'
TMP.mkdir(exist_ok=True)


def get_users(api: GraphAPI):
    users = api.get_users()
    for u in users:
        logging.info('user_name: %s', u['displayName'])
        try:
            photo = api.get_user_photo(u['id'])
            with open(TMP / f'{u["displayName"]}.png', 'wb') as f:
                f.write(photo)
        except Exception as e:
            logging.error("get user failed, err: %s", e)


def get_groups(api: GraphAPI, user_id: str):
    groups = api.get_groups()
    for g in groups:
        logging.info('group_name: %s', g['displayName'])
        send_mail(api, user_id, [g['mail']])
        members = api.get_group_member(g['id'])
        send_mail(api, user_id, [m['mail'] for m in members])


def download_files(api: GraphAPI, user_id: str):
    drive = api.get_drive(user_id)
    logging.info('drive_id: %s', drive)
    items = api.get_drive_item(drive)
    for item in items:
        if item['name'] == 'Public':
            for d in api.get_drive_item(drive, item['id']):
                logging.info('file_name: %s', d['name'])
                res = requests.get(d['@microsoft.graph.downloadUrl'])
                with open(TMP / d["name"], 'wb') as f:
                    f.write(res.content)


def upload_files(api: GraphAPI, user_id: str):
    drive = api.get_drive(user_id)
    for p in TMP.glob('*'):
        folder = datetime.now().strftime(TIME_FOAMAT)
        file_path = 'root:' + folder + p.name + ':'
        with open(p, 'rb') as f:
            api.upload_content(f.read(), drive_id=drive, file_path=file_path)


def send_mail(api: GraphAPI, sender: str, to: List[str]):
    logging.info('recipients: %s', to)
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


def get_zip_list(baiduApi: BaiduAPI, graphApi: GraphAPI, drive: str):
    data = baiduApi.search_files('.zip', '/我的资源', recursion=1)['list']
    logging.debug(data)
    graphApi.upload_content(json.dumps(data), drive_id=drive, file_path='root:/compressed.txt:')


def upload_unzip(baiduApi: BaiduAPI, graphApi: GraphAPI, drive: str):
    compressed_list = graphApi.get_item_content(drive, item_path='compressed.txt')

    fs = compressed_list.pop(0)
    graphApi.upload_content(json.dumps(compressed_list), drive_id=drive, file_path='root:/compressed.txt:')
    logging.info('remote path: %s', fs['path'])
    try:
        temp_file = TMP / fs['server_filename']
        baiduApi.download(fs['fs_id'], temp_file)
        try:
            graphApi.upload_file(temp_file, f'root:{fs["path"]}:', drive_id=drive)
        except Exception as e:
            logging.error('upload zip failed, err: %s', e)
        extract_path = TMP / fs['path'][1:-4]
        extract_path.mkdir(exist_ok=True, parents=True)
        extract_files(temp_file, extract_path)
        path_len = len(str(extract_path)) + 1
        for file in extract_path.rglob('*'):
            if file.is_file():
                file_path = str(file)[path_len:]
                graphApi.upload_file(file, f'root:{fs["path"][:-4]}/{file_path}:', drive_id=drive)
    except Exception as e:
        logging.error('upload unzip failed, err: %s', e)
        compressed_list.append(fs)
        graphApi.upload_content(json.dumps(compressed_list), drive_id=drive, file_path='root:/compressed.txt:')


def main():
    log_format = '%(asctime)-15s\tThread info: %(threadName)s %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format, datefmt='%Y/%m/%d %H:%M:%S')
    graphConfig = {
        'client_id': os.getenv('client_id'),
        'tenant_id': os.getenv('tenant_id'),
        'secret': os.getenv('secret'),
        'user_id': os.getenv('user_id'),
    }
    for v in graphConfig.values():
        if not v:
            raise ValueError('config error')
    api = GraphAPI(graphConfig)
    get_users(api)
    get_groups(api, graphConfig['user_id'])
    download_files(api, graphConfig['user_id'])
    upload_files(api, graphConfig['user_id'])

    refresh_token = ''
    drive = api.get_drive(graphConfig['user_id'])

    def update_token(t):
        iv, ciphertext, tag = encrypt(os.getenv('refresh_token_key'), t, os.getenv('refresh_token_associated_data'))
        cipher_data = {'iv': iv, 'ciphertext': ciphertext, 'tag': tag}
        api.upload_content(json.dumps(cipher_data), drive_id=drive, file_path='root:/refresh_token.txt:')

    try:
        token_file = api.get_item_content(drive, item_path='refresh_token.txt')
        refresh_token = decrypt(os.getenv('refresh_token_key'), os.getenv('refresh_token_associated_data'),
                                **token_file)
    except ValueError as e:
        logging.error('update token failed, err: %s', e)

    baiduConfig = {
        'client_id': os.getenv('baidu_client_id'),
        'client_secret': os.getenv('baidu_client_secret'),
        'refresh_token': refresh_token or os.getenv('refresh_token'),
    }
    for v in baiduConfig.values():
        if not v:
            raise ValueError('config error')
    baiduApi = BaiduAPI(baiduConfig, update_token)
    upload_unzip(baiduApi, api, drive)


if __name__ == '__main__':
    main()
