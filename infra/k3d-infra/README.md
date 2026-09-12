# DunCarBox в k3d через OpenTofu

Docker Compose используется для разработки. Серверная конфигурация собирается
Kustomize и применяется OpenTofu в namespace `duncarbox`.

## Структура

- `cluster.tf` — существующий k3d-кластер и встроенный registry.
- `.tofu/` — overlay для k3d: namespace, Ingress и StorageClass `local-path`.
- `../../backend/.tofu/` — Deployment, Service и ConfigMap backend.
- `../../frontend/.tofu/` — Deployment и Service nginx с собранным frontend.
- `../postgres/.tofu/` — StatefulSet PostgreSQL 17, Service `db` и PVC на 10 GiB.
- `tls.tf` — cert-manager Issuer и Certificate с автоматическим продлением.
- `kustomization.tf` — HCL overlay: адреса образов, тег релиза, Secret с реквизитами
  БД и применение ресурсов в порядке `ids_prio` провайдера.

Маршрут запросов: порт 443 сервера → Traefik (TLS) → `frontend:80` → nginx →
`backend:8000` для `/api/`. Backend подключается к `db:5432`. Сервисы используют
ClusterIP; отдельные порты backend и PostgreSQL на хосте не публикуются.
Ingress обслуживает `https://app.nikaeru.com/`; hostname задаётся переменной
`ingress_host` в `terraform.tfvars`. Дополнительное имя для Cloudflare Proxy
задаётся `proxy_ingress_host` (в текущем примере `app-proxy.nikaeru.com`);
оба имени входят в правила Ingress и SAN сертификата. HTTP перенаправляется на HTTPS.
Запросы `/api/` идут по тому же HTTPS origin; nginx сохраняет
`X-Forwarded-Proto`, полученный от Traefik. TLS завершается на Ingress,
внутрикластерные соединения и health probes используют HTTP.
Uvicorn доверяет forwarded headers внутри кластера (`FORWARDED_ALLOW_IPS=*`),
поэтому генерируемые backend redirects также сохраняют HTTPS. Backend должен
оставаться внутренним ClusterIP Service, доступным только доверенным клиентам.

## IPv4/IPv6, HAPP и UFW

В `cluster.tf` для портов 80/443 намеренно не задан `host`: Docker публикует
их на `0.0.0.0` и `[::]`. Привязка `host = "0.0.0.0"` ограничивает публикацию
IPv4. Kubernetes API по-прежнему привязан к `127.0.0.1`.

