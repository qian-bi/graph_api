import json
from configparser import SectionProxy

import msal
import requests


class GraphAPI:
    _HOST = 'https://graph.microsoft.com/v1.0'
    _API = {
        'authority': 'https://login.microsoftonline.com/{tenant_id}',
        'users': '{host}/users',
        'photo': '{host}/users/{user_id}/photo/$value',
        'drive': '{host}/drives/{drive_id}',
        'user_drive': '{host}/users/{user_id}/drive',
        'drive_item': '{host}/drives/{drive_id}/items/{item_id}/children',
        'send_mail': '{host}/users/{user_id}/sendMail'
    }

    def __init__(self, config: SectionProxy):
        self.scope = config['scope']
        self._app = msal.ConfidentialClientApplication(
            config["client_id"],
            authority=self._API['authority'].format(tenant_id=config['tenant_id']),
            client_credential=config["secret"])
        self._token_header = {'Authorization': ''}
        self.get_access_token()

    def get_access_token(self):
        result = self._app.acquire_token_silent(self.scope, account=None)
        if not result:
            result = self._app.acquire_token_for_client(scopes=self.scope)
        if not result or result.get("access_token", '') == '':
            raise ValueError('failed to get access token')
        self._token_header['Authorization'] = result.get("access_token")

    def _request_graph(self, url, body=None):
        if body is not None:
            res: requests.Response = requests.post(url, json=body, headers=self._token_header)
        else:
            res: requests.Response = requests.get(url, headers=self._token_header)
        if res.status_code == 401:
            self.get_access_token()
            return self._request_graph(url, body)
        if res.status_code >= 400:
            raise ValueError(f'request failed, code:{res.status_code}, response:{res.text}')
        if res.headers.get('content-type', '').startswith('application/json'):
            return json.loads(res.content)
        return res.content

    def get_users(self):
        url = self._API['users'].format(host=self._HOST)
        return self._request_graph(url)['value']

    def get_user_photo(self, user_id):
        url = self._API['photo'].format(host=self._HOST, user_id=user_id)
        return self._request_graph(url)

    def get_drive(self, user_id='', drive_id=''):
        if user_id != '':
            url = self._API['user_drive'].format(host=self._HOST, user_id=user_id)
        elif drive_id != '':
            url = self._API['drive'].format(host=self._HOST, drive_id=drive_id)
        return self._request_graph(url)['id']

    def get_drive_item(self, drive_id, item='root'):
        url = self._API['drive_item'].format(host=self._HOST, drive_id=drive_id, item_id=item)
        return self._request_graph(url)['value']

    def send_mail(self, user_id, body):
        url = self._API['send_mail'].format(host=self._HOST, user_id=user_id)
        return self._request_graph(url, body)
