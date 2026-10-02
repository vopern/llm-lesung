# LLM-Lesung — single-EC2 AWS deployment
#
# The web tier is read-only: all Claude analysis runs locally and the resulting
# SQLite DB is uploaded separately (`make push-db`). The instance therefore makes
# no outbound API calls and needs no IAM role or registry; the only secret it can
# hold is the optional Cloudflare Tunnel token.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Credentials come from ~/.aws/credentials. No region here: it comes from the
# profile (`region` in ~/.aws/config), so account and region cannot drift.
provider "aws" {
  profile = var.aws_profile
}

# Own dual-stack network: one public subnet with an IPv4 and an IPv6 route out.
resource "aws_vpc" "main" {
  cidr_block                       = "10.0.0.0/16"
  assign_generated_ipv6_cidr_block = true

  tags = { Name = "llm-lesung" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "llm-lesung" }
}

resource "aws_subnet" "public" {
  vpc_id                          = aws_vpc.main.id
  cidr_block                      = "10.0.1.0/24"
  ipv6_cidr_block                 = cidrsubnet(aws_vpc.main.ipv6_cidr_block, 8, 0)
  assign_ipv6_address_on_creation = true

  tags = { Name = "llm-lesung" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  route {
    ipv6_cidr_block = "::/0"
    gateway_id      = aws_internet_gateway.main.id
  }

  tags = { Name = "llm-lesung" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Latest Amazon Linux 2023 x86_64 AMI (matches the t3 instance, so the image
# built on an x86_64 laptop runs without emulation).
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# SSH key pair created from a local public key — no console click-ops.
resource "aws_key_pair" "deployer" {
  key_name   = var.key_name
  public_key = file(pathexpand(var.ssh_public_key_path))
}

# No public access: both HTTP and SSH are restricted to var.my_ip and var.my_ipv6.
# No 443: public traffic, if any, arrives through the outbound Cloudflare Tunnel.
# Run `make infra-ip` + re-apply when your ISP address changes.
resource "aws_security_group" "web" {
  name_prefix = "llm-lesung-"
  description = "LLM-Lesung: HTTP + SSH from my_ip/my_ipv6 only (no public access)"
  vpc_id      = aws_vpc.main.id

  ingress {
    description      = "HTTP from operator"
    from_port        = 80
    to_port          = 80
    protocol         = "tcp"
    cidr_blocks      = [var.my_ip]
    ipv6_cidr_blocks = [var.my_ipv6]
  }

  ingress {
    description      = "SSH from operator"
    from_port        = 22
    to_port          = 22
    protocol         = "tcp"
    cidr_blocks      = [var.my_ip]
    ipv6_cidr_blocks = [var.my_ipv6]
  }

  egress {
    description      = "All outbound"
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = { Name = "llm-lesung" }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_instance" "web" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.deployer.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.web.id]
  ipv6_address_count     = 1
  user_data              = file("${path.module}/user-data.sh")

  # Auto-assigned public IP so cloud-init has internet the moment the box boots
  # (the Elastic IP below is associated only after the instance exists, which is
  # too late for the Docker install). The EIP then supersedes it as the address
  # everything else uses.
  associate_public_ip_address = true

  # A newer AMI must not silently replace the instance and its DB; rebuild
  # deliberately with `terraform apply -replace=aws_instance.web`.
  lifecycle {
    ignore_changes = [ami]
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
  }

  tags = { Name = "llm-lesung" }
}

# Fixed public address. Unlike the auto-assigned IP it survives stop/start, so
# the deploy targets, the browser bookmark and any future DNS record keep
# working. AWS charges for a public IPv4 either way, so this costs nothing
# extra while the instance runs (an EIP not attached to a running instance is
# billed at the same rate — release it with `make infra-down`, don't just stop
# the box).
resource "aws_eip" "web" {
  instance = aws_instance.web.id
  domain   = "vpc"

  tags = { Name = "llm-lesung" }
}
