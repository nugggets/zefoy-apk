"""Zefoy automator core (refactored from plowside/Zefoy_TIKTOK_BOT).

No input()/print()/ctypes: all output goes through the `log` callback, captcha
can be solved manually through `captcha_handler`, and the loop can be stopped
at any time via `stop()`.
"""
import base64
import json
import os
import random
import re
import threading
import time
from string import ascii_letters, digits
from urllib.parse import urlparse, unquote

import requests

# tls_client ships a native Go library that does not work on Android,
# so there we silently fall back to plain `requests`.
try:
    if 'ANDROID_ARGUMENT' in os.environ:
        raise ImportError('android')
    import tls_client
except Exception:
    tls_client = None

BASE_URL = 'https://zefoy.com/'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36')
CAPTCHA_API = 'https://plowsidecaptcha.pythonanywhere.com/captcha'
DEFAULT_SERVICES = ['Followers', 'Hearts', 'Comments Hearts', 'Views', 'Shares', 'Favorites']
DEFAULT_CONFIG = {
    'url': '',
    'service': 'Views',
    'comment_id': None,
    'proxy': None,
    'captcha_auto_solve': True,
}


class StopBot(Exception):
    """Raised inside the worker when the user pressed Stop."""


class ConfigError(Exception):
    """Fatal problem with user input (bad URL etc.), no point in retrying."""


def _decode(text):
    return base64.b64decode(unquote(text.encode()[::-1])).decode()


