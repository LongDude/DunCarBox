locals {
  # Each component publishes its tag only after a successful registry push.
  # The old shared variable is a migration fallback for existing installations.
  backend_image_tag  = try(trimspace(file("${path.module}/../../backend/.tofu/image-tag")), var.image_tag)
  frontend_image_tag = try(trimspace(file("${path.module}/../../frontend/.tofu/image-tag")), var.image_tag)
}
