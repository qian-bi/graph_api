import json
from configparser import SectionProxy
from functools import partial
from pathlib import Path

import requests

from common import API, APIEnum

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
            raise ValueError(f'request failed, code:{res.status_code}, response:{res.text}')
        if res.headers.get('content-type', '').startswith('application/json'):
            return json.loads(res.content)
        return res.content

    def refresh_token(self):
        res = self._request_baidu(_BaiduURL.refresh_token, {
            'refresh_token': self._refresh_token,
            'client_id': self._client_id,
            'client_secret': self._client_secret
        })
        with open('refresh_token', 'w') as f:
            f.write(res['refresh_token'])
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

    def get_download_url(self, fs_id: int):
        fsids = f'[{fs_id}]'
        res = self._request_baidu(_BaiduURL.filemeta, params_={'fsids': fsids, 'dlink': 1})
        return res['list'][0]['dlink']

    def download(self, fs_id: int, file: Path):
        url = self.get_download_url(fs_id)
        with self._session.request('get', url, headers=self._header, params=self._token_params, stream=True) as r:
            with open(file, 'wb') as f:
                for content in r.iter_content(chunk_size=1048576):
                    f.write(content)