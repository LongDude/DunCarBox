terraform {
  required_version = ">= 1.8.0"

  required_providers {
    k3d = {
      source  = "registry.terraform.io/agynio/k3d"
      version = "0.2.3"
    }

    kustomization = {
      source  = "kbst/kustomization"
      version = "~> 0.9"
    }
  }
}

provider "k3d" {

}

provider "kustomization" {
  kuberconfig_path = "~/.kube/config"
}
