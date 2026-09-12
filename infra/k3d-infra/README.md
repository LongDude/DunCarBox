# DunCarBox в k3d через OpenTofu

Docker Compose используется для разработки. Серверная конфигурация собирается
Kustomize и применяется OpenTofu в namespace `duncarbox`.

## Структура

- `cluster.tf` — существующий k3d-кластер и встроенный registry.
- `.tofu/` — overlay для k3d: namespace, Ingress и StorageClass `local-path`.
- `../../backend/.tofu/` — Deployment, Service и ConfigMap backend.
- `../../frontend/.tofu/` — Deployment и Service nginx с собранным frontend.
- `../postgres/.tofu/` — StatefulSet PostgreSQL 17, Service `db` и PVC на 10 GiB.
- `kustomization.tf` — HCL overlay: адреса образов, тег релиза, Secret с реквизитами
  БД и применение ресурсов в порядке `ids_prio` провайдера.

Маршрут запросов: порт 80 сервера → Traefik → `frontend:80` → nginx →
`backend:8000` для `/api/`. Backend подключается к `db:5432`. Сервисы используют
ClusterIP; отдельные порты backend и PostgreSQL на хосте не публикуются.
Ingress принимает любой HTTP Host. Домен можно указать в `.tofu/ingress.yaml`;
TLS и сертификаты в этой конфигурации не настроены.

## Запуск

Нужны Docker Engine, OpenTofu >= 1.8 и kubectl. При запуске с нуля сначала
создайте кластер и registry отдельным шагом ниже, затем загрузите образы и
примените приложение. k3d также устанавливает Traefik и StorageClass `local-path`.
Имя контекста вычисляется из `cluster_name`; путь к kubeconfig задаётся через
`kubeconfig_path` (по умолчанию `~/.kube/config`).

Все команды ниже выполняются из корня репозитория в Bash.

1. Инициализируйте провайдеры и задайте уникальный тег релиза. Пароль передаётся
   через окружение, без записи в отслеживаемые файлы:

   ```bash
   tofu -chdir=infra/k3d-infra init
   export TF_VAR_image_tag="$(git rev-parse --short HEAD)-$(date -u +%Y%m%d%H%M%S)"
   read -rsp 'PostgreSQL password: ' TF_VAR_postgres_password
   echo
   export TF_VAR_postgres_password
   ```

   Для автоматизации передавайте `TF_VAR_postgres_password` из хранилища секретов
   CI. `postgres_user` и `postgres_database` по умолчанию равны `duncarbox`.

2. **При запуске с нуля создайте кластер до общего `plan` или `apply`:**

   ```bash
   tofu -chdir=infra/k3d-infra apply -target=k3d_cluster.main
   kubectl --context k3d-duncarbox get nodes
   ```

   Если кластер и контекст уже существуют, пропустите этот шаг. При другом
   `cluster_name` замените имя контекста в команде kubectl.

   Провайдер Kustomization читает kubeconfig на этапе планирования. Поэтому
   общий `tofu apply` в пустом окружении завершается ошибкой
   `context "k3d-duncarbox" does not exist`: кластер ещё не создан.
   `depends_on` у namespace задаёт порядок создания ресурсов, но не откладывает
   настройку провайдера. Начальный запуск с `-target` включает только кластер
   и позволяет создать kubeconfig до планирования Kubernetes-ресурсов.
   Предупреждение OpenTofu о resource targeting ожидаемо; дальнейшие шаги
   выполняются без `-target`.

3. Соберите оба образа существующими Dockerfile и отправьте их в registry:

   ```bash
   registry_push="$(tofu -chdir=infra/k3d-infra output -raw registry_push_address)"
   docker build -f backend/Dockerfile -t "$registry_push/duncarbox-backend:$TF_VAR_image_tag" .
   docker build -f frontend/Dockerfile -t "$registry_push/duncarbox-frontend:$TF_VAR_image_tag" .
   docker push "$registry_push/duncarbox-backend:$TF_VAR_image_tag"
   docker push "$registry_push/duncarbox-frontend:$TF_VAR_image_tag"
   ```

   Хост отправляет образы через `localhost:<registry_host_port>`. Kubernetes
   загружает их через `<registry_name>:5000`; overlay подставляет этот адрес
   автоматически. Провайдер создаёт registry с именем из `registries.create.name`
   без префикса `k3d-`. Это имя также используется в HTTP mirror в
   `/etc/rancher/k3s/registries.yaml` узлов кластера.

4. Проверьте и примените план:

   ```bash
   tofu -chdir=infra/k3d-infra validate
   tofu -chdir=infra/k3d-infra plan -out=deploy.tfplan
   tofu -chdir=infra/k3d-infra apply deploy.tfplan
   rm infra/k3d-infra/deploy.tfplan
   unset TF_VAR_postgres_password
   ```

   OpenTofu сначала создаёт namespace, затем остальные ресурсы, ожидая
   готовности Deployment и StatefulSet до 10 минут. Backend ждёт PostgreSQL через init container
   перед инициализацией каталога. Проверки готовности используют существующие
   HTTP endpoints приложения и `pg_isready` для БД.

5. Проверьте результат (если `cluster_name` изменён, замените имя контекста):

   ```bash
   kubectl --context k3d-duncarbox -n duncarbox get pods,svc,ingress,pvc
   curl --fail http://127.0.0.1/api/v1/health
   curl --fail http://127.0.0.1/api/v1/boxes
   ```

   Интерфейс доступен по `http://<адрес-сервера>/`.

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

При обновлении соберите и отправьте оба образа с новым `image_tag`, затем
повторите `plan` и `apply` с прежним паролем БД. Новый тег запускает обновление
Deployment. Kustomize добавляет хеши к именам ConfigMap и Secret и обновляет
ссылки из pod templates при изменении конфигурации.

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
образов и ссылки на ещё не созданный Secret. Полный overlay с реквизитами и
образами собирает OpenTofu; применять YAML отдельно через `kubectl apply -k`
не нужно. Порядок ресурсов и скрытие Secret следуют
[документации Kustomization provider](https://github.com/kbst/terraform-provider-kustomization/blob/master/docs/resources/resource.md).
