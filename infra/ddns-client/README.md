# IPv6 Prefix DDNS Client

Из корня проекта используйте `make ddns-install`, `make ddns-status`,
`make ddns-restart`, `make ddns-logs`, `make check-ipv6` и `make check-dns`.
Все команды и параметры описаны в [OPERATIONS.md](../OPERATIONS.md).
Проверки подключения к SSH временно пропускаются; сервис будет настроен на порт 42.

Служба отслеживает изменение глобального IPv6-префикса на заданном сетевом интерфейсе, автоматически назначает стабильные IPv6-адреса с заданными суффиксами через NetworkManager и синхронизирует соответствующие AAAA-записи в Cloudflare.

Опциональный firewall-hook интегрируется с существующим UFW и Docker/k3d firewall, позволяя разделить адрес приложения и адрес SSH.

## IPv6, HAPP и UFW

Для сервера за HAPP включите в конфигурации:

```ini
DIRECT_ROUTING=true
FIREWALL_HOOK=/usr/local/sbin/ipv6-prefix-ddns-firewall
```

`DIRECT_ROUTING` по умолчанию выключен для конфигураций без этого параметра.
В локальном `config.conf` и шаблоне он включён. Исключения действуют **по исходному
адресу**, только для записей с суффиксами `10` и `20` текущего префикса:

```text
from <PREFIX>::10/128 lookup 106 priority 100
from <PREFIX>::20/128 lookup 106 priority 101
остальные источники → существующие маршруты HAPP
```

Это правила для ответов сервисов и исходящих сокетов, использующих эти адреса.
Они не являются маской для любых IPv6, оканчивающихся на `::10`/`::20`, и не
исключают из HAPP весь делегированный префикс. Несколько DNS-имён с одним
суффиксом создают одно правило. Локальные адреса по-прежнему обслуживает
системное правило `lookup local` с приоритетом 0.

Таблица IPv6 `106`, protocol `242` и приоритеты `100/101` зарезервированы для
DDNS. Таблица содержит текущую локальную сеть, link-local сеть и default через
шлюз `INTERFACE`, выбранный из `main`. Default HAPP и правила IPv4 не изменяются.
Чужие записи в таблице или правила приоритетов `1..101` вызывают ошибку вместо
перезаписи. При исчезновении физического шлюза исключённые источники получают
`unreachable`, пока шлюз не появится: их трафик не возвращается в тоннель.

Проверка маршрутов выполняется каждые `POLL_INTERVAL` секунд независимо от
DNS resync/cooldown. Смена префикса удаляет старые исключения, смена шлюза
обновляет маршрут. `DIRECT_ROUTING=false` удаляет принадлежащие DDNS правила
и маршруты при следующем запуске с новой конфигурацией. Простая остановка
службы сохраняет уже установленные правила до перезагрузки.

Для текущего k3d используется IPv4-only bridge с Docker `userland-proxy=true`:
он принимает IPv6 в хостовом `INPUT` и передаёт запрос контейнеру по IPv4.
В `infra/k3d-infra/cluster.tf` порты 80/443 публикуются без ограничения `host`
для обоих семейств адресов. Native IPv6 DNAT контейнеров этой схемой
маршрутизации ответов не покрывается.

UFW должен быть активен с `IPV6=yes`. Цепочка `IPV6-DDNS-HOST` ограничивает
доступные порты на управляемых адресах, затем возвращает разрешённые пакеты
в UFW. Цепочка `IPV6-DDNS-ALLOW` вызывается **в конце `ufw6-user-input`**:
пользовательские правила, включая явные deny/reject, проверяются раньше.
Исключения разрешают `<PREFIX>::10` TCP/80,443 и `<PREFIX>::20` TCP/42.
Сам sshd нужно отдельно настроить слушать IPv6 TCP/42.
Default INPUT/OUTPUT/FORWARD policies UFW не изменяются; ICMPv6 остаётся
под штатными правилами UFW. Маршрутизация не обходит фильтрацию OUTPUT.

Если IPv6 `DOCKER-USER` отсутствует, hook устанавливает ограничивающую цепочку
в `FORWARD`; для IPv6 userland-proxy это штатная ситуация. После `ufw reload`
или изменения правил UFW перезапустите DDNS, чтобы восстановить динамический
переход в `ufw6-user-input`. Эти runtime-правила проверяются через `ip6tables`,
а не через `ufw status`.

Обновление уже установленной службы, из корня репозитория:

