from enum import Enum
import json
from configparser import SectionProxy

import msal
import requests


class API:

    def __init__(self, name: str, url: str, method: str = 'get', host: str = 'https://graph.microsoft.com/v1.0'):
        self.name = name
        self.url = url
        self.host = host
        self.method = method


class APIEnum(Enum):
    authority = API('authority', '{host}/{tenant_id}', host='https://login.microsoftonline.com')
    users = API('users', '{host}/users')
    photo = API('photo', '{host}/users/{user_id}/photo/$value')
    drive = API('drive', '{host}/drives/{drive_id}')
    user_drive = API('user_drive', '{host}/users/{user_id}/drive')
    drive_item = API('drive_item', '{host}/drives/{drive_id}/items/{item_id}/children')
    send_mail = API('users', '{host}/users/{user_id}/sendMail', method='post')

    def get_url(self, **kwargs) -> str:
        return self.value.url.format(host=self.value.host, **kwargs)

    @property
    def method(self):
        return self.value.method


class GraphAPI:

    def __init__(self, config: SectionProxy):
        self.scope = ["https://graph.microsoft.com/.default"]
        self._app = msal.ConfidentialClientApplication(
            config["client_id"],
            authority=APIEnum.authority.get_url(tenant_id=config['tenant_id']),
            client_credential=config["secret"])
        self._session = requests.Session()
        self._token_header = {'Authorization': ''}
        self.get_access_token()

    def get_access_token(self):
        result = self._app.acquire_token_silent(self.scope, account=None)
        if not result:
            result = self._app.acquire_token_for_client(scopes=self.scope)
        if not result or result.get("access_token", '') == '':
            raise ValueError('failed to get access token')
        self._token_header['Authorization'] = result.get("access_token")

    def _request_graph(self, api: APIEnum, data_=None, json_=None, **kwargs):
        res: requests.Response = self._session.request(api.method,
                                                       api.get_url(**kwargs),
                                                       headers=self._token_header,
                                                       data=data_,
                                                       json=json_)
        if res.status_code == 401:
            self.get_access_token()
            return self._request_graph(api, data_, json_, **kwargs)
        if res.status_code >= 400:
            raise ValueError(f'request failed, code:{res.status_code}, response:{res.text}')
        if res.headers.get('content-type', '').startswith('application/json'):
            return json.loads(res.content)
        return res.content

    def get_users(self):
        return self._request_graph(APIEnum.users)['value']

    def get_user_photo(self, user_id):
        return self._request_graph(APIEnum.photo, user_id=user_id)

    def get_drive(self, user_id='', drive_id=''):
        if user_id != '':
            api = APIEnum.user_drive
        elif drive_id != '':
            api = APIEnum.drive
        return self._request_graph(api, user_id=user_id, drive_id=drive_id)['id']

    def get_drive_item(self, drive_id, item='root'):
        return self._request_graph(APIEnum.drive_item, drive_id=drive_id, item_id=item)['value']

    def send_mail(self, user_id, body):
        return self._request_graph(APIEnum.send_mail, json_=body, user_id=user_id)
