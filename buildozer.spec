[app]
title = Zefoy Bot
package.name = zefoybot
package.domain = org.zefoy
source.dir = .
source.include_exts = py,png,jpg,kv,json
source.exclude_dirs = .github,.git,bin,.buildozer,__pycache__
source.exclude_patterns = cli.py
version = 1.0

# tls_client (native Go lib) cannot run on Android -> core falls back to requests
requirements = python3,kivy==2.3.0,requests,urllib3,chardet,idna,certifi,charset-normalizer,openssl

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE,WAKE_LOCK
android.api = 33
android.minapi = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 1
