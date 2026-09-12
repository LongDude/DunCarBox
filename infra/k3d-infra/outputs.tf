output "cluster_name" {
  value = k3d_cluster.main.name
}

output "frontend_url" {
  value = "https://${var.ingress_host}"
}

output "registry_push_address" {
  value = "localhost:${var.registry_host_port}"
}

output "registry_internal_address" {
  value = "${var.registry_name}:5000"
}

output "application_image_tags" {
  description = "Independently published image tags selected for this deployment"
  value = {
    backend  = local.backend_image_tag
    frontend = local.frontend_image_tag
  }
}