Используется IPv4-only bridge k3d и включённый Docker `userland-proxy`
(значение по умолчанию). Прокси принимает IPv6 на хосте и соединяется с
IPv4 контейнера; IPv6 внутри Kubernetes для этого не требуется.
Не отключайте `userland-proxy` и не переводите bridge на native IPv6 DNAT
без изменения маршрутизации ответов: до обратного SNAT у пакета контейнерный
исходный адрес, поэтому правило `from <PUBLIC_IPV6>/128` его не перехватит.
См. [публикацию портов Docker](https://docs.docker.com/engine/network/port-publishing/).

DDNS-клиент с `DIRECT_ROUTING=true` выводит ответы только с текущих адресов
`<PREFIX>::10` и `<PREFIX>::20` через физический шлюз. Остальной трафик
продолжает использовать маршруты HAPP. UFW управляет хостовым `INPUT`;
DDNS-hook добавляет динамические разрешения после пользовательских правил UFW.
Установка и проверка описаны в [DDNS README](../ddns-client/README.md#ipv6-happ-и-ufw).

При обновлении существующего кластера сначала установите DDNS/firewall,
затем проверьте план изменения портов:

```bash
tofu -chdir=infra/k3d-infra plan -target=k3d_cluster.main -out=ipv6.tfplan
tofu -chdir=infra/k3d-infra apply ipv6.tfplan
rm infra/k3d-infra/ipv6.tfplan
sudo systemctl restart ipv6-prefix-ddns.service
docker ps --format 'table {{.Names}}\t{{.Ports}}'
ss -lnt6
```

Это разовое целевое обновление сетевых портов. Остальные переменные OpenTofu
задаются как в разделе запуска ниже. Провайдер `agynio/k3d` 0.2.3 обновляет
портовые mappings через замену `serverlb`, без удаления server/agent nodes.
Во время замены HTTP/HTTPS и Kubernetes API кратковременно недоступны.
Ожидаемый план для данного изменения: `0 to add, 1 to change, 0 to destroy`.
После применения проверьте наличие `[::]:80` и `[::]:443`, а затем подключение
из внешней IPv6-сети; публикация портов сама по себе не настраивает TLS.

## Запуск

Основные сценарии автоматизированы в корневом Makefile.
Полная инструкция: [infra/OPERATIONS.md](../OPERATIONS.md).

```bash
make help
make init
```

Перед первым запуском проверьте `terraform.tfvars` и DNS-записи домена.
`init` подготавливает провайдеры и реквизиты, создаёт кластер/registry,
собирает и публикует образы с независимыми тегами, устанавливает cert-manager,
готовит Cloudflare Secret для DNS-01 и развёртывает приложение.
Уже заданный пароль PostgreSQL сохраняется; отсутствующий запрашивается
скрытым вводом и записывается в локальный игнорируемый tfvars с правами 0600.

Кластер создаётся отдельным targeted apply до общего плана: провайдер
Kustomization требует существующий kubeconfig. Для выполнения по шагам:

```bash
make cluster-init
make images
make ssl-install
make ssl-token
make plan
make apply
make ssl-check
make check
```

Backend ждёт PostgreSQL, frontend ждёт успешного ответа backend health через
init container. `apply` ожидает готовности Deployment и StatefulSet, после
него Makefile проверяет rollout обоих компонентов. Выпуск TLS-сертификата
проверяется отдельно через `ssl-check`.

Для DDNS используйте `make ddns-install`, подготовив его `config.conf`.
SSH-подключения в проверках временно пропускаются; будущий порт — 42.

## HTTPS и сертификаты

По умолчанию `manage_certificate=true`: OpenTofu создаёт namespaced Issuer
Let’s Encrypt и Certificate `duncarbox-tls`. cert-manager выпускает сертификат
для `ingress_host`, сохраняет ключ и цепочку в Secret `tls_secret_name` и
автоматически продлевает их. Traefik подхватывает обновлённый Secret.
Ключ сертификата, ключ ACME-аккаунта и Cloudflare token не проходят через OpenTofu state.
По умолчанию используется DNS-01 через Cloudflare (`acme_solver="cloudflare"`):
cert-manager создаёт временную TXT-запись `_acme-challenge.app.nikaeru.com`.
Это работает и с IPv6-only origin при IPv4-only pod network; HTTP self-check
из такого pod не сможет подключиться к origin, имеющему только AAAA.

### Подготовка DNS и cert-manager

1. DNS `app.nikaeru.com` должен указывать на этот сервер. Для DDNS используйте
   `RECORD=app,10,false` в зоне `nikaeru.com` (DNS-only). Все опубликованные
   A/AAAA должны вести на доступный сервер; удалите устаревшие записи.
   Порт 80 обслуживает перенаправление, порт 443 — HTTPS.
   При IPv6-only origin проверяйте доступ из внешней IPv6-сети. DNS-01
   требует исходящего доступа cert-manager к Cloudflare API, ACME API и DNS.
   Сам origin для DNS-01 проверки не обязан быть доступен извне.
2. После создания кластера, **до общего OpenTofu plan/apply**, установите
   cert-manager один раз (если он уже установлен, используйте имеющуюся
   установку):

   ```bash
   kubectl --context k3d-duncarbox apply -f \
     https://github.com/cert-manager/cert-manager/releases/download/v1.21.2/cert-manager.yaml
   kubectl --context k3d-duncarbox -n cert-manager rollout status \
     deployment/cert-manager --timeout=180s
   kubectl --context k3d-duncarbox -n cert-manager rollout status \
     deployment/cert-manager-cainjector --timeout=180s
   kubectl --context k3d-duncarbox -n cert-manager rollout status \
     deployment/cert-manager-webhook --timeout=180s
   ```

   cert-manager — отдельный кластерный компонент, вне state приложения.
   Установка CRD нужна до применения `tls.tf`. Если webhook ещё не готов
   принимать запросы, дождитесь его готовности и повторите план.
   Если установлен `cmctl`, проверка: `cmctl --context k3d-duncarbox check api --wait=2m`.
   См. [официальную установку cert-manager](https://cert-manager.io/docs/installation/kubectl/).
3. Для DNS-01 создайте Cloudflare API Token с правами `Zone:DNS:Edit` и
   `Zone:Zone:Read`, ограниченный зоной `nikaeru.com`. Сохраните его в Secret
   `cloudflare-api-token` (ключ `api-token`) в namespace приложения.
   Команды ниже читают token без эха и передают через stdin, не аргументы процесса:

   ```bash
   kubectl --context k3d-duncarbox create namespace duncarbox --dry-run=client -o yaml | \
     kubectl --context k3d-duncarbox apply -f -
   read -rsp 'Cloudflare API token: ' DUNCARBOX_CF_TOKEN
   echo
   export DUNCARBOX_CF_TOKEN
   python3 -c 'import json, os; print(json.dumps({"apiVersion":"v1","kind":"Secret","metadata":{"name":"cloudflare-api-token","namespace":"duncarbox"},"type":"Opaque","stringData":{"api-token":os.environ["DUNCARBOX_CF_TOKEN"]}}))' | \
     kubectl --context k3d-duncarbox apply --server-side -f -
   unset DUNCARBOX_CF_TOKEN
   ```

   Существующий DDNS token подходит только при наличии обоих разрешений.
   Отдельный token позволяет независимо менять и отзывать доступ cert-manager.
   При другом имени Secret задайте `TF_VAR_cloudflare_api_token_secret_name`.
   Этот Secret устанавливается отдельно и не управляется OpenTofu.
   См. [Cloudflare DNS-01](https://cert-manager.io/docs/configuration/acme/dns01/cloudflare/).
4. Выполните сборку образов и обычный `plan/apply` из раздела запуска.
   При обновлении существующей HTTP-установки также нужен новый frontend image
   с обновлённым nginx config. До готовности Certificate браузер может видеть
   стандартный недоверенный сертификат Traefik; успешный `apply` сам по себе
   не означает, что сертификат уже выпущен.

Для пробного выпуска задайте `TF_VAR_acme_staging=true`. Такой сертификат
не доверен браузерами. Для перехода на production снимите эту переменную,
повторите `plan/apply`, затем запросите перевыпуск через
`cmctl --context k3d-duncarbox -n duncarbox renew duncarbox-tls` и дождитесь
завершения нового CertificateRequest. После перехода не ограничивайтесь старым
статусом Ready: проверьте issuer и сроки сертификата, который отдаёт Traefik.
По умолчанию используется production Let’s Encrypt.

### HTTP-01 вместо Cloudflare DNS-01

Задайте `TF_VAR_acme_solver=http01`, если origin доступен по HTTP и из
cert-manager pod, и из Интернета. Cloudflare Secret в этом режиме не нужен.
Порт 80 должен оставаться открытым для продления. Solver создаёт отдельный
маршрут `/.well-known/acme-challenge/` на entrypoint `web` с приоритетом 1000,
без middleware перенаправления. При IPv6-only DNS и IPv4-only pod network
используйте режим DNS-01 по умолчанию.

### Существующий сертификат или локальная проверка

Можно обойтись без cert-manager: задайте `TF_VAR_manage_certificate=false`
до планирования и установите Secret в namespace `duncarbox`:

```bash
kubectl --context k3d-duncarbox create namespace duncarbox --dry-run=client -o yaml | \
  kubectl --context k3d-duncarbox apply -f -
kubectl --context k3d-duncarbox -n duncarbox create secret tls duncarbox-tls \
  --cert=/secure/path/fullchain.pem --key=/secure/path/privkey.pem \
  --dry-run=client -o yaml | kubectl --context k3d-duncarbox apply -f -
```

Сертификат должен содержать `ingress_host` в SAN; `fullchain.pem` — сертификат
и промежуточные CA. Для другого имени Secret задайте `TF_VAR_tls_secret_name`.
Обновление и продление такого сертификата выполняет его владелец.
При переключении с cert-manager используйте новое имя Secret, чтобы исключить
конфликт владения и зависимость от политики удаления старого Certificate.

Для локальной проверки можно создать временный self-signed сертификат вне репозитория:

```bash
tls_dir="$(mktemp -d)"
openssl req -x509 -newkey rsa:2048 -nodes -days 7 \
  -keyout "$tls_dir/privkey.pem" -out "$tls_dir/fullchain.pem" \
  -subj '/CN=app.nikaeru.com' -addext 'subjectAltName=DNS:app.nikaeru.com'
```

Установите его командой выше с путями из `$tls_dir`, затем проверяйте через
`curl --cacert "$tls_dir/fullchain.pem" --resolve app.nikaeru.com:443:127.0.0.1 https://app.nikaeru.com/`.
Не добавляйте приватные ключи в Git или container images.

### Проверка и диагностика

```bash
kubectl --context k3d-duncarbox -n duncarbox get issuer,certificate,certificaterequest
kubectl --context k3d-duncarbox -n duncarbox get orders,challenges
kubectl --context k3d-duncarbox -n duncarbox describe certificate duncarbox-tls
curl --fail --resolve app.nikaeru.com:443:127.0.0.1 https://app.nikaeru.com/api/v1/health
curl -6 --fail https://app.nikaeru.com/
openssl s_client -connect app.nikaeru.com:443 -servername app.nikaeru.com </dev/null 2>/dev/null | \
  openssl x509 -noout -subject -issuer -dates
```

Для Let's Encrypt не используйте `curl -k`: проверка должна подтверждать
доверие к цепочке и соответствие hostname. Запрос по IP без правильного
Host/SNI больше не является проверкой Ingress приложения. Если выпуск завис,
проверьте состояние Challenge и логи cert-manager; для DNS-01 — token,
права на зону и распространение TXT, для HTTP-01 — DNS и доступность TCP/80
как извне, так и из pod.
Перенаправление настроено только на HTTP Ingress приложения, чтобы не мешать
[HTTP-01 solver](https://cert-manager.io/docs/configuration/acme/http01/).
Настройки TLS и middleware соответствуют
[документации Traefik Ingress](https://doc.traefik.io/traefik/reference/routing-configuration/kubernetes/ingress/).

## Обновления и данные

Если `apply` сообщает `a cluster with that name already exists`, проверьте
`tofu -chdir=infra/k3d-infra state list`: работающий кластер должен быть связан
с адресом `k3d_cluster.main`. Наличие контекста в kubeconfig само по себе не
добавляет эту запись в OpenTofu state. Повторный запуск с `-target` также не
восстанавливает утраченную запись.

В таком случае сохраните текущий state и его backup перед восстановлением:
каждая следующая запись state может перезаписать автоматический backup.
У провайдера `agynio/k3d` версии `0.2.3` нет импортера для `k3d_cluster`.
Нужна сохранённая запись этого кластера из предыдущего state; восстановление
сначала проверяется в отдельной копии через `plan`, без пересоздания кластера.
Если потеряны и записи Kubernetes-ресурсов, их можно восстановить через
`tofu import` для `kustomization_resource`. После восстановления обычный
`plan` не должен предлагать создание уже существующих ресурсов.

Образы обновляются независимо:

```bash
make image-backend     # или make image-frontend; make images для обоих
make image-tags
make plan
make apply
```

Makefile сохраняет опубликованные теги в `backend/.tofu/image-tag` и
`frontend/.tofu/image-tag`. Они читаются OpenTofu через отдельные locals и
имеют приоритет над старой общей переменной `image_tag`. Ручной export тегов
не нужен. Непубликовавшийся образ не меняет выбранный тег. После изменения
тегов или конфигурации Makefile отклоняет ранее сохранённый план.
Выходное значение `application_image_tags` содержит карту обоих тегов.
Подробности и миграция старой конфигурации — в [OPERATIONS.md](../OPERATIONS.md).

Kustomize добавляет хеши к именам ConfigMap и Secret и обновляет ссылки
из pod templates при изменении конфигурации.

PVC сохраняет данные при перезапуске pod и обновлении приложения. Это отдельная
база: данные из compose volume `postgres_data` автоматически не переносятся.
`local-path` хранит данные внутри узла k3d; удаление PVC, namespace или кластера
может удалить базу. Перед такими действиями нужна резервная копия PostgreSQL.

Переменные `POSTGRES_*` инициализируют только пустой том. Для смены пароля
существующего пользователя сначала измените его в PostgreSQL, затем обновите
входную переменную и примените конфигурацию.

Значения Secret скрыты в выводе ресурсов плана, но присутствуют в OpenTofu state
и сохранённых планах. Храните их как секреты; `.gitignore` исключает новые state,
plan и локальные `*.auto.tfvars`. Ранее отслеживаемые Git файлы этим правилом
не исключаются.

## Проверка без развёртывания

```bash
kubectl kustomize infra/k3d-infra/.tofu
tofu -chdir=infra/k3d-infra validate
tofu -chdir=infra/k3d-infra plan
```

`kubectl kustomize` проверяет YAML overlay: в его выводе остаются базовые имена
образов, пример hostname `app.example.ru` и ссылки на ещё не созданные Secret. Полный overlay с реквизитами и
образами собирает OpenTofu; применять YAML отдельно через `kubectl apply -k`
не нужно. Порядок ресурсов и скрытие Secret следуют
[документации Kustomization provider](https://github.com/kbst/terraform-provider-kustomization/blob/master/docs/resources/resource.md).
