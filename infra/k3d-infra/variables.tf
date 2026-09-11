variable "cluster_name" {
  description = "k3d cluster name"
  type        = string
  default     = "duncarbox"
}

variable "registry_name" {
  type        = string
  description = "Name of the project-local container registry"
  default     = "duncarbox-registry"
}

variable "registry_host_port" {
  type        = string
  description = "Registry port exposed on the host"
  default     = "5000"
}

variable "kube_api_port" {
  description = "Kubernetes API port on localhost"
  type        = number
  default     = 6445
}