```bash
sudo install -m 0750 infra/ddns-client/ipv6-prefix-ddns.py /usr/local/sbin/ipv6-prefix-ddns
sudo install -m 0750 infra/ddns-client/ipv6-prefix-ddns-firewall /usr/local/sbin/ipv6-prefix-ddns-firewall
sudo install -m 0600 infra/ddns-client/config.conf /etc/ipv6-prefix-ddns/config.conf
sudo install -m 0644 infra/ddns-client/ipv6-prefix-ddns.service /etc/systemd/system/ipv6-prefix-ddns.service
sudo systemctl daemon-reload
sudo systemctl restart ipv6-prefix-ddns.service
sudo journalctl -u ipv6-prefix-ddns.service -n 40 --no-pager
```

После успешной синхронизации примените изменение публикации портов по
[инструкции k3d](../k3d-infra/README.md#ipv4ipv6-happ-и-ufw).

Проверка маршрутов (подставьте текущие APP/SSH и обычный SLAAC-адрес):

```bash
ip -6 rule show
ip -6 route show table 106
ip -6 route get 2606:4700:4700::1111 from <APP_IPV6>
ip -6 route get 2606:4700:4700::1111 from <SSH_IPV6>
ip -6 route get 2606:4700:4700::1111 from <SLAAC_IPV6>
sudo ip6tables -S ufw6-user-input
sudo ip6tables -S IPV6-DDNS-ALLOW
```

Первые два route lookup должны выбрать `INTERFACE`, третий — `happ-xray`
при включённом HAPP. Проверяйте TCP также из внешней IPv6-сети: локальное
подключение к собственному адресу не проверяет входной firewall роутера.

Тесты с реальными маршрутами и TCP-пакетами выполняются в одноразовых
user/network namespaces, без изменения сети хоста:

```bash
unshare --user --map-root-user --net env DDNS_NETWORK_TESTS=1 \
  python3 -m unittest discover -s infra/ddns-client/tests -v
```

Типичная конфигурация:

```text
ISP / PPPoE
     │
     │ IPv6 Prefix Delegation / RA
     ▼
   Router
     │
     ▼
Linux host / NetworkManager
     │
     ├── SLAAC address
     ├── <PREFIX>::10 ── app.example.ru
     └── <PREFIX>::20 ── ssh.example.ru
              │
              ▼
      ipv6-prefix-ddns
        │      │      │
        │      │      └── Cloudflare DNS
        │      └───────── firewall hook
        └──────────────── NetworkManager
```

## Структура проекта

```text
ddns-client/
├── config.conf
├── config.conf.example
├── ipv6-prefix-ddns-firewall
├── ipv6-prefix-ddns.py
└── ipv6-prefix-ddns.service
```

`config.conf` содержит локальную конфигурацию конкретного хоста и не должен храниться в публичном репозитории, так как содержит Cloudflare API Token.

Рекомендуется добавить его в `.gitignore`:

```gitignore
config.conf
```

---

# 1. Требования

## 1.1. Сеть

Хост должен иметь глобальный IPv6-адрес на физическом интерфейсе.

Проверка:

```bash
ip -6 addr show dev enp1s0 scope global
```

Ожидается как минимум один глобальный адрес, например:

```text
inet6 2a00:1234:5678:abcd:1234:5678:9abc:def0/64 ...
```

Служба определяет текущий префикс непосредственно по адресу указанного `INTERFACE`. Внешние сервисы определения IP не используются, поэтому активный VPN на другом интерфейсе не должен влиять на DDNS.

Предполагается, что IPv6 интерфейса управляется NetworkManager и использует:

```text
ipv6.method = auto
```

Проверить:

```bash
nmcli -g ipv6.method connection show "Проводное подключение 1"
```

При необходимости:

```bash
sudo nmcli connection modify \
    "Проводное подключение 1" \
    ipv6.method auto
```

Желательно, чтобы на интерфейсе существовал один основной глобальный SLAAC/DHCPv6-префикс. При нескольких независимых глобальных префиксах на одном интерфейсе автоматический выбор может оказаться неоднозначным.

## 1.2. ПО

Необходимы:

```text
Python >= 3.10
systemd
NetworkManager / nmcli
iproute2 / ip
bash
awk
jq
logger
ip6tables
Docker
k3d
```

При использовании UFW:

```text
ufw
```

Для CachyOS/Arch Linux основные зависимости можно установить так:

```bash
sudo pacman -S --needed \
    python \
    networkmanager \
    iproute2 \
    jq \
    iptables-nft \
    ufw
```

`bash`, `awk`, `logger` и systemd обычно уже являются частью базовой системы.

Проверка:

```bash
command -v python3
command -v nmcli
command -v ip
command -v jq
command -v ip6tables
command -v logger
command -v docker
command -v k3d
```

## 1.3. Cloudflare

DNS-зона домена должна обслуживаться Cloudflare.

Понадобятся:

```text
CF_ZONE
CF_ZONE_ID
CF_API_TOKEN
```

Для API Token достаточно предоставить конкретной DNS-зоне право:

```text
Zone → DNS → Edit
```

или эквивалентное ему `DNS Write`.

Рекомендуется ограничить token только одной необходимой зоной.

Хост должен иметь исходящий HTTPS-доступ к:

```text
api.cloudflare.com:443
```

Демон может как обновлять существующие AAAA-записи, так и создавать отсутствующие.

## 1.4. Docker

Текущая версия firewall-hook рассчитана на Docker с firewall backend:

```text
iptables
```

Использование `iptables-nft` на уровне Linux допустимо: команды `ip6tables` в таком случае управляют правилами через nf_tables compatibility layer.

Не следует переключать Docker на native:

```json
{
  "firewall-backend": "nftables"
}
```

без переработки firewall-hook.

Проверить наличие необходимой Docker chain:

```bash
sudo ip6tables -nL DOCKER-USER
```

При отсутствии IPv6 `DOCKER-USER` hook использует `FORWARD` для ограничения
forwarded-трафика. IPv6 userland-proxy работает через `INPUT` и UFW.

## 1.5 Требования к k3d / OpenTofu

Жизненный цикл k3d-кластера, конфигурация Kubernetes load balancer /
Ingress и необходимые port mappings управляются OpenTofu.

DDNS client не создаёт и не изменяет k3d/Kubernetes resources.

OpenTofu-конфигурация должна обеспечить следующий внешний контракт:

```text
host TCP/80  -> k3d loadbalancer / ingress TCP/80
host TCP/443 -> k3d loadbalancer / ingress TCP/443
```

k3d рекомендует публиковать ingress через `@loadbalancer`; именно
serverlb принимает опубликованные host ports и проксирует их к server
nodes.

Дополнительные публичные Docker/k3d host ports не предполагаются.
Firewall DDNS-службы пропускает с внешнего INTERFACE только новые
forwarded-соединения к APP IPv6 на TCP/80 и TCP/443.

Создание кластера, port mappings, Kubernetes Services/Ingress и их
dependency ordering являются ответственностью OpenTofu stack.

После `tofu apply` должны успешно выполняться:

```bash
tofu show
k3d cluster list
kubectl get nodes
kubectl get ingress -A
kubectl get svc -A
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

База данных и backend API, если им не требуется прямой внешний доступ, не должны публиковаться отдельными host-портами.

Предпочтительная схема:

```text
Internet
   │
   │ TCP 80/443
   ▼
k3d serverlb
   │
   ▼
Traefik / Ingress
   │
   ├── frontend
   └── backend

PostgreSQL:
ClusterIP only
```

Docker/k3d и UFW желательно запустить до `ipv6-prefix-ddns.service`.
Hook требует активный IPv6 UFW и выбирает `DOCKER-USER` либо `FORWARD`.

Если Docker или k3d были запущены позже, выполните:

```bash
sudo systemctl restart ipv6-prefix-ddns.service
```

---

# 2. Подготовка UFW

UFW отключать не требуется.

Рекомендуемая базовая политика:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
```

Проверить:

```bash
sudo ufw status verbose
```

Особенно важно не оставлять глобальное IPv6-разрешение SSH вида:

```text
42/tcp ALLOW Anywhere (v6)
```

Иначе SSH может остаться доступным не только через `<PREFIX>::20`, но и через SLAAC или другие IPv6-адреса хоста.

Просмотреть правила:

```bash
sudo ufw status numbered
```

После изменения UFW или выполнения:

```bash
sudo ufw reload
```

рекомендуется повторно запустить DDNS-сервис:

```bash
sudo systemctl restart ipv6-prefix-ddns.service
```

Это гарантирует повторную установку динамических firewall-правил.

---

# 3. Конфигурация k3d

Если кластер ещё не создан:

```bash
k3d cluster create duncarbox \
    -p "80:80@loadbalancer" \
    -p "443:443@loadbalancer"
```

Если используется только HTTP:

```bash
k3d cluster create duncarbox \
    -p "80:80@loadbalancer"
```

После запуска:

```bash
k3d cluster list
```

и:

```bash
docker ps
```

Проверьте опубликованные порты контейнера `serverlb`.

Также проверьте Docker firewall:

```bash
sudo ip6tables -nL DOCKER-USER
```

Если цепочка отсутствует, проверьте переход в `IPV6-DDNS-DOCKER` из `FORWARD`.

---

# 4. Создание конфигурации

Создайте пользовательский конфиг из шаблона:

```bash
cp config.conf.example config.conf
```

Отредактируйте:

```bash
nano config.conf
```

Пример:

```ini
INTERFACE=enp4s0
CONNECTION=Проводное подключение 1

CF_ZONE=example.ru
CF_ZONE_ID=0123456789abcdef0123456789abcdef
CF_API_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

POLL_INTERVAL=5

RETRY_COUNT=5
RETRY_DELAY=5

COOLDOWN=900
RESYNC_INTERVAL=900

FIREWALL_HOOK=/usr/local/sbin/ipv6-prefix-ddns-firewall

RECORD=app,10,false
RECORD=ssh,20,false
```

---

# 5. Параметры конфигурации

## `INTERFACE`

Сетевой интерфейс, с которого определяется глобальный IPv6-префикс.

Например:

```ini
INTERFACE=enp4s0
```

Посмотреть интерфейсы:

```bash
nmcli device
```

или:

```bash
ip link
```

## `CONNECTION`

Имя профиля NetworkManager.

Например:

```ini
CONNECTION=Проводное подключение 1
```

Посмотреть:

```bash
nmcli connection show
```

## `CF_ZONE`

DNS-зона Cloudflare:

```ini
CF_ZONE=example.ru
```

## `CF_ZONE_ID`

Cloudflare Zone ID:

```ini
CF_ZONE_ID=0123456789abcdef0123456789abcdef
```

## `CF_API_TOKEN`

API Token с правом изменения DNS:

```ini
CF_API_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Конфигурационный файл должен быть доступен только root.

## `POLL_INTERVAL`

Интервал проверки локального IPv6-префикса:

```ini
POLL_INTERVAL=5
```

Значение задаётся в секундах.

## `RETRY_COUNT`

Количество попыток полной синхронизации:

```ini
RETRY_COUNT=5
```

## `RETRY_DELAY`

Пауза между попытками:

```ini
RETRY_DELAY=5
```

## `COOLDOWN`

Пауза после исчерпания всех retry:

```ini
COOLDOWN=900
```

`900` секунд = 15 минут.

Cooldown привязан к префиксу, на котором произошла ошибка. Если провайдер за это время выдаст другой префикс, новый префикс может быть обработан сразу.

## `RESYNC_INTERVAL`

Интервал полной сверки состояния даже без изменения IPv6-префикса:

```ini
RESYNC_INTERVAL=900
```

Это позволяет восстановить состояние после ручного изменения DNS, удаления IPv6-адреса и некоторых других внешних изменений.

## `FIREWALL_HOOK`

Путь до firewall hook:

```ini
FIREWALL_HOOK=/usr/local/sbin/ipv6-prefix-ddns-firewall
```

Для полного отключения hook:

```ini
FIREWALL_HOOK=
```

## `RECORD`

Формат:

```text
RECORD=<domain-within-zone>,<hex-suffix>,<proxied>
```

Примеры:

```ini
RECORD=app,10,false
RECORD=ssh,20,false
RECORD=api,30,true
RECORD=@,40,false
```

Для зоны:

```text
example.ru
```

и префикса:

```text
2a00:1234:5678:abcd::/64
```

получатся:

```text
app.example.ru → 2a00:1234:5678:abcd::10
ssh.example.ru → 2a00:1234:5678:abcd::20
api.example.ru → 2a00:1234:5678:abcd::30
example.ru     → 2a00:1234:5678:abcd::40
```

Суффикс интерпретируется как hexadecimal.

Разные DNS-имена могут использовать одинаковый суффикс независимо от `proxied`:

```ini
RECORD=app,10,true
RECORD=direct,10,false
```

Обе записи используют один origin IPv6-адрес. Каждая синхронизируется со своим
значением `proxied`, а адрес добавляется в NetworkManager один раз. DNS-имя
в конфигурации должно оставаться уникальным, чтобы записи не перезаписывали
настройки друг друга.

Эквивалентны, например:

```text
10
::10
0x10
```

`proxied`:

```text
false → Cloudflare DNS only
true  → Cloudflare Proxy
```

Для обычного SSH следует использовать:

```ini
RECORD=ssh,20,false
```

Для текущей рекомендуемой конфигурации:

```ini
RECORD=app,10,false
RECORD=ssh,20,false
```

обе записи работают в режиме DNS only.

Имена и IPv6-суффиксы должны быть уникальными.

---

# 6. Важное ограничение firewall-hook

Сам DDNS-клиент позволяет задавать произвольное количество `RECORD`.

Текущая реализация `ipv6-prefix-ddns-firewall`, однако, присваивает специальное значение именно двум суффиксам:

```text
::10 → application
::20 → SSH
```

Поэтому при включённом firewall-hook в конфигурации должны присутствовать:

```ini
RECORD=app,10,false
RECORD=ssh,20,false
```

Доменные имена могут отличаться; firewall ищет записи по суффиксу, а не по hostname.

Host firewall выполняет следующую политику:

```text
Host INPUT:
  APP_IP TCP/80,443  RETURN → UFW → dynamic ALLOW
  SSH_IP TCP/42      RETURN → UFW → dynamic ALLOW
  прочие NEW TCP на APP_IP/SSH_IP  DROP
  остальные host packets          передаются UFW

Docker / k3d forwarding from INTERFACE:
  original destination APP_IP:80   ALLOW
  original destination APP_IP:443  ALLOW
  любой другой NEW forwarded flow  DROP
```

Docker-specific policy использует conntrack original destination, поскольку к моменту прохождения `DOCKER-USER` Docker уже выполнил DNAT. Обычная проверка `-d APP_IP` в этой цепочке недостаточна.

Strict Docker policy предполагает, что данный хост не используется как универсальный IPv6 router: любые другие NEW forwarded connections, пришедшие через `INTERFACE`, блокируются.

Текущая версия hook не ограничивает весь Docker traffic исключительно адресом `::10`: прочий трафик после проверки также возвращается в стандартные Docker rules.

---

# 7. Установка

Из каталога проекта:

```bash
cd ddns-client
```

Создайте системные каталоги:

```bash
sudo install -d \
    -o root \
    -g root \
    -m 0755 \
    /etc/ipv6-prefix-ddns

sudo install -d \
    -o root \
    -g root \
    -m 0750 \
    /var/lib/ipv6-prefix-ddns
```

Установите daemon:

```bash
sudo install \
    -o root \
    -g root \
    -m 0750 \
    ipv6-prefix-ddns.py \
    /usr/local/sbin/ipv6-prefix-ddns
```

Установите firewall hook:

```bash
sudo install \
    -o root \
    -g root \
    -m 0750 \
    ipv6-prefix-ddns-firewall \
    /usr/local/sbin/ipv6-prefix-ddns-firewall
```

Установите конфигурацию:

```bash
sudo install \
    -o root \
    -g root \
    -m 0600 \
    config.conf \
    /etc/ipv6-prefix-ddns/config.conf
```

Установите systemd unit:

```bash
sudo install \
    -o root \
    -g root \
    -m 0644 \
    ipv6-prefix-ddns.service \
    /etc/systemd/system/ipv6-prefix-ddns.service
```

Перечитайте конфигурацию systemd:

```bash
sudo systemctl daemon-reload
```

Проверить unit:

```bash
sudo systemd-analyze verify \
    /etc/systemd/system/ipv6-prefix-ddns.service
```

Включить службу:

```bash
sudo systemctl enable --now ipv6-prefix-ddns.service
```

Проверить:

```bash
systemctl status ipv6-prefix-ddns.service
```

---

# 8. Стандартный алгоритм работы

После запуска daemon:

```text
1. Загружает config.conf.
2. Загружает последнее успешное состояние state.json.
3. Читает глобальные IPv6 на INTERFACE.
4. Исключает адреса, суффиксы которых принадлежат RECORD.
5. Предпочитает dynamic non-temporary IPv6.
6. Вычисляет текущий IPv6 prefix.
7. Для каждого RECORD вычисляет <PREFIX>::<suffix>.
8. Сравнивает адреса с ipv6.addresses NetworkManager.
9. При необходимости заменяет ipv6.addresses.
10. Выполняет nmcli device reapply.
11. Если reapply не помог — выполняет connection up.
12. Проверяет, что все управляемые адреса появились на интерфейсе.
13. Создаёт pending-state.json.
14. При наличии FIREWALL_HOOK обновляет firewall.
15. Проверяет каждую Cloudflare AAAA-запись.
16. Создаёт отсутствующие записи.
17. PATCH'ит изменившиеся записи.
18. Сохраняет успешное состояние в state.json.
```

DNS не обновляется до тех пор, пока новый IPv6 фактически не появился на локальном интерфейсе.

Файлы состояния:

```text
/var/lib/ipv6-prefix-ddns/state.json
/var/lib/ipv6-prefix-ddns/pending-state.json
```

`pending-state.json` существует во время reconcile и передаётся firewall-hook.

---

# 9. NetworkManager и владение адресами

Служба считает:

```text
ipv6.addresses
```

указанного профиля NetworkManager своей зоной ответственности.

Если в профиле вручную заданы дополнительные статические IPv6, отсутствующие в `RECORD=`, daemon удалит их из `ipv6.addresses` при следующей синхронизации.

Поэтому все управляемые дополнительные IPv6 данного профиля следует описывать через `RECORD=`.

SLAAC-адрес при этом сохраняется, поскольку профиль остаётся в режиме:

```text
ipv6.method=auto
```

---

# 10. Retry и cooldown

При ошибке полной синхронизации daemon повторяет операцию согласно:

```ini
RETRY_COUNT=5
RETRY_DELAY=5
```

То есть:

```text
attempt 1
   ↓
5 seconds
   ↓
attempt 2
   ↓
5 seconds
   ↓
...
attempt 5
```

После последней неудачи:

```ini
COOLDOWN=900
```

daemon прекращает попытки для данного префикса примерно на 15 минут.

Если за это время обнаружен другой IPv6-префикс, он обрабатывается отдельно.

---

# 11. Проверка до первого запуска

Проверить Python:

```bash
python3 -m py_compile ipv6-prefix-ddns.py
```

Проверить обработку конфигурации (из каталога `infra/ddns-client`):

```bash
python3 -m unittest discover -s tests -v
```

Проверить Bash:

```bash
bash -n ipv6-prefix-ddns-firewall
```

Проверить интерфейс:

```bash
ip -6 addr show dev enp4s0 scope global
```

Проверить NetworkManager:

```bash
nmcli device
nmcli connection show
```

Проверить Docker:

```bash
docker info
```

Проверить `DOCKER-USER`:

```bash
sudo ip6tables -nL DOCKER-USER
```

Проверить UFW:

```bash
sudo ufw status verbose
```

---

# 12. Проверка после запуска

## Состояние systemd

```bash
systemctl status ipv6-prefix-ddns.service
```

Должно быть:

```text
Active: active (running)
```

## Логи

```bash
journalctl -u ipv6-prefix-ddns.service -f
```

После успешного reconcile ожидаются сообщения вида:

```text
IPv6 prefix change detected: ...
reconciling prefix ...
desired record: app.example.ru -> ...
desired record: ssh.example.ru -> ...
updating NetworkManager IPv6 reservations ...
running firewall hook ...
updating Cloudflare AAAA ...
synchronization completed successfully ...
```

Firewall hook отдельно пишет в journal:

```bash
journalctl -t ipv6-prefix-ddns-firewall
```

## IPv6 интерфейса

```bash
ip -6 addr show dev enp4s0 scope global
```

При `RECORD=app,10,false` и `RECORD=ssh,20,false` должны присутствовать:

```text
<PREFIX>::10
<PREFIX>::20
```

плюс SLAAC-адрес.

## NetworkManager

```bash
nmcli -g ipv6.addresses \
    connection show "Проводное подключение 1"
```

## State

```bash
sudo cat /var/lib/ipv6-prefix-ddns/state.json
```

или:

```bash
sudo jq . /var/lib/ipv6-prefix-ddns/state.json
```

Пример:

```json
{
  "prefix": "2a00:1234:5678:abcd::/64",
  "records": {
    "app.example.ru": {
      "address": "2a00:1234:5678:abcd::10",
      "proxied": false,
      "suffix": "10"
    },
    "ssh.example.ru": {
      "address": "2a00:1234:5678:abcd::20",
      "proxied": false,
      "suffix": "20"
    }
  }
}
```

---

# 13. Проверка DNS

Для DNS-only записи:

```bash
dig +short AAAA app.example.ru
dig +short AAAA ssh.example.ru
```

Ожидаются управляемые IPv6:

```text
2a00:1234:5678:abcd::10
2a00:1234:5678:abcd::20
```

При:

```text
proxied=true
```

DNS будет возвращать адреса Cloudflare, а не origin IPv6. Поэтому сравнивать `dig` с `<PREFIX>::suffix` можно только для DNS-only записей.

---

# 14. Проверка firewall

Host chain:

```bash
sudo ip6tables -nvL IPV6-DDNS-HOST
```

Docker:

```bash
sudo ip6tables -nvL IPV6-DDNS-DOCKER
```

Проверить переход из INPUT:

```bash
sudo ip6tables -S INPUT | grep IPV6-DDNS
```

Проверить Docker jump:

```bash
sudo ip6tables -S | grep IPV6-DDNS
```

Проверить UFW:

```bash
sudo ufw status verbose
```

Проверки следует повторять после `ufw reload` и после перезапуска Docker.

---

# 15. Проверка доступности снаружи

Тесты необходимо выполнять с устройства, находящегося в другой IPv6-сети, например через мобильную сеть или внешний сервер.

TLS и автоматическое продление сертификатов настраиваются отдельно
в [k3d-инфраструктуре](../k3d-infra/README.md#https-и-сертификаты).
DDNS и открытый порт 443 сами по себе сертификат не устанавливают.

Проверка приложения:

```bash
curl -6 -I https://app.example.ru/
```

или для HTTP:

```bash
curl -6 -I http://app.example.ru/
```

Проверка SSH:

```bash
ssh -6 user@ssh.example.ru
```

Проверка, что SSH не доступен через application address:

```bash
nc -6 -vz app.example.ru 22
```

Соединение должно блокироваться.

Проверка, что HTTP/HTTPS не доступны через SSH address:

```bash
nc -6 -vz ssh.example.ru 80
nc -6 -vz ssh.example.ru 443
```

Они также должны блокироваться.

При тестировании учитывайте, что firewall-hook блокирует Docker traffic на `::20`, но текущая версия не гарантирует, что опубликованные Docker-порты доступны исключительно на `::10`.

---

# 16. Проверка k3d

```bash
k3d cluster list
```

```bash
kubectl get nodes
```

```bash
kubectl get ingress -A
```

```bash
kubectl get svc -A
```

Проверить server load balancer:

```bash
docker ps --format \
    'table {{.Names}}\t{{.Ports}}' \
    | grep serverlb
```

Должны быть опубликованы необходимые ingress-порты.

---

# 17. Тест смены IPv6-префикса

Перед тестом:

```bash
ip -6 addr show dev enp4s0 scope global
```

```bash
dig +short AAAA app.example.ru
dig +short AAAA ssh.example.ru
```

```bash
sudo jq . /var/lib/ipv6-prefix-ddns/state.json
```

Затем выполните реальное PPPoE/WAN reconnect на маршрутизаторе.

После получения нового SLAAC-адреса наблюдайте:

```bash
journalctl -u ipv6-prefix-ddns.service -f
```

Ожидаемая последовательность:

```text
старый prefix
     ↓
новый SLAAC address
     ↓
prefix change detected
     ↓
NetworkManager получает NEW_PREFIX::10 и ::20
     ↓
firewall обновляется
     ↓
Cloudflare AAAA обновляются
     ↓
state.json сохраняется
```

После этого повторите:

```bash
ip -6 addr show dev enp4s0 scope global
dig +short AAAA app.example.ru
dig +short AAAA ssh.example.ru
```

и внешний:

```bash
curl -6 -I https://app.example.ru/
ssh -6 user@ssh.example.ru
```

---

# 18. Мониторинг

Основные команды для ежедневной эксплуатации:

```bash
systemctl is-active ipv6-prefix-ddns.service
```

```bash
systemctl status ipv6-prefix-ddns.service
```

```bash
journalctl -u ipv6-prefix-ddns.service -n 100
```

```bash
journalctl -u ipv6-prefix-ddns.service -f
```

Ошибки синхронизации:

```bash
journalctl -u ipv6-prefix-ddns.service \
    | grep -E 'ERROR|failed|cooldown|Cloudflare'
```

Firewall:

```bash
journalctl -t ipv6-prefix-ddns-firewall -n 100
```

Текущий prefix:

```bash
sudo jq -r '.prefix' \
    /var/lib/ipv6-prefix-ddns/state.json
```

Последняя успешная синхронизация:

```bash
sudo jq -r '.last_success' \
    /var/lib/ipv6-prefix-ddns/state.json
```

Все зарегистрированные адреса:

```bash
sudo jq -r \
    '.records | to_entries[] | "\(.key) -> \(.value.address)"' \
    /var/lib/ipv6-prefix-ddns/state.json
```

DNS:

```bash
dig +short AAAA app.example.ru
dig +short AAAA ssh.example.ru
```

Приложение:

```bash
curl -6 -fsS -o /dev/null \
    https://app.example.ru/
```

SSH port:

```bash
nc -6 -vz ssh.example.ru 42
```

k3d:

```bash
k3d cluster list
kubectl get nodes
kubectl get pods -A
kubectl get ingress -A
```

Docker firewall:

```bash
sudo ip6tables -S INPUT | grep IPV6-DDNS
sudo ip6tables -S | grep IPV6-DDNS

sudo ip6tables -nvL IPV6-DDNS-HOST
sudo ip6tables -nvL IPV6-DDNS-DOCKER
```

Проверка отсутствия повторных jump'ов:
```bash
sudo systemctl restart ipv6-prefix-ddns.service
sudo systemctl restart ipv6-prefix-ddns.service
sudo systemctl restart ipv6-prefix-ddns.service

sudo ip6tables -S INPUT \
    | grep -c -- '-j IPV6-DDNS-HOST'

sudo ip6tables -S DOCKER-USER \
    | grep -c -- '-j IPV6-DDNS-DOCKER'
```
Обе команды должны вернуть
```bash
1
```

Проверка строгой политики с внешней IPv6-сети:
```bash
nc -6 -vz app.example.ru 80
nc -6 -vz app.example.ru 443

nc -6 -vz app.example.ru 22
nc -6 -vz ssh.example.ru 42
nc -6 -vz ssh.example.ru 80
nc -6 -vz ssh.example.ru 443
```
Ожидается:
```bash
app:80     success
app:443    success
app:22     blocked

ssh:42     success
ssh:80     blocked
ssh:443    blocked
```


---

# 19. Изменение конфигурации

После изменения:

```text
/etc/ipv6-prefix-ddns/config.conf
```

перезапустите daemon:

```bash
sudo systemctl restart ipv6-prefix-ddns.service
```

и наблюдайте журнал:

```bash
journalctl -u ipv6-prefix-ddns.service -f
```

При старте daemon всегда выполняет полный reconcile, поэтому изменения `RECORD`, suffix или `proxied` применяются сразу.

---

# 20. Обновление службы

После обновления файлов проекта:

```bash
sudo install \
    -o root -g root -m 0750 \
    ipv6-prefix-ddns.py \
    /usr/local/sbin/ipv6-prefix-ddns

sudo install \
    -o root -g root -m 0750 \
    ipv6-prefix-ddns-firewall \
    /usr/local/sbin/ipv6-prefix-ddns-firewall
```

Если unit также изменился:

```bash
sudo install \
    -o root -g root -m 0644 \
    ipv6-prefix-ddns.service \
    /etc/systemd/system/ipv6-prefix-ddns.service

sudo systemctl daemon-reload
```

После обновления:

```bash
sudo systemctl restart ipv6-prefix-ddns.service
```

Проверить:

```bash
systemctl status ipv6-prefix-ddns.service
journalctl -u ipv6-prefix-ddns.service -n 100
```

---

# 21. Troubleshooting

### `no non-managed global IPv6 address found`

Проверить:

```bash
ip -6 addr show dev <INTERFACE> scope global
```

На интерфейсе должен существовать глобальный SLAAC/DHCPv6 IPv6.

### `managed IPv6 addresses did not appear`

Проверить:

```bash
nmcli connection show
nmcli device
ip -6 addr show dev <INTERFACE>
```

Также убедитесь, что `CONNECTION` действительно соответствует `INTERFACE`.

### `Cloudflare HTTP 401/403`

Проверить:

```text
CF_API_TOKEN
CF_ZONE_ID
```

Token должен иметь `DNS Write` для нужной зоны.

### `DOCKER-USER IPv6 chain not found`

Проверить:

```bash
sudo ip6tables -nL DOCKER-USER
```

Для IPv4-only bridge отсутствие IPv6 `DOCKER-USER` допустимо: проверьте
`sudo ip6tables -S FORWARD` и цепочку `IPV6-DDNS-DOCKER`. Docker должен
использовать iptables backend.

После изменения Docker:

```bash
sudo systemctl restart ipv6-prefix-ddns.service
```

### Firewall работает, но Docker-сервис доступен по неожиданному IPv6

Текущий hook гарантированно блокирует Docker traffic на SSH-адресе `::20`, но не ограничивает Docker исключительно адресом `::10`.

Для строгой модели:

```text
Docker доступен только через ::10
SSH доступен только через ::20
```

потребуется более строгая политика в `IPV6-DDNS-DOCKER`.

### После `ufw reload` изменилось поведение

Перезапустите DDNS daemon:

```bash
sudo systemctl restart ipv6-prefix-ddns.service
```

и проверьте:

```bash
sudo ip6tables -S INPUT | grep IPV6-DDNS
```

---

# 22. Безопасность

`config.conf` содержит Cloudflare API Token и должен иметь права:

```text
0600 root:root
```

Проверить:

```bash
sudo stat /etc/ipv6-prefix-ddns/config.conf
```

Используйте Cloudflare token только с минимально необходимым `DNS Write` и только для требуемой зоны.

Для SSH рекомендуется:

```text
PasswordAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
```

Не публикуйте Kubernetes API, PostgreSQL или backend management endpoints непосредственно в Internet без необходимости.

Для внешнего доступа публикуйте только ingress-порты, обычно:

```text
80/tcp
443/tcp
```

и SSH на отдельном IPv6:

```text
42/tcp → <PREFIX>::20
```
