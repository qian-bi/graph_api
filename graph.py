import json
from configparser import SectionProxy
from functools import partial
from pathlib import Path

import msal
import requests

from common import API, APIEnum, RequestError, get_content

GraphHost = partial(API, host='https://graph.microsoft.com/v1.0')


class _GraphURL(APIEnum):
    authority = API('authority', '{host}/{tenant_id}', host='https://login.microsoftonline.com')
    users = GraphHost('users', '{host}/users')
    user = GraphHost('user', '{host}/users/{user_id}')
    groups = GraphHost('users', '{host}/groups')
    group = GraphHost('user', '{host}/groups/{group_id}')
    group_member = GraphHost('user', '{host}/groups/{group_id}/members')
    group_owner = GraphHost('user', '{host}/groups/{group_id}/owners')
    photo = GraphHost('photo', '{host}/users/{user_id}/photo/$value')
    drive = GraphHost('drive', '{host}/drives/{drive_id}')
    user_drive = GraphHost('user_drive', '{host}/users/{user_id}/drive')
    drive_item = GraphHost('drive_item', '{host}/drives/{drive_id}/items/{item_id}/children')
    drive_path = GraphHost('drive_path', '{host}/drives/{drive_id}/root:/{item_path}')
    send_mail = GraphHost('users', '{host}/users/{user_id}/sendMail', method='post')
    upload_drive = GraphHost('upload_drive', '{host}/drives/{drive_id}/items/{file_path}/content', method='put')
    upload_user_drive = GraphHost('upload_user_drive',
                                  '{host}/users/{user_id}/drive/items/{file_path}/content',
                                  method='put')
    replace_drive = GraphHost('replace_drive', '{host}/drives/{drive_id}/items/{item_id}/content', method='put')
    replace_user_drive = GraphHost('replace_user_drive',
                                   '{host}/users/{user_id}/drive/items/{item_id}/content',
                                   method='put')
    upload_session = GraphHost('create_upload_session',
                               '{host}/drives/{drive_id}/items/{item_id}/createUploadSession',
                               method='post')
    user_upload_session = GraphHost('upload_session',
                                    '{host}//users/{user_id}/drive/items/{item_id}/createUploadSession',
                                    method='post')
    list_applications = GraphHost('list_applications', '{host}/applications')
    get_application = GraphHost('get_application', '{host}/applications/{application_id}')


