#!/usr/bin/env python3
"""Makefile operations. Uses only Python's standard library and existing CLIs."""
from __future__ import annotations

import fcntl
import getpass
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra/k3d-infra"
PLAN = INFRA / "deploy.tfplan"
PLAN_META = INFRA / "deploy.tfplan.meta.json"
LOCAL_CONFIG = INFRA / "zz-operations.auto.tfvars.json"
COMPONENTS = ("backend", "frontend")
TAG_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")


class TLSCertificateError(RuntimeError):
    """The endpoint certificate is not yet valid for the requested hostname."""


class CloudflareEdgeCertificateError(TLSCertificateError):
    """Cloudflare closed TLS before presenting an edge certificate."""


def run(*args, capture=False, input=None, check=True, quiet=False, env=None):
    args = [str(arg) for arg in args]
    if not quiet:
        print("+ " + shlex.join(args), flush=True)
    result = subprocess.run(args, cwd=ROOT, text=True, input=input,
                            capture_output=capture, check=False, env=env)
    if check and result.returncode:
        if capture:
            print(result.stderr, file=sys.stderr, end="")
        raise RuntimeError(f"Команда завершилась с кодом {result.returncode}: {args[0]}")
    return result


def tofu(*args, **kwargs):
    return run("tofu", f"-chdir={INFRA}", *args, **kwargs)


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def update_local_config(values):
    current = json.loads(LOCAL_CONFIG.read_text()) if LOCAL_CONFIG.exists() else {}
    current.update(values)
    atomic_write(LOCAL_CONFIG, json.dumps(current, indent=2) + "\n")


def console(expression, inspect_only=True):
    # Config inspection never needs a database credential and never prints it.
    args = ["console", "-no-color"]
    if inspect_only:
        args.append("-var=postgres_password=inspection-only")
    result = tofu(*args, input=f"jsonencode({expression})\n", capture=True,
                  quiet=True, check=False, env={**os.environ, "TF_INPUT": "0"})
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    if result.stdout.strip() == "(known after apply)":
        raise RuntimeError("OpenTofu: missing input value (known after apply)")
    return json.loads(json.loads(result.stdout.strip()))


def settings():
    names = ("cluster_name", "kubeconfig_path", "registry_host_port", "registry_name",
             "ingress_host", "tls_secret_name", "manage_certificate", "acme_solver",
             "cloudflare_api_token_secret_name")
    expression = "{" + ",".join(f"{name}=var.{name}" for name in names)
    expression += ",tags={backend=local.backend_image_tag,frontend=local.frontend_image_tag}}"
    return console(expression)


def kube(config, *args, **kwargs):
    return run("kubectl", "--kubeconfig", str(Path(config["kubeconfig_path"]).expanduser()),
               "--context", "k3d-" + config["cluster_name"], *args, **kwargs)


def configure():
    tofu("init", "-input=false")
    try:
        if console('nonsensitive(var.postgres_password != "")', inspect_only=False):
            print("Пароль PostgreSQL уже задан; текущие реквизиты сохранены.")
            return
    except RuntimeError as error:
        if not any(message in str(error) for message in
                   ("No value for required variable", "missing input value")):
            raise
    if not sys.stdin.isatty():
        raise RuntimeError("Задайте postgres_password в локальном *.auto.tfvars или выполните make configure в терминале.")
    password = getpass.getpass("Пароль PostgreSQL (для существующей БД — текущий): ")
    if not password:
        raise RuntimeError("Пароль не может быть пустым")
    if password != getpass.getpass("Повторите пароль: "):
        raise RuntimeError("Пароли не совпадают")
    update_local_config({"postgres_password": password})
    print(f"Реквизиты сохранены в {LOCAL_CONFIG.relative_to(ROOT)} (0600, вне Git).")


def tag_path(component):
    return ROOT / component / ".tofu/image-tag"


def built_path(component):
    return ROOT / component / ".tofu/image-built.json"


def valid_tag(tag):
    if tag == "unbuilt" or not TAG_PATTERN.fullmatch(tag):
        raise RuntimeError(f"Некорректный или отсутствующий тег: {tag!r}; выполните make images")
    return tag


