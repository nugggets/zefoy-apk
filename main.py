"""Android (Kivy) front-end for the Zefoy automator. Entry point for buildozer."""
import json
import os
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput

from zefoy_core import Zefoy, DEFAULT_CONFIG, DEFAULT_SERVICES

Window.softinput_mode = 'below_target'

KV = '''
<Lbl@Label>:
    size_hint_y: None
    height: dp(22)
    halign: 'left'
    text_size: self.size
    color: .8, .8, .8, 1

BoxLayout:
    orientation: 'vertical'
    padding: dp(10)
    spacing: dp(6)

    Lbl:
        text: 'TikTok video URL'
    TextInput:
        id: url
        size_hint_y: None
        height: dp(44)
        multiline: False
        write_tab: False
        hint_text: 'https://www.tiktok.com/@user/video/123...'

    Lbl:
        text: 'Service'
    Spinner:
        id: service
        size_hint_y: None
        height: dp(44)
        text: 'Views'

    Lbl:
        text: 'Comment ID (only for Comments Hearts)'
    TextInput:
        id: comment_id
        size_hint_y: None
        height: dp(44)
        multiline: False
        input_filter: 'int'

    Lbl:
        text: 'Proxy (ip:port or ip:port:user:pass), optional'
    TextInput:
        id: proxy
        size_hint_y: None
        height: dp(44)
        multiline: False

    BoxLayout:
        size_hint_y: None
        height: dp(40)
        CheckBox:
            id: auto
            size_hint_x: None
            width: dp(44)
            active: True
        Label:
            text: 'Auto-solve captcha'
            halign: 'left'
            text_size: self.size
            valign: 'middle'

    BoxLayout:
        size_hint_y: None
        height: dp(50)
        spacing: dp(8)
        Button:
            id: start
            text: 'START'
            background_color: .2, .7, .3, 1
            on_release: app.start()
        Button:
            id: stop
            text: 'STOP'
            disabled: True
            background_color: .85, .25, .25, 1
            on_release: app.stop()

    Label:
        id: stats
        size_hint_y: None
        height: dp(22)
        text: ''
        font_size: '13sp'

    ScrollView:
        id: scroll
        do_scroll_x: False
        bar_width: dp(4)
        Label:
            id: log
            size_hint_y: None
            height: self.texture_size[1]
            text_size: self.width, None
            halign: 'left'
            valign: 'top'
            font_size: '12sp'
            text: ''
'''


class ZefoyApp(App):
    title = 'Zefoy Bot'

    def build(self):
        self.root_widget = Builder.load_string(KV)
        self.bot = None
        self.worker = None
        self.running = False
        self.lines = []
        self.cfg_path = os.path.join(self.user_data_dir, 'config.json')
        ids = self.root_widget.ids
        ids.service.values = DEFAULT_SERVICES
        self.load_config()
        return self.root_widget

    # ---------------------------------------------------------------- config
    def load_config(self):
        cfg = dict(DEFAULT_CONFIG)
        try:
            with open(self.cfg_path, encoding='utf-8') as f:
                cfg.update(json.load(f))
        except Exception:
            pass
        ids = self.root_widget.ids
        ids.url.text = cfg['url'] or ''
        ids.service.text = cfg['service'] or 'Views'
        ids.comment_id.text = str(cfg['comment_id'] or '')
        ids.proxy.text = cfg['proxy'] or ''
        ids.auto.active = bool(cfg['captcha_auto_solve'])

    def read_form(self):
        ids = self.root_widget.ids
        return {
            'url': ids.url.text.strip(),
            'service': ids.service.text,
            'comment_id': ids.comment_id.text.strip() or None,
            'proxy': ids.proxy.text.strip() or None,
            'captcha_auto_solve': ids.auto.active,
        }

    # ---------------------------------------------------------------- log
    def log(self, msg):
        Clock.schedule_once(lambda dt: self._append(str(msg)))

    def _append(self, msg):
        self.lines.append(msg)
        self.lines = self.lines[-300:]
        ids = self.root_widget.ids
        ids.log.text = '\n'.join(self.lines)
        Clock.schedule_once(lambda dt: setattr(ids.scroll, 'scroll_y', 0), 0.05)

    # ---------------------------------------------------------------- run / stop
    def start(self):
        if self.running:
            return
        cfg = self.read_form()
        if not cfg['url']:
            self._append('Enter the video URL first')
            return
        try:
            with open(self.cfg_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=4)
        except Exception as e:
            self._append(f'Could not save config: {e}')

        self.bot = Zefoy(data_dir=self.user_data_dir, log=self.log,
                         captcha_handler=self.ask_captcha,
                         on_services=self.update_services, on_finish=self.on_finish)
        self.bot.apply_config(cfg)
        self.running = True
        ids = self.root_widget.ids
        ids.start.disabled = True
        ids.stop.disabled = False
        self.worker = threading.Thread(target=self.bot.run, daemon=True)
        self.worker.start()
        threading.Thread(target=self.stats_loop, args=(self.bot,), daemon=True).start()

    def stop(self):
        if self.bot:
            self._append('Stopping...')
            self.bot.stop()
            self.root_widget.ids.stop.disabled = True

    def on_finish(self):
        def _ui(dt):
            self.running = False
            ids = self.root_widget.ids
            ids.start.disabled = False
            ids.stop.disabled = True
            ids.stats.text = ''
        Clock.schedule_once(_ui)

    def on_stop(self):
        if self.bot:
            self.bot.stop()

    def update_services(self, names):
        def _ui(dt):
            self.root_widget.ids.service.values = names
        Clock.schedule_once(_ui)

    def stats_loop(self, bot):
        while self.running and bot is self.bot and not bot.stop_event.is_set():
            try:
                if bot.url and bot.url != 'None':
                    s = bot.get_video_info()
                    text = (f"Views {s['viewCount']} | Likes {s['likeCount']} | "
                            f"Comments {s['commentCount']} | Shares {s['shareCount']}")
                    Clock.schedule_once(lambda dt, t=text: setattr(self.root_widget.ids.stats, 'text', t))
            except Exception:
                pass
            bot.stop_event.wait(5)

    # ---------------------------------------------------------------- manual captcha
    def ask_captcha(self, path):
        """Called from the worker thread; blocks until the user answers."""
        done = threading.Event()
        result = {'text': ''}

        def show(dt):
            box = BoxLayout(orientation='vertical', spacing=8, padding=8)
            box.add_widget(Image(source=path, nocache=True))
            entry = TextInput(multiline=False, size_hint_y=None, height=44)
            box.add_widget(entry)
            btn = Button(text='OK', size_hint_y=None, height=48)
            box.add_widget(btn)
            popup = Popup(title='Solve captcha', content=box, size_hint=(.95, .6),
                          auto_dismiss=False)

            def ok(*_):
                result['text'] = entry.text
                popup.dismiss()
                done.set()
            btn.bind(on_release=ok)
            entry.bind(on_text_validate=ok)
            popup.open()
            entry.focus = True

        Clock.schedule_once(show)
        while not done.wait(0.5):
            if self.bot is None or self.bot.stop_event.is_set():
                break
        return result['text']


if __name__ == '__main__':
    ZefoyApp().run()
