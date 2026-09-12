# The YAML overlay assembles service bases; HCL supplies registry and credentials.
data "kustomization_overlay" "duncarbox" {
  resources = ["${path.module}/.tofu"]
  namespace = "duncarbox"

  patches {
    target {
      kind = "Ingress"
    }
    patch = jsonencode(concat([
      { op = "replace", path = "/spec/rules/0/host", value = var.ingress_host },
      ], var.proxy_ingress_host == "" ? [] : [
      { op = "add", path = "/spec/rules/-", value = {
        host = var.proxy_ingress_host
        http = {
          paths = [{
            path     = "/"
            pathType = "Prefix"
            backend = {
              service = { name = "frontend", port = { name = "http" } }
            }
          }]
        }
      } },
    ]))
  }

  patches {
    target {
      kind = "Ingress"
      name = "duncarbox"
    }
    patch = jsonencode(concat([
      { op = "replace", path = "/spec/tls/0/hosts/0", value = var.ingress_host },
      { op = "replace", path = "/spec/tls/0/secretName", value = var.tls_secret_name },
      ], var.proxy_ingress_host == "" ? [] : [
      { op = "add", path = "/spec/tls/0/hosts/-", value = var.proxy_ingress_host },
    ]))
  }

  images {
    name     = "duncarbox-backend"
    new_name = "${var.registry_name}:5000/duncarbox-backend"
    new_tag  = local.backend_image_tag
  }

  images {
    name     = "duncarbox-frontend"
    new_name = "${var.registry_name}:5000/duncarbox-frontend"
    new_tag  = local.frontend_image_tag
  }

  secret_generator {
    name = "db-credentials"
    type = "Opaque"
    literals = [
      "POSTGRES_USER=${var.postgres_user}",
      "POSTGRES_DB=${var.postgres_database}",
      "POSTGRES_PASSWORD=${var.postgres_password}",
    ]
  }
}

# Namespace first, then ordinary resources, then resources that depend on them.
# Do not defer the data source until cluster creation: for_each IDs must be known
# during planning. The cluster and kubeconfig must already exist before this plan.
resource "kustomization_resource" "namespace" {
  for_each = data.kustomization_overlay.duncarbox.ids_prio[0]
  manifest = data.kustomization_overlay.duncarbox.manifests[each.value]

  depends_on = [k3d_cluster.main]
}

resource "kustomization_resource" "resources" {
  for_each = data.kustomization_overlay.duncarbox.ids_prio[1]
  manifest = startswith(each.value, "_/Secret/") ? sensitive(data.kustomization_overlay.duncarbox.manifests[each.value]) : data.kustomization_overlay.duncarbox.manifests[each.value]
  wait     = true

  lifecycle {
    precondition {
      condition = alltrue([
        for tag in [local.backend_image_tag, local.frontend_image_tag] :
        tag != "unbuilt" && can(regex("^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$", tag))
      ])
      error_message = "Publish application images first: make images."
    }
  }

  timeouts {
    create = "10m"
    update = "10m"
  }

  depends_on = [kustomization_resource.namespace]
}

resource "kustomization_resource" "dependent_resources" {
  for_each = data.kustomization_overlay.duncarbox.ids_prio[2]
  manifest = data.kustomization_overlay.duncarbox.manifests[each.value]
  wait     = true

  timeouts {
    create = "10m"
    update = "10m"
  }

  depends_on = [kustomization_resource.resources]
}