def new_tag():
    commit = run("git", "rev-parse", "--short", "HEAD", capture=True, quiet=True).stdout.strip()
    return f"{commit}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid4().hex[:8]}"


def build_image(component, config):
    tag = new_tag()
    image = f"localhost:{config['registry_host_port']}/duncarbox-{component}:{tag}"
    run("docker", "build", "-f", f"{component}/Dockerfile", "-t", image, ".")
    image_id = run("docker", "image", "inspect", "--format", "{{.Id}}", image,
                   capture=True, quiet=True).stdout.strip()
    atomic_write(built_path(component), json.dumps({"tag": tag, "image": image, "id": image_id}) + "\n")
    print(f"Собран {image}; опубликованный тег пока не изменён.")


def push_image(component, config):
    path = built_path(component)
    if not path.exists():
        raise RuntimeError(f"Сначала выполните make image-build-{component}")
    built = json.loads(path.read_text())
    valid_tag(built["tag"])
    expected = f"localhost:{config['registry_host_port']}/duncarbox-{component}:{built['tag']}"
    if built["image"] != expected:
        raise RuntimeError("Адрес registry изменился после сборки; пересоберите образ.")
    image_id = run("docker", "image", "inspect", "--format", "{{.Id}}", expected,
                   capture=True, quiet=True).stdout.strip()
    if image_id != built["id"]:
        raise RuntimeError("Образ под тегом изменился после сборки; создайте новую сборку.")
    run("docker", "push", expected)
    # This is the commit point. A failed build/push must not select a new release.
    atomic_write(tag_path(component), built["tag"] + "\n")
    print(f"Опубликован {component}: {built['tag']}. Применение: make deploy")


def images(components=COMPONENTS):
    config = settings()
    for component in components:
        build_image(component, config)
        push_image(component, config)


def fingerprint():
    paths = set(INFRA.glob("*.tf")) | set(INFRA.glob("*.tfvars")) | set(INFRA.glob("*.tfvars.json"))
    for directory in [INFRA / ".tofu", ROOT / "backend/.tofu", ROOT / "frontend/.tofu", ROOT / "infra/postgres/.tofu"]:
        paths.update(directory.glob("*.yaml"))
    paths.update(tag_path(component) for component in COMPONENTS)
    result = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(paths) if path.exists()}
    result.update({"env:" + name: hashlib.sha256(value.encode()).hexdigest()
                   for name, value in os.environ.items() if name.startswith("TF_VAR_")})
    return result


