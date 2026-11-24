# Бот на VPS, плата по USB

Путь данных: ESP32 → USB → `bridge.py` на компьютере → HTTPS → бот на VPS. На компьютере нужен интернет и отключённый сон. При его выключении серверный бот остаётся доступен для разговора, но свежих измерений не получает.

Ниже пример для Ubuntu с Python, venv и systemd. Домен с действующим HTTPS-сертификатом и nginx настройте заранее. Не открывайте HTTP-порты приёма данных наружу: они слушают loopback.

## Установка

Скопируйте папку `bot` в `/opt/neuroflower/app`, затем на сервере:

```sh
sudo useradd --system --home /var/lib/neuroflower --shell /usr/sbin/nologin neuroflower
sudo python3 -m venv /opt/neuroflower/venv
sudo /opt/neuroflower/venv/bin/pip install -r /opt/neuroflower/app/requirements.txt
sudo install -d -o neuroflower -g neuroflower -m 700 /var/lib/neuroflower
sudo install -o neuroflower -g neuroflower -m 600 /opt/neuroflower/app/config.server.example.json /var/lib/neuroflower/config.json
sudoedit /var/lib/neuroflower/config.json
```

Если пользователь уже создан, не создавайте его повторно. Заполните Telegram username, токен, числовой owner_id, OpenAI key и модель, как в локальной инструкции. Создайте два разных случайных секрета командой `python3 -c "import secrets; print(secrets.token_hex(32))"`: один для `ingest_token`, другой для `character_gateway_token`. Каждый вызов создаёт новый секрет; не публикуйте вывод.

Вставьте блок из `deploy/nginx-locations.conf` в HTTPS server вашего домена. После проверки `sudo nginx -t` выполните `sudo systemctl reload nginx`. Не заменяйте целиком конфигурацию действующего сайта.

Скопируйте `deploy/neuroflower.service` в `/etc/systemd/system/neuroflower.service` и выполните:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now neuroflower
sudo systemctl status neuroflower --no-pager
```

По умолчанию голосовой шлюз выключен. Включайте `character_gateway_enabled: true` только при настройке Саймона; адрес 127.0.0.1, порт 8798. Порт приёма показаний — 8797. Если они заняты на вашем VPS, согласованно измените конфигурацию и nginx; адаптер Саймона намеренно ограничен конкретным loopback endpoint.

## Мост на компьютере

Установите зависимости `bot/requirements.txt`. В папке `bot` скопируйте `bridge.example.json` в `bridge.json`. Укажите порт, домен и ровно тот `ingest_token`, который записали на сервере. Telegram/OpenAI ключи мосту не нужны.

```powershell
.\.venv\Scripts\python.exe bridge.py --config bridge.json
```

Перед этим остановите локального Telegram-бота и Serial Monitor. Один токен Telegram не должен обслуживаться двумя процессами. На сервере `/start` и «Показатели» должны показать свежую запись. Остановите мост: спустя более 90 секунд данные должны отмечаться устаревшими. Снова запустите — свежесть должна восстановиться.

Сервис хранит память в `/var/lib/neuroflower`. Обновляйте только код, сохраняя эту папку. Перед обновлением делайте резервную копию базы при остановленном сервисе либо через SQLite backup API. Секреты и память не входят в Git.
