import asyncio
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import aiohttp
import requests

from baidu import BaiduAPI
from common import RequestError, TimeOutError
from graph import GraphAPI
from utils import decrypt, encrypt, extract_files

TIME_FOAMAT = '/%Y/%m/%d/%H/'
TMP = Path(__file__).parent / 'tmp'
TMP.mkdir(exist_ok=True)
REGEX = re.compile('[\\|:"<>?#$%^&*]')
TIMEOUT = 18000


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
                if res.status_code >= 400:
                    raise RequestError(res.status_code, res.text, msg='get file failed')
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


def get_current_file(graphApi: GraphAPI, drive: str) -> Tuple[dict, int]:
    current_file = graphApi.get_item_content(drive, item_path='baidu_current_file.txt')
    res = requests.get(current_file['upload_url'])
    if res.status_code == 404:
        logging.info('current file finished')
        return None, 0
    if res.status_code == 401:
        logging.warn('unauthorized upload for %s, restart', current_file['server_filename'])
        upadte_current_file(graphApi, drive, current_file)
        return current_file, 0
    if res.status_code >= 400:
        logging.error('failed to check file %s', current_file['server_filename'])
        raise RequestError(res.status_code, res.text)
    data = json.loads(res.content)
    if len(data['nextExpectedRanges']) == 0:
        index = 0
    else:
        next_range = data['nextExpectedRanges'][0]
        index = int(next_range[0:next_range.index('-')])
    return current_file, index


def get_next_file(baiduApi: BaiduAPI, graphApi: GraphAPI, drive: str) -> dict:
    file_list = graphApi.get_item_content(drive, item_path='baidu_file_list.txt')
    if not file_list['list']:
        if not file_list['has_more']:
            return None
        page = file_list['next_page']
        file_list = baiduApi.search_files('.', '/', page=page, recursion=1)
        file_list['next_page'] = page + 1
    logging.info('total list: %d', len(file_list['list']))
    current_file = {'isdir': 1}
    while current_file['isdir']:
        if not file_list['list']:
            return get_next_file(baiduApi, graphApi, drive)
        current_file = file_list['list'].pop()
    upadte_current_file(graphApi, drive, current_file)
    graphApi.upload_content(json.dumps(file_list), drive_id=drive, file_path='root:/baidu_file_list.txt:')
    return current_file


def upadte_current_file(graphApi: GraphAPI, drive: str, current_file: dict) -> None:
    path = REGEX.sub('', current_file["path"])
    current_file['upload_url'] = graphApi.create_upload_session(f'root:{path}:', drive_id=drive)
    current_file['download_start_time'] = time.time()
    graphApi.upload_content(json.dumps(current_file), drive_id=drive, file_path='root:/baidu_current_file.txt:')


def put_nowait(queue: asyncio.Queue, item):
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        pass


async def transport_file(queue: asyncio.Queue, exit_queue: asyncio.Queue, start_time: float):
    upload_headers = {}
    async with aiohttp.ClientSession() as sess:
        while True:
            if time.time() - start_time >= TIMEOUT:
                put_nowait(exit_queue, 0)
                logging.info('exit upload')
                return
            try:
                finished, fs, resp_headers, data = await queue.get()
                if finished:
                    logging.info('file %s finished, size: %d, avg_rate: %.2f', fs['server_filename'], fs['size'],
                                 fs['size'] / (time.time() - fs['download_start_time']) / 1024)
                    continue
                upload_headers['Content-Length'] = resp_headers['Content-Length']
                upload_headers['Content-Range'] = resp_headers['Content-Range']
                async with sess.put(fs['upload_url'], data=data, headers=upload_headers) as upload_res:
                    if upload_res.status >= 400:
                        logging.error('upload failed, code:%d, resp:%s', upload_res.status, await upload_res.text())
                        put_nowait(exit_queue, 0)
            except Exception as e:
                put_nowait(exit_queue, 0)
                logging.error('upload failed, err:%s', e)


async def baidu_to_onedrive(baiduApi: BaiduAPI, graphApi: GraphAPI, drive: str):
    start_time = time.time()
    queue = asyncio.Queue(maxsize=10)
    exit_queue = asyncio.Queue(maxsize=1)
    asyncio.create_task(transport_file(queue, exit_queue, start_time))
    while True:
        try:
            if time.time() - start_time >= TIMEOUT:
                logging.info('exit transport')
                return
            current_file, next_byte = get_current_file(graphApi, drive)
            if current_file is None:
                current_file = get_next_file(baiduApi, graphApi, drive)
            if current_file is None:
                return
            logging.info('transport file: %s', current_file['path'])
            await baiduApi.get_file_content(queue, current_file, next_byte, exit_queue)
        except TimeOutError:
            return
        except Exception as e:
            logging.error('transport file to onedrive failed,file:%s, err:%s', current_file, e)
        await asyncio.sleep(random.randint(200, 300))


def main():
    time.sleep(random.randint(600, 1800))
    log_format = '%(asctime)-15s\t|\t%(levelname)s\t|\t%(filename)s:%(lineno)d\t|\t %(message)s'
    logging.basicConfig(level=logging.INFO, format=log_format, datefmt='%Y/%m/%d %H:%M:%S')
    if len(sys.argv) != 2:
        logging.error('invalid params %s', sys.argv)
        return
    job = sys.argv[1]
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
    if job == 'graph_test':
        get_users(api)
        get_groups(api, graphConfig['user_id'])
        # download_files(api, graphConfig['user_id'])
        # upload_files(api, graphConfig['user_id'])
    elif job == 'baidu_to_onedrive':
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
        except RequestError as e:
            logging.error('update token failed, err: %s', e)
            return

        baiduConfig = {
            'client_id': os.getenv('baidu_client_id'),
            'client_secret': os.getenv('baidu_client_secret'),
            'refresh_token': refresh_token or os.getenv('refresh_token'),
        }
        for v in baiduConfig.values():
            if not v:
                raise ValueError('config error')
        baiduApi = BaiduAPI(baiduConfig, update_token)
        asyncio.run(baidu_to_onedrive(baiduApi, api, drive))


if __name__ == '__main__':
    main()
