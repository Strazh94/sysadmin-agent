# sysadmin-agent

Automates sysadmin routine: the daemon monitors critical server parameters
(RAM, disk, GPU, SSH logs, accounts) and when it detects an anomaly it
**takes action** instead of just sending an alert.

| Signal | Threshold (default) | Reaction |
|---|---|---|
| RAM usage | ≥ 90% | `drop_caches`, clean up old files in `/tmp` |
| Low disk space | < 10% free | `journalctl --vacuum`, remove rotated logs |
| GPU load / VRAM | ≥ 90% | alert to journald (does **not** auto-kill jobs) |
| Failed SSH logins | ≥ 5 from one IP in 5 min | **ban the IP via iptables** (whitelist is respected) |
| Accounts without a password | any | alert to journald + log file |

Everything the agent does is written both to `journalctl -u sysadmin-agent`
and to `/var/log/sysadmin-agent.log`.

## Stack

- **Python 3.10+** (`psutil`, `PyYAML`) — the daemon and all logic
- **Bash** — manual helpers (`bin/`)
- **systemd** — installed as a system service
- **iptables** — bans

## Structure

```
sysadmin-agent/
├── agent/                          # Python daemon
│   ├── __main__.py                 # entry point, main loop, signal handling
│   ├── config.py                   # loads config.yaml
│   ├── logging_setup.py            # journald + /var/log/sysadmin-agent.log
│   ├── monitors/
│   │   ├── memory.py               # RAM/swap
│   │   ├── disk.py                 # free space
│   │   ├── gpu.py                  # nvidia-smi (disabled if unavailable)
│   │   ├── ssh_log.py              # parses journalctl/auth.log, brute-force
│   │   └── users.py                # passwordless / locked accounts
│   └── actions/
│       ├── cleanup.py              # drop_caches, /tmp, log rotation
│       ├── firewall.py             # ban IPs via iptables
│       └── users.py                # lock/unlock users
├── bin/
│   ├── ban-ip.sh                   # manual ban/unban/status
│   └── cleanup-logs.sh             # manual log and cache cleanup
├── systemd/sysadmin-agent.service  # unit file
├── config/config.yaml              # thresholds, interval, dry-run, whitelist
├── install.sh                      # installs as a service
├── requirements.txt
└── README.md
```

## Installation on a server

```bash
git clone https://github.com/Strazh94/sysadmin-agent.git
cd sysadmin-agent
sudo ./install.sh
```

The script copies the code to `/opt/sysadmin-agent`, the config to
`/etc/sysadmin-agent/config.yaml`, installs the unit file and starts the service.

### Manual installation (without install.sh)

```bash
sudo pip3 install -r requirements.txt
sudo cp -r agent /opt/sysadmin-agent/
sudo mkdir -p /etc/sysadmin-agent
sudo cp config/config.yaml /etc/sysadmin-agent/
sudo cp systemd/sysadmin-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start my-agent   # or sysadmin-agent — the name from the unit file
```

## Managing the service

```bash
sudo systemctl start sysadmin-agent     # start
sudo systemctl stop sysadmin-agent      # stop
sudo systemctl enable sysadmin-agent    # start on boot
sudo systemctl status sysadmin-agent    # status
journalctl -u sysadmin-agent -f         # live log
journalctl -u sysadmin-agent --since today
```

## Configuration

`/etc/sysadmin-agent/config.yaml`:

```yaml
dry_run: true        # true = alerts only, no real actions
interval_sec: 30     # polling interval

whitelist:           # these IPs are never banned
  - 127.0.0.1
  - 10.0.0.0/8

memory:
  used_percent_threshold: 90

ssh_log:
  max_failed_attempts: 5
  window_sec: 300
  ban_ttl_sec: 3600
```

> ⚠️ **`dry_run: true` is the default** — the agent only logs what it *would have done*.
> After testing it on the server, set `dry_run: false` to enable
> `drop_caches`, log cleanup and iptables bans.

After editing the config: `sudo systemctl restart sysadmin-agent`.

## Manual helpers

```bash
sudo bin/cleanup-logs.sh --dry-run   # show what would be cleaned
sudo bin/cleanup-logs.sh             # clean logs + drop_caches
sudo bin/ban-ip.sh 203.0.113.7       # ban an IP
sudo bin/ban-ip.sh --unban 203.0.113.7
sudo bin/ban-ip.sh --status          # agent rules
```

## Debugging

```bash
# run a single cycle without starting the service
sudo python3 -m agent --config config/config.yaml --once --verbose
```

## Requirements and security

- **root** is required (drop_caches, journal vacuum, iptables)
- runs on **Linux + systemd** only
- the GPU monitor needs `nvidia-smi`; without it, it is disabled automatically
- the agent does **not** remove or modify users on its own — it only alerts
- bans go to a dedicated `SYSADMIN_AGENT` chain, the rest of the firewall is untouched
- the whitelist (`whitelist`) protects your own IPs from being blocked

## License

MIT