def plan():
    config = settings()
    for tag in config["tags"].values():
        valid_tag(tag)
    PLAN_META.unlink(missing_ok=True)
    tofu("validate", "-no-color")
    tofu("plan", "-input=false", f"-out={PLAN}")
    # Include the actual plan hash, so a manually replaced plan is never mistaken
    # for the plan reviewed by this command.
    atomic_write(PLAN_META, json.dumps({"tags": config["tags"], "files": fingerprint(),
                 "plan_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest()}) + "\n")


def apply():
    if not PLAN.exists() or not PLAN_META.exists():
        raise RuntimeError("Нет проверенного плана; выполните make plan или make deploy.")
    metadata = json.loads(PLAN_META.read_text())
    config = settings()
    if (metadata["tags"] != config["tags"] or metadata["files"] != fingerprint()
            or metadata["plan_sha256"] != hashlib.sha256(PLAN.read_bytes()).hexdigest()):
        raise RuntimeError("Образы, конфигурация или план изменились: выполните make plan заново.")
    tofu("apply", "-input=false", PLAN)
    PLAN.unlink()
    PLAN_META.unlink()
    for component in COMPONENTS:
        kube(config, "-n", "duncarbox", "rollout", "status", f"deployment/{component}", "--timeout=180s")


def deploy():
    plan()
    apply()


def namespace(config):
    data = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "duncarbox"}}
    kube(config, "apply", "--server-side", "-f", "-", input=json.dumps(data))


def ssl_install(config):
    existing = kube(config, "-n", "cert-manager", "get", "deployment", "cert-manager",
                    "--ignore-not-found", "-o", "name", capture=True)
    if not existing.stdout.strip():
        version = os.environ.get("CERT_MANAGER_VERSION", "v1.21.2")
        if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
            raise RuntimeError("Некорректный CERT_MANAGER_VERSION")
        kube(config, "apply", "-f", f"https://github.com/cert-manager/cert-manager/releases/download/{version}/cert-manager.yaml")
    for component in ("cert-manager", "cert-manager-cainjector", "cert-manager-webhook"):
        kube(config, "-n", "cert-manager", "rollout", "status", f"deployment/{component}", "--timeout=180s")
    kube(config, "wait", "--for=condition=Established", "crd/certificates.cert-manager.io", "--timeout=120s")
    # Readiness of the Deployment alone does not prove the admission webhook works.
    probe = {"apiVersion": "cert-manager.io/v1", "kind": "Issuer", "metadata": {
        "name": "operations-webhook-check", "namespace": "default"}, "spec": {"selfSigned": {}}}
    kube(config, "apply", "--dry-run=server", "-f", "-", input=json.dumps(probe))


def ssl_token(config, only_if_missing=False):
    namespace(config)
    name = config["cloudflare_api_token_secret_name"]
    if only_if_missing:
        existing = kube(config, "-n", "duncarbox", "get", "secret", name, "--ignore-not-found",
                        "-o", "name", capture=True)
        if existing.stdout.strip():
            return
    path = os.environ.get("CF_TOKEN_FILE", "")
    if path:
        token = Path(path).expanduser().read_text().strip()
    elif sys.stdin.isatty():
        token = getpass.getpass("Cloudflare token (Zone:DNS:Edit + Zone:Zone:Read): ").strip()
    else:
        raise RuntimeError("Укажите CF_TOKEN_FILE или выполните make ssl-token в терминале.")
    if not token:
        raise RuntimeError("Пустой Cloudflare token")
    data = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": "duncarbox"},
            "type": "Opaque", "stringData": {"api-token": token}}
    kube(config, "apply", "--server-side", "-f", "-", input=json.dumps(data))


def ssl_prepare(config):
    if config["manage_certificate"]:
        ssl_install(config)
        if config["acme_solver"] == "cloudflare":
            ssl_token(config, only_if_missing=True)


def ssl_check(config):
    if config["manage_certificate"]:
        kube(config, "-n", "duncarbox", "wait", "--for=condition=Ready",
             "certificate/duncarbox-tls", "--timeout=10m")
    # Certificate Ready describes the Secret. Traefik consumes its update
    # asynchronously and may briefly still serve its previous/default certificate.
    for attempt in range(10):
        try:
            check_http(config["ingress_host"], "/api/v1/health", origin=True, health=True)
            return
        except TLSCertificateError as error:
            if attempt == 9:
                raise TLSCertificateError(
                    "Origin продолжает отдавать недоверенный сертификат или сертификат "
                    "для другого имени. Проверьте Ingress spec.tls.secretName и логи Traefik.\n"
                    + str(error)
                ) from error
            print(f"Ожидаю загрузки сертификата в Traefik ({attempt + 1}/10)...", flush=True)
            time.sleep(2)


def ssl_import(config):
    cert, key = os.environ.get("TLS_CERT"), os.environ.get("TLS_KEY")
    if not cert or not key:
        raise RuntimeError("Используйте make ssl-import TLS_CERT=/path/fullchain.pem TLS_KEY=/path/key.pem")
    for path in (cert, key):
        if not Path(path).is_file():
            raise RuntimeError(f"Файл не найден: {path}")
    run("openssl", "x509", "-in", cert, "-noout", "-checkhost", config["ingress_host"])
    run("openssl", "x509", "-in", cert, "-noout", "-checkend", "0")
    # A distinct name avoids ownership conflicts with cert-manager's Secret.
    name = config["tls_secret_name"] + "-manual" if config["manage_certificate"] else config["tls_secret_name"]
    namespace(config)
    secret = kube(config, "-n", "duncarbox", "create", "secret", "tls", name,
                  f"--cert={cert}", f"--key={key}", "--dry-run=client", "-o", "json", capture=True).stdout
    kube(config, "apply", "--server-side", "-f", "-", input=secret)
    update_local_config({"manage_certificate": False, "tls_secret_name": name})
    deploy()
    ssl_check(settings())


