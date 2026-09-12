#!/usr/bin/env bash

sudo install -m 0750 ipv6-prefix-ddns.py /usr/local/sbin/ipv6-prefix-ddns
sudo install -m 0750 ipv6-prefix-ddns-firewall /usr/local/sbin/ipv6-prefix-ddns-firewall
sudo install -m 0600 config.conf /etc/ipv6-prefix-ddns/config.conf
sudo install -m 0644 ipv6-prefix-ddns.service /etc/systemd/system/ipv6-prefix-ddns.service
sudo systemctl daemon-reload
sudo systemctl restart ipv6-prefix-ddns.service
sudo journalctl -u ipv6-prefix-ddns.service -n 40 --no-pager