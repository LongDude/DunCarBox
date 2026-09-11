terraform {
    required_version = ">= 1.8.0"

    required_providers {
      k3d = {
        source = "pvotal-tech/k3d"
        version = "0.0.7"
      }

      kustomization = {
        source = "kbst/kustomization"
        version = "~> 0.9"
      }
    }
}

provider "k3d" {
  
}

provider "kustomization" {
  kuberconfig_path = "~/.kube/config"
}