def ddns_module():
    name = "operations_ddns"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "infra/ddns-client/ipv6-prefix-ddns.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def ddns_config():
    path = Path(os.environ.get("DDNS_CONFIG", "infra/ddns-client/config.conf")).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return ddns_module().load_config(str(path))


def desired_records(config):
    module = ddns_module()
    network, _ = module.detect_prefix(config)
    return module.build_records(config, network)


def dns_addresses(hostname, record_type):
    server = os.environ.get("DNS_SERVER", "1.1.1.1")
    result = run("dig", "@" + server, "+time=3", "+tries=1", "+short", hostname, record_type,
                 capture=True, quiet=True)
    addresses = set()
    for line in result.stdout.splitlines():
        try:
            address = ipaddress.ip_address(line.strip())
        except ValueError:
            continue  # CNAME line
        if address.version == (6 if record_type == "AAAA" else 4):
            addresses.add(str(address))
    return addresses


def check_dns():
    module, config = ddns_module(), ddns_config()
    errors = []
    for record in desired_records(config):
        host = record["hostname"]
        try:
            existing = module.get_dns_record(config, host)
            if not existing or ipaddress.IPv6Address(existing["content"]) != ipaddress.IPv6Address(record["address"]) or bool(existing.get("proxied")) != record["proxied"]:
                raise RuntimeError("Cloudflare AAAA/content/proxied не совпадают с конфигурацией")
            public = dns_addresses(host, "AAAA")
            if record["proxied"]:
                if not public or record["address"] in public:
                    raise RuntimeError("Публичный AAAA не показывает адреса proxy")
            elif public != {record["address"]}:
                raise RuntimeError(f"Публичный AAAA {sorted(public)} != {record['address']}")
            print(f"OK DNS {host}: {', '.join(sorted(public))}, proxied={record['proxied']}")
        except (RuntimeError, OSError, ValueError) as error:
            errors.append(f"{host}: {error}")
    if errors:
        raise RuntimeError("\n".join(errors))


def check_ipv6():
    run("systemctl", "is-active", "ipv6-prefix-ddns.service")
    config = ddns_config()
    records = desired_records(config)
    addresses = {str(item["address"]) for item in ddns_module().get_global_addresses(config.interface)}
    errors = []
    for address in sorted({record["address"] for record in records}):
        if address not in addresses:
            errors.append(f"На {config.interface} отсутствует {address}")
    if config.direct_routing:
        rules = json.loads(run("ip", "-N", "-j", "-6", "rule", "show", capture=True).stdout)
        sources = sorted({r["address"] for r in records if r["suffix"] in ("10", "20")})
        for index, address in enumerate(sources):
            expected = ipaddress.IPv6Network(address + "/128")
            if not any(str(rule.get("table")) == "106" and str(rule.get("protocol")) == "242"
                       and int(rule["priority"]) == 100 + index
                       and ipaddress.IPv6Network(rule.get("src", "::/0")) == expected for rule in rules):
                errors.append(f"Отсутствует policy rule для {address}")
            route = json.loads(run("ip", "-j", "-6", "route", "get", "2606:4700:4700::1111",
                                   "from", address, capture=True).stdout)[0]
            if route.get("dev") != config.interface or str(route.get("table")) != "106":
                errors.append(f"Неверный маршрут для {address}: {route.get('dev')}, table={route.get('table')}")
            print(f"IPv6 {address} -> {route.get('dev')}, table={route.get('table')}")
    if config.firewall_hook:
        saved = run("sudo", "ip6tables-save", "-c", capture=True).stdout
        print(saved)
        # Verify the required jumps/allow; the full dump also exposes earlier UFW denies.
        rules = [re.sub(r"^\[\d+:\d+\] ", "", line) for line in saved.splitlines()]
        required = [f"-A INPUT -i {config.interface} -j IPV6-DDNS-HOST",
                    "-A ufw6-user-input -j IPV6-DDNS-ALLOW"]
        for rule in required:
            if rules.count(rule) != 1:
                errors.append(f"Ожидался один переход: {rule}")
        guards = [f"-A {parent} -i {config.interface} -j IPV6-DDNS-DOCKER"
                  for parent in ("FORWARD", "DOCKER-USER")]
        if sum(rules.count(rule) for rule in guards) != 1:
            errors.append("Ожидался один переход в IPV6-DDNS-DOCKER")
        app = next((r["address"] for r in records if r["suffix"] == "10"), None)
        if not app or not any(line.startswith("-A IPV6-DDNS-ALLOW ") and f"-d {app}/128 " in line
                              and f"-i {config.interface} " in line and "--dports 80,443 " in line
                              and line.endswith("-j ACCEPT") for line in rules):
            errors.append("Отсутствует разрешение HTTP/HTTPS для APP IPv6")
    else:
        print("FIREWALL_HOOK выключен; управляемые firewall-правила не ожидаются.")
    print("SSH: подключение к порту 42 пропущено. Проверка локальных правил не заменяет внешний запрос.")
    if errors:
        raise RuntimeError("\n".join(errors))


