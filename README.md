# sysadmin-agent

Автоматизация рутины сисадмина: демон мониторит критические параметры
сервера (RAM, диск, GPU, SSH-логи, аккаунты) и при обнаружении аномалий
**выполняет действие**, а не просто шлёт алерт.

| Сигнал | Порог (по умолчанию) | Реакция |
|---|---|---|
| Занято RAM | ≥ 90% | `drop_caches`, чистка старых файлов в `/tmp` |
| Мало места на диске | < 10% свободно | `journalctl --vacuum`, удаление ротированных логов |
| GPU load / VRAM | ≥ 90% | алерт в journald (авто-kill задач **не** делает) |
| Неудачные SSH-логины | ≥ 5 с одного IP за 5 мин | **бан IP через iptables** (белый список учитывается) |
| Аккаунты без пароля | любые | алерт в journald + лог-файл |

Всё, что делает агент, пишется и в `journalctl -u sysadmin-agent`, и в
`/var/log/sysadmin-agent.log`.

## Стек

- **Python 3.10+** (`psutil`, `PyYAML`) — демон и вся логика
- **Bash** — ручные хелперы (`bin/`)
- **systemd** — установка как системная служба
- **iptables** — баны

## Структура

```
sysadmin-agent/
├── agent/                          # Python-демон
│   ├── __main__.py                 # entry point, главный цикл, signal handling
│   ├── config.py                   # загрузка config.yaml
│   ├── logging_setup.py            # journald + /var/log/sysadmin-agent.log
│   ├── monitors/
│   │   ├── memory.py               # RAM/swap
│   │   ├── disk.py                 # свободное место
│   │   ├── gpu.py                  # nvidia-smi (отключается, если его нет)
│   │   ├── ssh_log.py              # парсинг journalctl/auth.log, brute-force
│   │   └── users.py                # аккаунты без пароля / залоченные
│   └── actions/
│       ├── cleanup.py              # drop_caches, /tmp, ротация логов
│       ├── firewall.py             # бан IP через iptables
│       └── users.py                # lock/unlock юзеров
├── bin/
│   ├── ban-ip.sh                   # ручной бан/разбан/статус
│   └── cleanup-logs.sh             # ручная чистка логов и кэша
├── systemd/sysadmin-agent.service  # unit-файл
├── config/config.yaml              # пороги, интервал, dry-run, whitelist
├── install.sh                      # установка как службы
├── requirements.txt
└── README.md
```

## Установка на сервере

```bash
git clone https://github.com/<you>/sysadmin-agent.git
cd sysadmin-agent
sudo ./install.sh
```

Скрипт скопирует код в `/opt/sysadmin-agent`, конфиг — в
`/etc/sysadmin-agent/config.yaml`, поставит unit-файл и запустит службу.

### Ручная установка (без install.sh)

```bash
sudo pip3 install -r requirements.txt
sudo cp -r agent /opt/sysadmin-agent/
sudo mkdir -p /etc/sysadmin-agent
sudo cp config/config.yaml /etc/sysadmin-agent/
sudo cp systemd/sysadmin-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start my-agent   # или sysadmin-agent — имя из unit-файла
```

## Управление службой

```bash
sudo systemctl start sysadmin-agent     # старт
sudo systemctl stop sysadmin-agent      # стоп
sudo systemctl enable sysadmin-agent    # автозапуск при загрузке
sudo systemctl status sysadmin-agent    # состояние
journalctl -u sysadmin-agent -f         # живой лог
journalctl -u sysadmin-agent --since today
```

## Конфигурация

`/etc/sysadmin-agent/config.yaml`:

```yaml
dry_run: true        # true = только алерты, без реальных действий
interval_sec: 30     # период опроса

whitelist:           # эти IP никогда не будут забанены
  - 127.0.0.1
  - 10.0.0.0/8

memory:
  used_percent_threshold: 90

ssh_log:
  max_failed_attempts: 5
  window_sec: 300
  ban_ttl_sec: 3600
```

> ⚠️ **По умолчанию `dry_run: true`** — агент только логирует, что *сделал бы*.
> После проверки на сервере поставьте `dry_run: false`, чтобы включить
> `drop_caches`, чистку логов и баны iptables.

После правки конфига: `sudo systemctl restart sysadmin-agent`.

## Ручные хелперы

```bash
sudo bin/cleanup-logs.sh --dry-run   # показать, что будет почищено
sudo bin/cleanup-logs.sh             # почистить логи + drop_caches
sudo bin/ban-ip.sh 203.0.113.7       # забанить IP
sudo bin/ban-ip.sh --unban 203.0.113.7
sudo bin/ban-ip.sh --status          # правила агента
```

## Отладка

```bash
# один цикл без запуска службы
sudo python3 -m agent --config config/config.yaml --once --verbose
```

## Требования и безопасность

- нужен **root** (drop_caches, journal vacuum, iptables)
- работает только на **Linux + systemd**
- GPU-монитору нужен `nvidia-smi`; без него он отключается автоматически
- агент **не** удаляет и **не** меняет пользователей сам — только алертит
- баны идут в отдельную цепочку `SYSADMIN_AGENT`, остальной фаервол не трогается
- белый список (`whitelist`) защищает от блокировки собственных IP

## Лицензия

MIT
