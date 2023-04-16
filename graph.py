import json
from configparser import SectionProxy
from enum import Enum

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
    user = API('user', '{host}/users/{user_id}')
    groups = API('users', '{host}/groups')
    group = API('user', '{host}/groups/{group_id}')
    group_member = API('user', '{host}/groups/{group_id}/members')
    group_owner = API('user', '{host}/groups/{group_id}/owners')
    photo = API('photo', '{host}/users/{user_id}/photo/$value')
    drive = API('drive', '{host}/drives/{drive_id}')
    user_drive = API('user_drive', '{host}/users/{user_id}/drive')
    drive_item = API('drive_item', '{host}/drives/{drive_id}/items/{item_id}/children')
    send_mail = API('users', '{host}/users/{user_id}/sendMail', method='post')
    upload_drive = API('upload_drive', '{host}/drives/{drive_id}/items/{file_path}/content', method='put')
    upload_user_drive = API('upload_user_drive', '{host}/users/{user_id}/drive/items/{file_path}/content', method='put')
    replace_drive = API('replace_drive', '{host}/drives/{drive_id}/items/{item_id}/content', method='put')
    replace_user_drive = API('replace_user_drive', '{host}/users/{user_id}/drive/items/{item_id}/content', method='put')

    def get_url(self, **kwargs) -> str:
        return self.value.url.format(host=self.value.host, **kwargs)

    @property
    def method(self) -> str:
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

    def _request_graph(self, api: APIEnum, data_=None, json_=None, headers: dict = None, **kwargs):
        if headers is None:
            headers = self._token_header
        else:
            headers.update(self._token_header)
        res: requests.Response = self._session.request(api.method,
                                                       api.get_url(**kwargs),
                                                       headers=headers,
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

    def get_users(self, user_id: str = ''):
        if user_id:
            return self._request_graph(APIEnum.user, user_id=user_id)
        return self._request_graph(APIEnum.users)['value']

    def get_user_photo(self, user_id: str):
        return self._request_graph(APIEnum.photo, user_id=user_id)

    def get_groups(self, group_id: str = ''):
        if group_id:
            return self._request_graph(APIEnum.group, group_id=group_id)
        return self._request_graph(APIEnum.groups)['value']

    def get_group_member(self, group_id: str):
        return self._request_graph(APIEnum.group_member, group_id=group_id)['value']

    def get_group_owner(self, group_id: str):
        return self._request_graph(APIEnum.group_owner, group_id=group_id)['value']

    def get_drive(self, user_id: str = '', drive_id: str = ''):
        if user_id != '':
            api = APIEnum.user_drive
        elif drive_id != '':
            api = APIEnum.drive
        else:
            raise ValueError('params illegal')
        return self._request_graph(api, user_id=user_id, drive_id=drive_id)['id']

    def get_drive_item(self, drive_id: str, item: str = 'root'):
        return self._request_graph(APIEnum.drive_item, drive_id=drive_id, item_id=item)['value']

    def send_mail(self, user_id: str, body):
        return self._request_graph(APIEnum.send_mail, json_=body, user_id=user_id)

    def upload_file(self,
                    content_type: str,
                    content: bytes,
                    drive_id: str = '',
                    file_path: str = '',
                    user_id: str = '',
                    item_id: str = ''):
        if drive_id != '':
            if file_path != '':
                api = APIEnum.upload_drive
            elif item_id != '':
                api = APIEnum.replace_drive
            else:
                raise ValueError('params illegal')
        elif user_id != '':
            if file_path != '':
                api = APIEnum.upload_user_drive
            elif item_id != '':
                api = APIEnum.replace_user_drive
            else:
                raise ValueError('params illegal')
        else:
            raise ValueError('params illegal')
        return self._request_graph(api,
                                   data_=content,
                                   headers={'content-type': content_type},
                                   drive_id=drive_id,
                                   file_path=file_path,
                                   user_id=user_id,
                                   item_id=item_id)
