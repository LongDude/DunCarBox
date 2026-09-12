output "cluster_name" {
  value = k3d_cluster.main.name
}

output "registry_push_address" {
  value = "localhost:${var.registry_host_port}"
}

output "registry_internal_address" {
  value = "${var.registry_name}:5000"
}
