variable "aws_profile" {
  description = "Profile in ~/.aws/credentials; also supplies the region. Required, no default. Set as AWS_PROFILE in .env."
  type        = string
}

variable "my_ip" {
  description = "Your public IP in CIDR form for SSH access, e.g. \"203.0.113.4/32\". Find it with `curl -4 ifconfig.me`."
  type        = string
}

variable "my_ipv6" {
  description = "Your IPv6 /64 prefix, e.g. \"2001:db8:1:2::/64\" — a prefix, because the host part of an outgoing IPv6 address rotates daily. `make infra-ip` fills in both addresses."
  type        = string
}

variable "instance_type" {
  description = "x86_64 instance, so local builds need no emulation. t3.micro (1 GB) is ample; t3.nano (0.5 GB) also fits."
  type        = string
  default     = "t3.micro"
}

variable "key_name" {
  description = "Name for the EC2 key pair Terraform creates from ssh_public_key_path."
  type        = string
  default     = "llm-lesung"
}

variable "ssh_public_key_path" {
  description = "Public key uploaded as the EC2 key pair. Required, no default. Derived from SSH_KEY in .env. Changing it replaces the instance."
  type        = string
}
