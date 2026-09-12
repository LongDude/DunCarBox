# Управление DunCarBox через Makefile

Команды выполняются из корня репозитория на Linux/Bash. `make help` показывает
полный список. Нужны GNU Make, Python 3.10+, Docker Engine, OpenTofu >= 1.8,
kubectl и curl; для DNS-проверок — `dig`, для DDNS — NetworkManager, iproute2,
jq, systemd и UFW с IPv6. Запускайте `make` от своего пользователя: только
установка/управление DDNS и чтение firewall используют `sudo`.

## Первая установка

1. Проверьте `infra/k3d-infra/terraform.tfvars`: домен `ingress_host`, имя
   кластера, registry и порты. Настройки читаются через OpenTofu с его обычными
   приоритетами переменных; Makefile не содержит второй копии этих значений.
2. Подготовьте AAAA-записи в Cloudflare или DDNS-конфигурацию, как описано ниже.
3. Запустите:

   ```bash
   make init
   ```

`init` устанавливает провайдеры, проверяет наличие реквизитов PostgreSQL,
создаёт кластер и registry отдельным targeted apply, собирает и публикует оба
образа, подготавливает cert-manager и DNS-01 token, применяет приложение,
ждёт rollout и готовности сертификата. Отсутствующий пароль PostgreSQL и
Cloudflare token запрашиваются скрытым вводом. Существующий пароль не меняется.
При отсутствии реквизитов в неинтерактивном запуске команда завершается с
инструкцией; можно заранее выполнить `make configure` в терминале.

Новый пароль сохраняется с правами 0600 в игнорируемом Git файле
`infra/k3d-infra/zz-operations.auto.tfvars.json`. На существующей БД всегда
используйте её текущий пароль. Cloudflare token передаётся в Kubernetes Secret
через stdin; Makefile не сохраняет его в tfvars или аргументах процесса.

Создание кластера подтверждается штатным запросом OpenTofu. `make deploy`,
`make init`, `make ssl-issue` и `make ssl-import` применяют план приложения
сразу после его вывода. Для отдельного просмотра перед применением:

```bash
make cluster-init
make images
make ssl-install
make ssl-token
make plan
# Проверьте план выше.
make apply
make ssl-check
```