def check_http(host, path="/", *, origin=False, proxy=False, health=False):
    with tempfile.TemporaryDirectory(prefix="duncarbox-http-") as directory:
        headers, body = Path(directory) / "headers", Path(directory) / "body"
        args = ["curl", "--noproxy", "*", "--connect-timeout", "5", "--max-time", "20",
                "--silent", "--show-error", "--dump-header", headers, "--output", body,
                "--write-out", "%{http_code}"]
        if origin:
            address = str(ipaddress.ip_address(os.environ.get("ORIGIN_IP", "127.0.0.1")))
            if ":" in address:
                address = f"[{address}]"
            args += ["--resolve", f"{host}:443:{address}"]
        result = run(*args, f"https://{host}{path}", capture=True, check=False)
        header_text = headers.read_text() if headers.exists() else ""
        print(f"{host}{path}: HTTP {result.stdout.strip() or '000'}")
        for line in header_text.splitlines():
            if line.lower().startswith(("http/", "server:", "cf-ray:", "cf-cache-status:", "location:")):
                print("  " + line)
        if result.returncode:
            if proxy and result.returncode == 35:
                raise CloudflareEdgeCertificateError(
                    "Cloudflare не выдал edge-сертификат для этого имени и разорвал TLS. "
                    "Для глубокого имени включите Total TLS/Advanced Certificate Manager "
                    "или используйте имя первого уровня (например, app-proxy.<zone>)."
                )
            error_type = TLSCertificateError if result.returncode == 60 else RuntimeError
            raise error_type(result.stderr.strip())
        if result.stdout.strip() != "200":
            detail = body.read_text(errors="replace")[:500] if body.exists() else ""
            raise RuntimeError(f"Ожидался HTTP 200: {detail}")
        if proxy and not re.search(r"^cf-ray:", header_text, re.I | re.M):
            raise RuntimeError("Нет CF-Ray: ответ не подтверждает прохождение через Cloudflare")
        if health or path.startswith("/api/"):
            try:
                data = json.loads(body.read_text())
            except ValueError as error:
                raise RuntimeError("API endpoint вернул не JSON") from error
            if health and (not isinstance(data, dict) or data.get("status") != "ok"):
                raise RuntimeError(f"API не готов: {data}")
        elif path == "/" and "<html" not in body.read_text(errors="replace").lower():
            raise RuntimeError("Вместо страницы frontend получен неожиданный ответ")


def check_service(config, origin=False, proxy=False):
    host = config["ingress_host"]
    if proxy:
        first, _, zone = host.partition(".")
        host = os.environ.get("PROXY_HOST") or f"{first}-proxy.{zone}"
        if not (dns_addresses(host, "AAAA") or dns_addresses(host, "A")):
            raise RuntimeError(f"Нет публичных DNS-адресов для {host}")
    try:
        check_http(host, origin=origin, proxy=proxy)
        check_http(host, "/api/v1/health", origin=origin, proxy=proxy, health=True)
        check_http(host, "/api/v1/boxes", origin=origin, proxy=proxy)
    except CloudflareEdgeCertificateError:
        if proxy:
            print(
                "\nCloudflare DNS proxy работает, но HTTPS для этого hostname не настроен. "
                "Origin и DDNS исправны; настройте сертификат Cloudflare или задайте "
                "PROXY_HOST=app-proxy.<zone> для имени первого уровня.",
                file=sys.stderr,
            )
        raise


