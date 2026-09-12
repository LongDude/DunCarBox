# Install cert-manager and its CRDs before applying these resources (see README).
# Private keys and certificates are generated in Kubernetes, never in Tofu state.
resource "kustomization_resource" "acme_issuer" {
  count = var.manage_certificate ? 1 : 0
  manifest = jsonencode({
    apiVersion = "cert-manager.io/v1"
    kind       = "Issuer"
    metadata = {
      name      = "duncarbox-letsencrypt"
      namespace = "duncarbox"
    }
    spec = {
      acme = merge({
        server = var.acme_staging ? "https://acme-staging-v02.api.letsencrypt.org/directory" : "https://acme-v02.api.letsencrypt.org/directory"
        privateKeySecretRef = {
          name = var.acme_staging ? "letsencrypt-staging-account" : "letsencrypt-production-account"
        }
        solvers = concat(var.acme_solver == "cloudflare" ? [{
          dns01 = {
            cloudflare = {
              apiTokenSecretRef = {
                name = var.cloudflare_api_token_secret_name
                key  = "api-token"
              }
            }
          }
          }] : [], var.acme_solver == "http01" ? [{
          http01 = {
            ingress = {
              ingressClassName = "traefik"
              ingressTemplate = {
                metadata = {
                  annotations = {
                    "traefik.ingress.kubernetes.io/router.entrypoints" = "web"
                    "traefik.ingress.kubernetes.io/router.priority"    = "1000"
                  }
                }
              }
            }
          }
        }] : [])
      }, var.acme_email == "" ? {} : { email = var.acme_email })
    }
  })

  depends_on = [kustomization_resource.namespace]
}

resource "kustomization_resource" "certificate" {
  count = var.manage_certificate ? 1 : 0
  manifest = jsonencode({
    apiVersion = "cert-manager.io/v1"
    kind       = "Certificate"
    metadata = {
      name      = "duncarbox-tls"
      namespace = "duncarbox"
    }
    spec = {
      secretName = var.tls_secret_name
      dnsNames   = concat([var.ingress_host], var.proxy_ingress_host == "" ? [] : [var.proxy_ingress_host])
      issuerRef = {
        name = "duncarbox-letsencrypt"
        kind = "Issuer"
      }
      privateKey = {
        algorithm      = "RSA"
        size           = 2048
        rotationPolicy = "Always"
      }
    }
  })

  # Certificate readiness is checked explicitly with kubectl wait after apply.
  depends_on = [kustomization_resource.acme_issuer]
}
