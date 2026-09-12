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

variable "kubeconfig_path" {
  description = "Path to the kubeconfig containing the k3d cluster context"
  type        = string
  default     = "~/.kube/config"
}

variable "image_tag" {
  description = "Tag of both application images already pushed to the project registry"
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$", var.image_tag))
    error_message = "image_tag must be a valid container image tag. Use a unique tag for each release."
  }
}

variable "postgres_user" {
  description = "PostgreSQL user created on first volume initialization"
  type        = string
  default     = "duncarbox"
}

variable "postgres_database" {
  description = "PostgreSQL database created on first volume initialization"
  type        = string
  default     = "duncarbox"
}

variable "postgres_password" {
  description = "PostgreSQL password; changing it does not update an existing database role"
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.postgres_password) > 0
    error_message = "postgres_password must not be empty."
  }
}
