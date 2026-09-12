# The YAML overlay assembles service bases; HCL supplies registry and credentials.
data "kustomization_overlay" "duncarbox" {
  resources = ["${path.module}/.tofu"]
  namespace = "duncarbox"

  images {
    name     = "duncarbox-backend"
    new_name = "${var.registry_name}:5000/duncarbox-backend"
    new_tag  = var.image_tag
  }

  images {
    name     = "duncarbox-frontend"
    new_name = "${var.registry_name}:5000/duncarbox-frontend"
    new_tag  = var.image_tag
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
