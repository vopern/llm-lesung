output "public_ip" {
  description = "Fixed public IP (Elastic IP) of the instance — stable across stop/start."
  value       = aws_eip.web.public_ip
}

output "url" {
  description = "Site URL (plain HTTP, reachable only from your my_ip)."
  value       = "http://${aws_eip.web.public_ip}"
}

output "url_ipv6" {
  description = "Site URL over IPv6 (plain HTTP, reachable only from your my_ipv6 prefix). Stable across stop/start, changes if the instance is replaced."
  value       = "http://[${aws_instance.web.ipv6_addresses[0]}]"
}

output "ssh_cmd" {
  description = "SSH into the instance. Prefer `make ssh-ec2`, which passes SSH_KEY."
  value       = "ssh -i <SSH_KEY> ec2-user@${aws_eip.web.public_ip}"
}
