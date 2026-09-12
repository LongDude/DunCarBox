variable "ingress_host" {
  description = "Public DNS hostname for frontend HTTPS (no scheme or path)"
  type        = string

  validation {
    condition     = length(var.ingress_host) <= 253 && can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$", var.ingress_host))
    error_message = "ingress_host must be a lowercase DNS hostname, such as app.nikaeru.com."
  }
}

variable "proxy_ingress_host" {
  description = "Optional additional hostname accepted by the HTTPS Ingress (for example app-proxy.nikaeru.com)"
  type        = string
  default     = ""

  validation {
    condition     = var.proxy_ingress_host == "" || (length(var.proxy_ingress_host) <= 253 && can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$", var.proxy_ingress_host)))
    error_message = "proxy_ingress_host must be empty or a lowercase DNS hostname."
  }
}

variable "tls_secret_name" {
  description = "TLS Secret in duncarbox; created by cert-manager or supplied separately"
  type        = string
  default     = "duncarbox-tls"

  validation {
    condition     = length(var.tls_secret_name) <= 253 && can(regex("^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$", var.tls_secret_name))
    error_message = "tls_secret_name must be a Kubernetes Secret name."
  }
}

variable "manage_certificate" {
  description = "Create a cert-manager Issuer and Certificate; false uses an existing TLS Secret"
  type        = bool
  default     = true
}

variable "acme_email" {
  description = "Optional contact email for the Let's Encrypt account"
  type        = string
  default     = ""
}

variable "acme_solver" {
  description = "cloudflare uses DNS-01 (also works with an IPv6-only origin); http01 requires origin reachability from cert-manager"
  type        = string
  default     = "cloudflare"

  validation {
    condition     = contains(["cloudflare", "http01"], var.acme_solver)
    error_message = "acme_solver must be cloudflare or http01."
  }
}

variable "cloudflare_api_token_secret_name" {
  description = "Existing Secret in duncarbox with an api-token key for Cloudflare DNS-01"
  type        = string
  default     = "cloudflare-api-token"
}

variable "acme_staging" {
  description = "Use Let's Encrypt staging (certificates are not browser-trusted)"
  type        = bool
  default     = false
}

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
  description = "Legacy fallback until each component has a .tofu/image-tag file; managed by make images"
  type        = string
  default     = "unbuilt"

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