class GraphAPI:

    def __init__(self, config: SectionProxy):
        self.scope = ["https://graph.microsoft.com/.default"]
        self._app = msal.ConfidentialClientApplication(
            config["client_id"],
            authority=_GraphURL.authority.get_url(tenant_id=config['tenant_id']),
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

    def _request_graph(self, api: _GraphURL, data_=None, json_=None, headers: dict = None, **kwargs):
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
            return self._request_graph(api, data_, json_, headers, **kwargs)
        if res.status_code >= 400:
            raise RequestError(res.status_code, res.text, api.name)
        if res.headers.get('content-type', '').startswith('application/json'):
            return json.loads(res.content)
        return res.content

    def get_users(self, user_id: str = ''):
        if user_id:
            return self._request_graph(_GraphURL.user, user_id=user_id)
        return self._request_graph(_GraphURL.users)['value']

    def get_user_photo(self, user_id: str):
        return self._request_graph(_GraphURL.photo, user_id=user_id)

    def get_groups(self, group_id: str = ''):
        if group_id:
            return self._request_graph(_GraphURL.group, group_id=group_id)
        return self._request_graph(_GraphURL.groups)['value']

    def get_group_member(self, group_id: str):
        return self._request_graph(_GraphURL.group_member, group_id=group_id)['value']

    def get_group_owner(self, group_id: str):
        return self._request_graph(_GraphURL.group_owner, group_id=group_id)['value']

    def get_drive(self, user_id: str = '', drive_id: str = ''):
        if user_id != '':
            api = _GraphURL.user_drive
        elif drive_id != '':
            api = _GraphURL.drive
        else:
            raise ValueError('params illegal')
        return self._request_graph(api, user_id=user_id, drive_id=drive_id)['id']

    def get_drive_item(self, drive_id: str, item: str = 'root', item_path: str = ''):
        if item_path:
            return self._request_graph(_GraphURL.drive_path, drive_id=drive_id, item_path=item_path)
        return self._request_graph(_GraphURL.drive_item, drive_id=drive_id, item_id=item)['value']

    def get_item_content(self, drive_id: str, item: str = 'root', item_path: str = ''):
        file_item = self.get_drive_item(drive_id, item, item_path)
        res = self._session.get(file_item['@microsoft.graph.downloadUrl'])
        if res.status_code >= 400:
            raise RequestError(res.status_code, res.text, msg='get item failed')
        if res.content.startswith((b'[', b'{')):
            return json.loads(res.content)
        return res.content

    def send_mail(self, user_id: str, body):
        return self._request_graph(_GraphURL.send_mail, json_=body, user_id=user_id)

    def list_applications(self):
        return self._request_graph(_GraphURL.list_applications)['value']

    def get_application(self, application_id: str):
        return self._request_graph(_GraphURL.get_application, application_id=application_id)

    def create_upload_session(self, remote_path: str, user_id: str = '', drive_id: str = ''):
        if user_id != '' and drive_id == '':
            api = _GraphURL.user_upload_session
        elif user_id == '' and drive_id != '':
            api = _GraphURL.upload_session
        else:
            raise ValueError('params illegal')
        item_id = self.upload_content(b'', drive_id=drive_id, file_path=remote_path)['id']
        res = self._request_graph(api,
                                  json_={"item": {
                                      "@microsoft.graph.conflictBehavior": "replace"
                                  }},
                                  user_id=user_id,
                                  drive_id=drive_id,
                                  item_id=item_id)
        return res['uploadUrl']

    def upload_file(self, local_path: Path, remote_path: str, user_id: str = '', drive_id: str = ''):
        if user_id != '' and drive_id == '':
            api = _GraphURL.user_upload_session
        elif user_id == '' and drive_id != '':
            api = _GraphURL.upload_session
        else:
            raise ValueError('params illegal')
        item_id = self.upload_content(b'', drive_id=drive_id, file_path=remote_path)['id']
        file_size = local_path.stat().st_size
        res = self._request_graph(api,
                                  json_={"item": {
                                      "@microsoft.graph.conflictBehavior": "replace"
                                  }},
                                  user_id=user_id,
                                  drive_id=drive_id,
                                  item_id=item_id)
        upload_url = res['uploadUrl']
        with open(local_path, 'rb') as f:
            i = 0
            while True:
                data = f.read(1280 * 1024)
                if not data:
                    break
                upload_res = self._session.put(upload_url,
                                               data=data,
                                               headers={
                                                   'Content-Length': str(len(data)),
                                                   'Content-Range': f'bytes {i}-{i+len(data)-1}/{file_size}'
                                               })
                if upload_res.status_code >= 400:
                    raise RequestError(upload_res.status_code, upload_res.text, msg='upload failed')
                i += len(data)

    def upload_content(self,
                       content: bytes,
                       drive_id: str = '',
                       file_path: str = '',
                       user_id: str = '',
                       item_id: str = ''):
        if drive_id != '':
            if file_path != '':
                api = _GraphURL.upload_drive
            elif item_id != '':
                api = _GraphURL.replace_drive
            else:
                raise ValueError('params illegal')
        elif user_id != '':
            if file_path != '':
                api = _GraphURL.upload_user_drive
            elif item_id != '':
                api = _GraphURL.replace_user_drive
            else:
                raise ValueError('params illegal')
        else:
            raise ValueError('params illegal')
        content_type = get_content(file_path)
        return self._request_graph(api,
                                   data_=content,
                                   headers={'content-type': content_type},
                                   drive_id=drive_id,
                                   file_path=file_path,
                                   user_id=user_id,
                                   item_id=item_id)
