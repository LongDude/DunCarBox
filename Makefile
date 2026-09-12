.DEFAULT_GOAL := help
.NOTPARALLEL:

PYTHON ?= python3
export DDNS_CONFIG ?= infra/ddns-client/config.conf
export TLS_CERT ?=
export TLS_KEY ?=
export CF_TOKEN_FILE ?=
export PROXY_HOST ?=
export ORIGIN_IP ?= 127.0.0.1
export DNS_SERVER ?= 1.1.1.1
export CERT_MANAGER_VERSION ?= v1.21.2

OPS = $(PYTHON) infra/scripts/operations.py

.PHONY: help configure init cluster-init images image-backend image-frontend \
 image-build-backend image-build-frontend image-push-backend image-push-frontend \
 image-tags plan apply deploy status ssl-install ssl-token ssl-issue ssl-import ssl-check \
 ddns-install ddns-start ddns-stop ddns-restart ddns-enable ddns-disable ddns-status ddns-logs \
 check-ipv6 check-dns check-local check-service check-proxy check test-ops test-ddns

help: ## Список команд и основных сценариев
	@$(OPS) help
configure: ## Настроить локальный пароль PostgreSQL, если он ещё не задан
	@$(OPS) configure
init: ## Первый запуск: кластер, образы, cert-manager, сертификат и приложение
	@$(OPS) init
cluster-init: ## Инициализировать провайдеры и создать только кластер/registry
	@$(OPS) cluster-init
images: ## Собрать и опубликовать оба образа, сохранить независимые теги
	@$(OPS) images
image-backend image-frontend: ## Собрать и опубликовать один компонент
	@$(OPS) $@
image-build-backend image-build-frontend: ## Только сборка; опубликованный тег не меняется
	@$(OPS) $@
image-push-backend image-push-frontend: ## Опубликовать последнюю сборку и сохранить тег
	@$(OPS) $@
image-tags: ## Показать сохранённые теги и ещё не опубликованные сборки
	@$(OPS) image-tags
plan: ## Создать план с сохранёнными тегами
	@$(OPS) plan
apply: ## Применить сохранённый план, проверив, что теги не изменились
	@$(OPS) apply
deploy: ## Создать и применить новый план, дождаться rollout
	@$(OPS) deploy
status: ## Состояние pod, Service, Ingress и текущие image
	@$(OPS) status
ssl-install: ## Установить cert-manager, дождаться готовности
	@$(OPS) ssl-install
ssl-token: ## Установить Cloudflare token из CF_TOKEN_FILE или скрытого ввода
	@$(OPS) ssl-token
ssl-issue: ## Подготовить cert-manager/token, применить конфигурацию и дождаться сертификата
	@$(OPS) ssl-issue
ssl-import: ## Установить свой сертификат: TLS_CERT=... TLS_KEY=...
	@$(OPS) ssl-import
ssl-check: ## Проверить Certificate и доверенный HTTPS сертификат origin
	@$(OPS) ssl-check
ddns-install: ## Установить DDNS из DDNS_CONFIG и включить службу
	@$(OPS) ddns-install
ddns-start ddns-stop ddns-restart ddns-enable ddns-disable ddns-status ddns-logs: ## Управление DDNS-службой
	@$(OPS) $@
check-ipv6: ## Адреса, policy routing и правила IPv6 firewall; без подключения SSH
	@$(OPS) check-ipv6
check-dns: ## Сравнить Cloudflare и публичный DNS с текущим IPv6-префиксом
	@$(OPS) check-dns
check-local: ## Проверить HTTPS origin через ORIGIN_IP с правильным Host/SNI
	@$(OPS) check-local
check-service: ## Проверить публичный HTTPS и API через DNS
	@$(OPS) check-service
check-proxy: ## Проверить Cloudflare app-proxy: DNS, HTTPS, заголовки, API
	@$(OPS) check-proxy
check: ## Все проверки после запуска, включая Cloudflare Proxy
	@$(OPS) check
test-ops: ## Регрессионные тесты Makefile-операций без изменений кластера
	@$(PYTHON) -m unittest discover -s infra/scripts/tests -v
test-ddns: ## Тесты DDNS; сетевые тесты требуют отдельного namespace
	@$(PYTHON) -m unittest discover -s infra/ddns-client/tests -v
