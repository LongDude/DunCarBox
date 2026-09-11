resource "k3d_cluster" "main" {
  name = var.cluster_name

  servers = 1
  agents  = 2

  #
  # Kubernetes API
  #
  kube_api {
    host_ip   = "127.0.0.1"
    host_port = var.kube_api_port
  }

  #
  # HTTP -> k3d loadbalancer
  #
  port {
    host          = "0.0.0.0"
    host_port      = 80
    container_port = 80

    node_filters = [
      "loadbalancer"
    ]
  }

  #
  # HTTPS -> k3d loadbalancer
  #
  port {
    host          = "0.0.0.0"
    host_port      = 443
    container_port = 443

    node_filters = [
      "loadbalancer"
    ]
  }

  registries {
    create = {
      name      = var.registry_name
      host      = "${var.registry_name}.local"
      host_port = var.registry_host_port
    }
  }

  k3d {
    disable_load_balancer = false
    disable_image_volume  = false
  }

  kubeconfig {
    update_default_kubeconfig = true
    switch_current_context    = true
  }
}