def help_text():
    for line in (ROOT / "Makefile").read_text().splitlines():
        if ": ## " in line:
            target, description = line.split(": ## ", 1)
            print(f"{target:48} {description}")
    print("\nПервый запуск: make init\nОбновление frontend: make image-frontend && make deploy\n"
          "DDNS: make ddns-install && make check-ipv6 && make check-dns\n"
          "Диагностика: make check (SSH пропущен)")


def main(command):
    if command == "help":
        help_text()
    elif command == "configure":
        configure()
    elif command in ("cluster-init", "init"):
        configure()
        tofu("apply", "-target=k3d_cluster.main")
        if command == "init":
            images()
            config = settings()
            ssl_prepare(config)
            deploy()
            ssl_check(config)
            print("Основной стек запущен. DDNS: make ddns-install; диагностика: make check")
    elif command == "images":
        images()
    elif command in ("image-backend", "image-frontend"):
        images((command.removeprefix("image-"),))
    elif command.startswith("image-build-") or command.startswith("image-push-"):
        component = command.split("-")[-1]
        if component not in COMPONENTS:
            raise RuntimeError("Неизвестный компонент")
        (build_image if "-build-" in command else push_image)(component, settings())
    elif command == "image-tags":
        print(json.dumps(settings()["tags"], indent=2))
        for component in COMPONENTS:
            if built_path(component).exists():
                print(f"Последняя сборка {component}: {json.loads(built_path(component).read_text())['tag']}")
    elif command in ("plan", "apply", "deploy"):
        {"plan": plan, "apply": apply, "deploy": deploy}[command]()
    elif command == "status":
        config = settings()
        kube(config, "-n", "duncarbox", "get", "pods,svc,ingress,pvc")
        kube(config, "-n", "duncarbox", "get", "deployments", "-o",
             "custom-columns=NAME:.metadata.name,IMAGE:.spec.template.spec.containers[*].image")
    elif command.startswith("ssl-"):
        config = settings()
        if command == "ssl-install":
            ssl_install(config)
        elif command == "ssl-token":
            ssl_token(config)
        elif command == "ssl-issue":
            if not config["manage_certificate"]:
                raise RuntimeError("Для выпуска через cert-manager задайте manage_certificate=true в локальном tfvars.")
            ssl_prepare(config)
            deploy()
            ssl_check(config)
        elif command == "ssl-import":
            ssl_import(config)
        elif command == "ssl-check":
            ssl_check(config)
        else:
            raise RuntimeError("Неизвестная SSL-команда")
    elif command == "ddns-install":
        config = ddns_config()  # Validate before any privileged install.
        run("bash", ROOT / "infra/ddns-client/install.sh", config.config_path)
    elif command == "ddns-logs":
        run("sudo", "journalctl", "-u", "ipv6-prefix-ddns.service", "-n", "100", "--no-pager")
    elif command in {"ddns-" + action for action in ("start", "stop", "restart", "enable", "disable", "status")}:
        run("sudo", "systemctl", command.removeprefix("ddns-"), "ipv6-prefix-ddns.service")
    elif command == "check-ipv6":
        check_ipv6()
    elif command == "check-dns":
        check_dns()
    elif command in ("check-local", "check-service", "check-proxy"):
        check_service(settings(), origin=command == "check-local", proxy=command == "check-proxy")
    elif command == "check":
        errors = []
        for name in ("status", "check-ipv6", "check-dns", "check-local", "check-service", "check-proxy"):
            print(f"\n=== {name} ===", flush=True)
            try:
                main(name)
            except (RuntimeError, OSError, ValueError) as error:
                errors.append(f"{name}: {error}")
        if errors:
            raise RuntimeError("\n".join(errors))
    else:
        raise RuntimeError(f"Неизвестная команда: {command}")


if __name__ == "__main__":
    os.chdir(ROOT)
    os.umask(0o077)
    try:
        # Serialize separate make processes as well as `make -j` to protect
        # publication metadata and the saved plan from concurrent replacement.
        with (ROOT / ".operations.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            main(sys.argv[1] if len(sys.argv) > 1 else "help")
    except (RuntimeError, OSError, ValueError, KeyboardInterrupt) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
