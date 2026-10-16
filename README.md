# Zefoy Bot (Android / APK)

Переработка plowside/Zefoy_TIKTOK_BOT: ядро вынесено в `zefoy_core.py`, добавлен Kivy-интерфейс (`main.py`)
и сборка APK через Buildozer / GitHub Actions.

- `main.py` - Android-приложение (Kivy)
- `zefoy_core.py` - логика (без input/print, с кнопкой Stop)
- `cli.py` - консольный запуск в Termux/ПК (`python cli.py`, настройки в `config.json`)
- `buildozer.spec` - настройки сборки
- `.github/workflows/build-apk.yml` - автосборка APK

## Сборка APK
Залейте проект в свой репозиторий на GitHub (ветка main). Во вкладке Actions запустится "Build APK"
(первая сборка 20-40 минут). Готовый файл: Actions -> последний запуск -> Artifacts -> zefoy-bot-apk.

Примечание: в APK вместо tls_client (нативная библиотека, на Android не работает) используется requests.
Если Zefoy отвечает 502/Cloudflare - используйте прокси или консольную версию через Termux.