class Zefoy:
    def __init__(self, data_dir='.', log=print, captcha_handler=None,
                 on_services=None, on_finish=None):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.log = log
        self.captcha_handler = captcha_handler
        self.on_services = on_services
        self.on_finish = on_finish
        self.stop_event = threading.Event()

        self.headers = {'user-agent': USER_AGENT}
        self.session = None
        self.using_tls = False
        self._new_session()

        self.captcha_auto_solve = True
        self.captcha_1 = None
        self.captcha_ = {}
        self.service = 'Views'
        self.comment_id = None
        self.video_key = None
        self.video_info = None
        self.services = {}
        self.services_ids = {}
        self.services_status = {}
        self.url = ''
        self.proxy_ = None
        self._applied_proxy = object()

    # ------------------------------------------------------------ helpers
    def p(self, name):
        return os.path.join(self.data_dir, name)

    def _new_session(self):
        if tls_client is not None:
            self.session = tls_client.Session(client_identifier='chrome112',
                                              random_tls_extension_order=True)
            self.using_tls = True
        else:
            self.session = requests.Session()
            self.using_tls = False

    def _req(self, method, url, **kw):
        if self.using_tls:
            kw.setdefault('timeout_seconds', 30)
        else:
            kw.setdefault('timeout', 30)
        return getattr(self.session, method)(url, **kw)

    def stop(self):
        self.stop_event.set()

    def sleep(self, seconds):
        if self.stop_event.wait(seconds):
            raise StopBot()

    def _check_stop(self):
        if self.stop_event.is_set():
            raise StopBot()

    def apply_config(self, cfg):
        c = dict(DEFAULT_CONFIG)
        c.update(cfg or {})
        self.url = (c['url'] or '').strip()
        self.service = c['service']
        self.comment_id = c['comment_id']
        self.captcha_auto_solve = bool(c['captcha_auto_solve'])
        proxy = c['proxy']
        self.proxy_ = proxy.strip() if isinstance(proxy, str) and proxy.strip() else None

    def export_config(self):
        return {'url': self.url, 'service': self.service, 'comment_id': self.comment_id,
                'proxy': self.proxy_, 'captcha_auto_solve': self.captcha_auto_solve}

    # ------------------------------------------------------------ captcha / session
    def get_captcha(self):
        """True if a session already exists, False if a captcha has to be solved."""
        sess_file = self.p('session')
        if os.path.exists(sess_file):
            with open(sess_file, encoding='utf-8') as f:
                self.session.cookies.set('PHPSESSID', f.read().strip(), domain='zefoy.com')
        r = self._req('get', BASE_URL, headers=self.headers)
        if 'Enter Video URL' in r.text:
            self.video_key = r.text.split('" placeholder="Enter Video URL"')[0].split('name="')[-1]
            return True
        if '<title>Just a moment...</title>' in r.text:
            raise RuntimeError('zefoy.com is behind Cloudflare protection right now '
                               '(try later or use a proxy)')
        self.captcha_ = {}
        for k, v in re.findall(r'<input type="hidden" name="(.*)" value="(.*)">', r.text):
            self.captcha_[k] = v
        self.captcha_1 = r.text.split('type="text" name="')[1].split(
            '" oninput="this.value=this.value.toLowerCase()"')[0]
        captcha_url = r.text.split('<img src="')[1].split('" onerror="imgOnError()" class="')[0]
        img = self._req('get', f'{BASE_URL}{captcha_url}', headers=self.headers)
        with open(self.p('captcha.png'), 'wb') as f:
            f.write(img.content)
        self.log('Solving captcha...')
        return False

    def send_captcha(self, new_session=False):
        if new_session:
            self._new_session()
            self._applied_proxy = object()
            self._apply_proxy()
            try:
                os.remove(self.p('session'))
            except OSError:
                pass
            self.sleep(2)

        for attempt in range(5):
            self._check_stop()
            try:
                if self.get_captcha():
                    self.log('Connected to session')
                    return True, 'The session already exists'
                break
            except StopBot:
                raise
            except Exception as e:
                self.log(f"Can't get captcha: {e}")
                if attempt == 4:
                    raise
                self.sleep(2)

        solved = self.solve_captcha(self.p('captcha.png'))
        if not solved:
            return False, ''
        self.captcha_[self.captcha_1] = solved
        r = self._req('post', BASE_URL, headers=self.headers, data=self.captcha_)
        if 'Enter Video URL' in r.text:
            self.log('Session was created')
            with open(self.p('session'), 'w', encoding='utf-8') as f:
                f.write(self.session.cookies.get('PHPSESSID') or '')
            self.video_key = r.text.split('" placeholder="Enter Video URL"')[0].split('name="')[-1]
            return True, solved
        self.log('Captcha was wrong, retrying...')
        return False, solved

    def solve_captcha(self, path):
        if self.captcha_auto_solve:
            with open(path, 'rb') as f:
                r = requests.post(CAPTCHA_API, files={'file': ('captcha.png', f, 'image/png')},
                                  timeout=60)
            text = r.json()['captcha_text']
        else:
            if self.captcha_handler is None:
                raise ConfigError('Manual captcha needs a captcha handler')
            text = self.captcha_handler(path)
            self._check_stop()
        return (text or '').replace('\n', '').replace('\r', '').strip()

    # ------------------------------------------------------------ services
    def get_status_services(self):
        html = self._req('get', BASE_URL, headers=self.headers).text
        for x in re.findall(r'<h5 class="card-title">.+</h5>\n.+\n.+', html):
            try:
                self.services[x.split('<h5 class="card-title">')[1].split('<')[0].strip()] = \
                    x.split('d-sm-inline-block">')[1].split('</small>')[0].strip()
            except IndexError:
                pass
        for x in re.findall(r'<h5 class="card-title mb-3">.+</h5>\n<form action=".+">', html):
            self.services_ids[x.split('title mb-3">')[1].split('<')[0].strip()] = \
                x.split('<form action="')[1].split('">')[0].strip()
        for x in re.findall(r'<h5 class="card-title">.+</h5>\n.+<button .+', html):
            self.services_status[x.split('<h5 class="card-title">')[1].split('<')[0].strip()] = \
                'disabled class' not in x
        return self.services, self.services_status

    def wait_services(self):
        while True:
            self._check_stop()
            if len(self.get_status_services()[0]) > 1:
                break
            self.log('Cant get services, retrying...')
            self.send_captcha()
            self.sleep(2)
        online = [n for n, ok in self.services_status.items() if ok]
        self.log(f'Total online services: {len(online)}')
        for name, info in self.services.items():
            mark = 'ON ' if self.services_status.get(name) else 'OFF'
            self.log(f'  [{mark}] {name}: {info}')
        if self.on_services:
            self.on_services(list(self.services))

    # ------------------------------------------------------------ main logic
    def _wait_timer(self, t):
        self.log(f'Time to next use: {t}s')
        end = time.time() + t + 2
        while time.time() < end:
            self.sleep(min(1, end - time.time()))

    def find_video(self):
        if not self.service:
            return False, "You didn't choose the service"
        while True:
            self._check_stop()
            if self.service not in self.services_ids:
                self.get_status_services()
                if self.service not in self.services_ids:
                    self.log(f'Service "{self.service}" not found on the site, retrying...')
                    self.sleep(5)
                    continue
            r = self._req('post', f'{BASE_URL}{self.services_ids[self.service]}',
                          headers={'user-agent': USER_AGENT, 'origin': 'https://zefoy.com'},
                          files={self.video_key: (None, self.url)})
            try:
                info = _decode(r.text)
            except Exception:
                self.sleep(3)
                continue
            if 'Session expired. Please re-login' in info:
                self.log('Session expired. Reloging...')
                self.send_captcha()
                return (False, None)
            if 'service is currently not working' in info:
                return (False, 'Service is currently not working, try again later. '
                               '| You can change it in settings.')
            if 'onsubmit="showHideElements' in info:
                self.video_info = [info.split('" name="')[1].split('"')[0],
                                   info.split('value="')[1].split('"')[0]]
                return True, r.text
            if 'Checking Timer...' in info:
                m = re.findall(r'ltm=(\d*);', info)
                if not m:
                    return (False, None)
                t = int(m[0])
                if t >= 1000:
                    self.log('Your IP was banned')
                if t:
                    self._wait_timer(t)
                continue
            if 'Too many requests. Please slow' in info:
                self.sleep(3)
                continue
            self.log(info.strip()[:200])
            self.sleep(3)

    def _green_text(self, res):
        try:
            return res.split("sans-serif;text-align:center;color:green;'>")[1].split('</')[0].strip()
        except IndexError:
            return None

    def use_service(self):
        found = self.find_video()
        if not found[0]:
            return found[1]
        hdr = {'user-agent': USER_AGENT, 'origin': 'https://zefoy.com'}
        url = f'{BASE_URL}{self.services_ids[self.service]}'
        r = self._req('post', url, headers=hdr,
                      files={self.video_info[0]: (None, self.video_info[1])})
        try:
            res = _decode(r.text)
        except Exception:
            self.sleep(3)
            return ''

        if self.service == 'Comments Hearts':
            v = re.search(r'<i class="text-red fa fa-heart"><\/i><\/div>\n<input type="hidden" '
                          r'name="([^"]+)".*\n<input type="hidden" name="([^"]+)"', res)
            if not v:
                self.sleep(3)
                return ''
            if not self.comment_id:
                raise ConfigError('Comments Hearts needs a comment_id')
            r = self._req('post', url, headers=hdr,
                          files={v.group(1): (None, self.video_info[1]),
                                 v.group(2): (None, str(self.comment_id))})
            try:
                res = _decode(r.text)
            except Exception:
                self.sleep(3)
                return ''

        if 'Session expired. Please re-login' in res:
            self.log('Session expired. Reloging...')
            self.send_captcha()
            return ''
        if 'Too many requests. Please slow' in res or 'Checking Timer' in res:
            self.sleep(3)
            return ''
        if 'service is currently not working' in res:
            return 'Service is currently not working, try again later.'
        if 'Please try again later. Server too busy' in res:
            self.log('Error on submit: Please try again later. Server too busy.')
            return ''
        msg = self._green_text(res)
        if msg:
            self.log(msg)
        else:
            self.log('Unknown response: ' + re.sub(r'<[^>]+>', ' ', res).strip()[:150])
        return ''

    # ------------------------------------------------------------ video / proxy
    def get_video_info(self):
        vid = urlparse(self.url).path.rpartition('/')[2]
        r = requests.get(f'https://tiktok.livecounts.io/video/stats/{vid}', timeout=15,
                         headers={'origin': 'https://livecounts.io', 'user-agent': USER_AGENT}).json()
        if 'viewCount' in r:
            return r
        return {'viewCount': 0, 'likeCount': 0, 'commentCount': 0, 'shareCount': 0}

    def get_video_id(self):
        url_ = self.url.rstrip('/')
        if not url_:
            return False
        tail = urlparse(url_).path.rpartition('/')[2]
        if tail.isdigit():
            self.url = url_
            return True
        r = self._req('get', f'https://api.tokcount.com/?type=videoID&username=https://vm.tiktok.com/{tail}',
                      headers={'origin': 'https://tokcount.com', 'user-agent': USER_AGENT})
        if r.text == '':
            return False
        data = r.json()
        if 'author' not in data:
            return False
        self.url = f'https://www.tiktok.com/@{data["author"]}/video/{data["id"]}'
        self.log(f'Formatted video url --> {self.url}')
        return True

    def _apply_proxy(self):
        if self._applied_proxy == self.proxy_:
            return
        self._applied_proxy = self.proxy_
        if not self.proxy_:
            self.session.proxies = {}
            return
        try:
            if self.proxy_.startswith('http'):
                proxy_str = self.proxy_
            else:
                parts = self.proxy_.split(':')
                if len(parts) == 2:
                    proxy_str = f'http://{parts[0]}:{parts[1]}'
                else:
                    proxy_str = f'http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}'
            self.session.proxies = {'http': proxy_str, 'https': proxy_str}
            if self._req('get', 'https://api.ipify.org').status_code != 200:
                raise RuntimeError('Invalid proxy')
            self.log('Proxy connected')
        except Exception as e:
            self.log(f'Failed to use the proxy: {e}')
            self.proxy_ = None
            self._applied_proxy = None
            self.session.proxies = {}

    def prepare(self):
        if not self.url or self.url == 'None':
            raise ConfigError('Enter the video URL first')
        self._apply_proxy()
        if not self.get_video_id():
            raise ConfigError('Invalid video URL')

    # ------------------------------------------------------------ worker entry
    def run(self):
        self.stop_event.clear()
        self.log('Started')
        ready = False
        try:
            while True:
                try:
                    if not ready:
                        self.prepare()
                        self.send_captcha()
                        self.wait_services()
                        ready = True
                    r = self.use_service()
                    if 'Service is currently not working' in str(r):
                        self.log(str(r))
                        self.sleep(5)
                    else:
                        self.sleep(1)
                except (StopBot, ConfigError):
                    raise
                except Exception as e:
                    self.log(f'Critical ERROR | retrying in 30 seconds. ||| {type(e).__name__}: {e}')
                    self.sleep(30)
        except StopBot:
            pass
        except ConfigError as e:
            self.log(f'Error: {e}')
        finally:
            self.log('Stopped')
            if self.on_finish:
                self.on_finish()