`cluster-init` подходит и для подготовки к установке собственного сертификата.
Существующий cert-manager используется без смены версии; новая установка
использует v1.21.2. Изменение `CERT_MANAGER_VERSION` выбирает версию только
для новой установки. [Порядок установки cert-manager](https://cert-manager.io/docs/installation/kubectl/).

## Независимые образы и обновления

```bash
make image-backend      # build + push только backend
make image-frontend     # build + push только frontend
make images             # оба компонента
make image-tags         # опубликованные теги и последние сборки
make deploy             # новый plan + apply + ожидание rollout
```

Тег включает commit, UTC-время и случайный идентификатор. Новые теги создаются
и при повторной сборке того же commit с локальными изменениями. Пользователю
не нужны `export TF_VAR_image_tag` или ручная подстановка тегов.

| Файл | Назначение |
| --- | --- |
| `backend/.tofu/image-tag` | Последний успешно опубликованный backend |
| `frontend/.tofu/image-tag` | Последний успешно опубликованный frontend |
| `<component>/.tofu/image-built.json` | Последняя успешная локальная сборка: тег, registry и ID |

Эти файлы локальные и игнорируются Git. OpenTofu читает каждый `image-tag`
через отдельную local-переменную. Frontend и его init container используют
один frontend tag. Новый backend tag не меняет frontend tag, и наоборот.
Обновление тега происходит атомарно **после успешного push**. Ошибка сборки
или публикации не переключает выбранную версию приложения.

Для раздельной сборки и публикации:

```bash
make image-build-frontend
make image-push-frontend
make deploy
```

Неудачный push можно повторить. Если локальный образ под сохранённым тегом
изменился, публикация отклоняется: сначала нужна новая сборка.
Отдельные процессы Make сериализуются, чтобы не перезаписать теги или план
при параллельном запуске. Сохранённый план также содержит контрольные суммы
конфигурации: после изменения тегов, tfvars, манифестов или самого плана
`make apply` потребует новый `make plan`. После успешного apply план удаляется.

Миграция существующей установки: старый `image_tag` в tfvars используется
только пока у соответствующего компонента нет своего файла `image-tag`.
После публикации обоих компонентов старую переменную можно убрать. Новое
выходное значение OpenTofu — `application_image_tags`, карта из двух тегов.
В новом checkout выполните `make images` или восстановите локальные файлы
с тегами уже опубликованных образов. `unbuilt` никогда не применяется к
Deployment. Локальные теги нужно переносить вместе с инфраструктурными
настройками, если развёртывание запускается с другой машины.

## Сертификаты

Выпуск/продление управляется cert-manager при `manage_certificate=true`.
Для Cloudflare DNS-01 token нужны `Zone:DNS:Edit` и `Zone:Zone:Read`,
ограниченные нужной DNS-зоной.

```bash
make ssl-install
make ssl-token                           # скрытый ввод token
make ssl-token CF_TOKEN_FILE=/secure/cloudflare-token
make ssl-issue                           # подготовка + deploy + ожидание Ready
make ssl-check                           # Ready и HTTPS с проверкой доверия/SAN
```

После `Certificate Ready` Traefik может ещё короткое время отдавать предыдущий
сертификат. `ssl-check` повторяет проверку при ошибке сертификата до 10 раз с
паузой 2 секунды. Постоянная ошибка сертификата завершает команду ненулевым
кодом; HTTP/API-ошибки не маскируются этими повторными попытками.

`ssl-issue` использует уже установленный Secret; `ssl-token` обновляет его
явно. DNS-01 не требует входящего HTTP-доступа к origin. Убедитесь, что
cert-manager имеет исходящий доступ к DNS, Cloudflare API и ACME API.
[Cloudflare DNS-01](https://cert-manager.io/docs/configuration/acme/dns01/cloudflare/).

Для собственного сертификата:

```bash
make ssl-import TLS_CERT=/secure/fullchain.pem TLS_KEY=/secure/privkey.pem
```

Команда устанавливает TLS Secret, сохраняет `manage_certificate=false` и
имя Secret в локальных tfvars, применяет конфигурацию и проверяет HTTPS.
При переходе с cert-manager используется отдельное имя Secret с `-manual`,
чтобы не конфликтовать с его сертификатом. Продление импортированного
сертификата выполняется владельцем; повторите команду с новыми файлами.
Для возврата к cert-manager измените `manage_certificate` и `tls_secret_name`
в `zz-operations.auto.tfvars.json`, затем выполните `make ssl-issue`.

## DDNS

```bash
cp infra/ddns-client/config.conf.example infra/ddns-client/config.conf
# Заполните INTERFACE, CONNECTION, CF_ZONE, CF_ZONE_ID, CF_API_TOKEN и RECORD.
make ddns-install
make ddns-status
make ddns-logs
```

Для использования firewall включите
`FIREWALL_HOOK=/usr/local/sbin/ipv6-prefix-ddns-firewall`; для обхода HAPP
ответами с адресов `::10` и `::20` — `DIRECT_ROUTING=true`.
Пример для зоны `nikaeru.com`:

```ini
RECORD=app,10,false
RECORD=app-proxy,10,true
RECORD=ssh,20,false
```

`ddns-install` валидирует конфигурацию до установки, создаёт каталоги,
устанавливает скрипты/unit, включает автозапуск и перезапускает службу.
Произвольный путь: `make ddns-install DDNS_CONFIG=/path/config.conf`.
Тот же `DDNS_CONFIG` используйте для последующих проверок.

```bash
make ddns-start
make ddns-stop
make ddns-restart
make ddns-enable      # только автозапуск
make ddns-disable     # только автозапуск; не останавливает службу
```

После изменения конфигурации в репозитории повторите `ddns-install`.
`ddns-restart` читает уже установленный `/etc/ipv6-prefix-ddns/config.conf`.
Остановка DDNS не удаляет IPv6-адреса, firewall и policy rules.

## Проверки после запуска

```bash
make status
make check-ipv6
make check-dns
make check-local
make check-service
make check-proxy
# Или все проверки, с общим ненулевым exit code при любой ошибке:
make check
```

- `check-ipv6`: текущий префикс и адреса, direct policy rules/table 106,
  выбор физического интерфейса для ответов, вывод IPv6 firewall с counters,
  проверка переходов и разрешения TCP/80,443. Firewall только читается.
- `check-dns`: каждый RECORD сравнивается с Cloudflare API (origin AAAA и
  proxied) и публичным DNS. Для DNS-only ожидается текущий origin IPv6,
  для proxied — адреса proxy. Резолвер: `DNS_SERVER=1.1.1.1` по умолчанию.
  DNS-записи SSH тоже проверяются, но соединение с SSH не открывается.
- `check-local`: origin через `ORIGIN_IP=127.0.0.1`, с правильными Host/SNI,
  проверкой сертификата, главной страницы, health и каталога коробок.
- `check-service`: те же HTTP-проверки публичного домена через DNS.
- `check-proxy`: отдельный домен `app-proxy.<zone>` (выводится из
  `ingress_host`), DNS, HTTPS, ответ приложения и заголовок `CF-Ray`.
  Другой домен: `make check-proxy PROXY_HOST=app-proxy.example.com`.

HTTP 503, redirect вместо ожидаемого ответа, HTML вместо health JSON и
ошибка TLS завершают проверку ненулевым кодом. Проверки не используют `-k`.
Переменные HTTP(S)_PROXY отключены для curl; системная маршрутизация через
TUN по-прежнему действует. Локальное подключение к своему IPv6 не проверяет
firewall роутера и доступность из Интернета: публичные HTTP-проверки нужно
повторить с внешней сети. SSH-подключения пока полностью исключены; порт 42
будет настроен отдельно.

### Особенности app-proxy

AAAA с `proxied=true` недостаточно для успешного HTTPS: Cloudflare должен
иметь edge-сертификат именно для `app-proxy.<zone>`. В обычной full setup зоне
Universal SSL покрывает только зону и первый уровень поддоменов. Для имени
`app-proxy.nikaeru.com` достаточно сертификата `*.nikaeru.com`. Сертификат origin от cert-manager не расширяет
покрытие сертификата Cloudflare. [Ограничения Universal SSL](https://developers.cloudflare.com/ssl/edge-certificates/universal-ssl/limitations/).

Также origin должен принимать Host/SNI этого имени: настройте соответствующий
Ingress/сертификат либо поддерживаемое вашей Cloudflare-конфигурацией
переопределение origin Host/SNI на `ingress_host`. Makefile диагностирует
этот путь, но не меняет DNS-записи и настройки зоны Cloudflare.

Если TLS завершается сразу с `alert handshake failure` и сертификат не
предъявляется, проверьте состояние edge-сертификата Cloudflare и режим Proxy.
Для текущей схемы используйте `app-proxy.nikaeru.com`, затем запускайте
`PROXY_HOST=app-proxy.nikaeru.com make check-proxy`.

## Проверка самих скриптов

```bash
make test-ops
make test-ddns
```

`test-ops` проверяет независимость тегов, поведение при ошибках build/push,
защиту от устаревшего плана, обработку HTTP/TLS и передачу token через stdin.
Обычный `test-ddns` пропускает сетевые тесты. Для проверки реальных пакетов
в изолированном namespace используйте команду из [DDNS README](ddns-client/README.md).
