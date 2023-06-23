import asyncio
import json
import logging
from configparser import SectionProxy
from functools import partial
from pathlib import Path

import aiohttp
import requests

from common import API, APIEnum, RequestError
from utils import ThreadDownload

BaiduHost = partial(API, host='https://pan.baidu.com')


class _BaiduURL(APIEnum):
    refresh_token = API('refresh_token',
                        '{host}/oauth/2.0/token?grant_type=refresh_token&openapi=xpansdk',
                        host='https://openapi.baidu.com')
    listall = BaiduHost('listall', '{host}/rest/2.0/xpan/multimedia?method=listall')
    filemeta = BaiduHost('filemeta', '{host}/rest/2.0/xpan/multimedia?method=filemetas&openapi=xpansdk')
    pre_create = BaiduHost('pre_create', '{host}/rest/2.0/xpan/file?method=precreate&openapi=xpansdk', method='post')
    upload = BaiduHost('upload', '{host}/rest/2.0/pcs/superfile2?method=upload&openapi=xpansdk', method='post')
    create = BaiduHost('create', '{host}/rest/2.0/xpan/file?method=create&openapi=xpansdk', method='post')
    search = BaiduHost('search', '{host}/rest/2.0/xpan/file?method=search&openapi=xpansdk')


class BaiduAPI:

    def __init__(self, config: SectionProxy, update_token=None):
        self._session = requests.Session()
        self._header = {'User-Agent': 'pan.baidu.com'}
        self._refresh_token = config['refresh_token']
        if not self._refresh_token:
            raise ValueError('refresh token empty')
        self._client_id = config['client_id']
        self._client_secret = config['client_secret']
        self._token_params = {'access_token': ''}
        self.update_token = update_token
        self.refresh_token()

    def _request_baidu(self, api: _BaiduURL, params_=None, data_=None, json_=None, headers: dict = None, **kwargs):
        if headers is None:
            headers = self._header
        else:
            headers.update(self._header)
        if params_ is None:
            params_ = self._token_params
        else:
            params_.update(self._token_params)
        res: requests.Response = self._session.request(api.method,
                                                       api.get_url(**kwargs),
                                                       headers=headers,
                                                       params=params_,
                                                       data=data_,
                                                       json=json_)
        if res.status_code == 401:
            self.refresh_token()
            return self._request_baidu(api, params_, data_, json_, headers, **kwargs)
        if res.status_code >= 400:
            raise RequestError(res.status_code, res.text, api.name)
        if res.headers.get('content-type', '').startswith('application/json'):
            return json.loads(res.content)
        return res.content

    def refresh_token(self):
        res = self._request_baidu(_BaiduURL.refresh_token, {
            'refresh_token': self._refresh_token,
            'client_id': self._client_id,
            'client_secret': self._client_secret
        })
        if self.update_token:
            self.update_token(res['refresh_token'])
        self._token_params['access_token'] = res['access_token']

    def list_all(self, path: str, recursion: int = 0, start: int = 0):
        res = self._request_baidu(_BaiduURL.listall, params_={'path': path, 'recursion': recursion, 'start': start})
        return res

    def search_files(self, key: str, dir: str = '', page: int = 1, num: int = 500, recursion: int = 0):
        params = {'key': key, 'dir': dir, 'page': page, 'num': num, 'recursion': recursion}
        res = self._request_baidu(_BaiduURL.search, params_=params)
        return res

    def get_filemeta(self, fs_id: int):
        fsids = f'[{fs_id}]'
        res = self._request_baidu(_BaiduURL.filemeta, params_={'fsids': fsids, 'dlink': 1})
        return res['list'][0]

    def download(self, fs_id: int, file: Path):
        filemeta = self.get_filemeta(fs_id)
        url = filemeta['dlink']
        size = filemeta['size']
        ThreadDownload(size, url, file, headers=self._header, params=self._token_params).run()

    async def get_file_content(self, queue: asyncio.Queue, fs_id: int, next_byte: int, concurrency: int = 3):
        filemeta = self.get_filemeta(fs_id)
        url = filemeta['dlink']
        size = filemeta['size']
        async with aiohttp.ClientSession() as sess:
            for i in range(next_byte, size, 1310720 * concurrency):
                tasks = [
                    sess.get(url,
                             headers={
                                 'Range': f'bytes={i+1310720*c}-{i+1310720*c+1310719}',
                                 'User-Agent': 'pan.baidu.com'
                             },
                             params=self._token_params) for c in range(concurrency) if i + 1310720 * c < size
                ]
                for res in await asyncio.gather(*tasks, return_exceptions=True):
                    if isinstance(res, Exception):
                        logging.error('download failed, err:%s', res)
                        await queue.put((True, None, None))
                        raise res
                    if res.status >= 400:
                        logging.error('download failed')
                        text = await res.text()
                        await queue.put((True, None, None))
                        raise RequestError(res.status, text)
                    data = await res.read()
                    await queue.put((False, res.headers, data))
                    res.close()
        await queue.put((True, None, None))
