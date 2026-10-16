"""Console launcher (Termux / PC). Same workflow as the original: edit config.json, run."""
import json
import os
import sys

from zefoy_core import Zefoy, DEFAULT_CONFIG

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, 'config.json')


def ask_captcha(path):
    print(f'Open {path} and type the captcha text.')
    return input('Captcha: ')


def main():
    if not os.path.exists(CFG):
        json.dump(DEFAULT_CONFIG, open(CFG, 'w', encoding='utf-8'), indent=4)
    cfg = json.load(open(CFG, encoding='utf-8'))
    bot = Zefoy(data_dir=HERE, log=print, captcha_handler=ask_captcha)
    bot.apply_config(cfg)
    try:
        bot.run()
    except KeyboardInterrupt:
        bot.stop()


if __name__ == '__main__':
    sys.exit(main())
