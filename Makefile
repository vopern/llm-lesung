# LLM-Lesung — common operations. See README.md for details.

.PHONY: setup pipeline pipeline-all redteam redteam-all serve dev build test \
        gg-build gg-run gg-score gg-report gg-eval \
        eval-fetch eval-lint eval-export eval-score eval-run eval-report \
        infra-up infra-ip infra-down deploy push-db push-eval pull-feedback ssh-ec2 dockerlogs

# --- Local: app + pipeline runs ----------------------------------------------
LIMIT ?= 5

setup:            ## install backend + frontend deps
	uv sync
	cd frontend && npm install

pipeline:         ## analyze LIMIT bills (default 5), e.g. make pipeline LIMIT=20
	uv run python -m backend.pipeline --limit $(LIMIT)

pipeline-all:     ## analyze the full legislative period (~340 bills, ~$$45)
	uv run python -m backend.pipeline

redteam:          ## red-team LIMIT stored bills (default 5), one Claude call each
	uv run python -m backend.redteam_pipeline --limit $(LIMIT)

redteam-all:      ## red-team every stored bill whose pass is missing or outdated
	uv run python -m backend.redteam_pipeline

locate-quotes:    ## find page and context of the stored findings' quotes (free, no Claude call)
	uv run python -m backend.locate_quotes

serve: build      ## build frontend and serve app on http://localhost:8000
	uv run uvicorn backend.server:app --port 8000

dev:              ## backend with reload + vite dev server (hot reload)
	uv run uvicorn backend.server:app --reload --port 8000 & cd frontend && npm run dev

build:            ## production frontend build
	cd frontend && npm run build

test:             ## run the backend test suite
	uv run pytest

# --- Eval: test set (eval/README.md) -----------------------------------------
eval-fetch:       ## download the pinned Drucksache texts into eval/testset/texts/
	uv run python -m eval.testset fetch
eval-lint:        ## check the test set: schema, text hashes, anchors, splits, canary (free, offline)
	uv run python -m eval.testset lint
eval-export:      ## one JSONL sample per document -> data/testset/export/ (free, offline)
	uv run python -m eval.testset export
eval-score:       ## passage recall of the stored findings against the anchors (free, offline)
	uv run python -m eval.testset score db

# --- Eval: harness, Lektor or Angreifer on the pinned drafts (eval/README.md) --
EVAL_TASK  ?= lektor
EVAL_CASES ?=
EVAL_SPLIT ?= all
EVAL_ONLY  ?=
EVAL_TAG   ?=
EVAL_EFFORT ?=
EVAL_TURNS  ?=
EVAL_CONTEXT ?=
EVAL_ORACLE  ?=
EVAL_BE      ?=
EVAL_ARGS   = --task $(EVAL_TASK) $(if $(EVAL_CASES),--cases $(EVAL_CASES),) \
              $(if $(EVAL_TAG),--tag $(EVAL_TAG),) \
              $(if $(EVAL_CONTEXT),--context $(EVAL_CONTEXT),) \
              $(if $(EVAL_ORACLE),--oracle,) \
              $(if $(EVAL_BE),--beschlussempfehlung,) \
              $(if $(EVAL_EFFORT),--effort $(EVAL_EFFORT),) \
              $(if $(EVAL_TURNS),--max-turns $(EVAL_TURNS),)

eval-run:         ## run EVAL_TASK (lektor|angreifer) on the test-set drafts and score (costs money, one call per draft)
	uv run python -m eval.harness run $(EVAL_ARGS) --split $(EVAL_SPLIT) \
		$(if $(EVAL_ONLY),--only $(EVAL_ONLY),)
eval-report:      ## re-score a harness run -> data/eval/runs/<task>-<tag>/ (free, offline)
	uv run python -m eval.harness report $(EVAL_ARGS) --split $(EVAL_SPLIT)

# --- Eval: GG-recall (eval/README.md) ----------------------------------------
GG_MODEL ?= claude-sonnet-5
GG_TAG   ?= $(GG_MODEL)-on
GG_LIMIT ?=

gg-build:         ## download the Grundgesetz and build the test set (free, offline after)
	uv run python -m eval.gg fetch
	uv run python -m eval.gg build

gg-run:           ## ask GG_MODEL every test item via the Claude CLI (costs money)
	uv run python -m eval.gg run --model $(GG_MODEL) --tag $(GG_TAG) \
		$(if $(GG_LIMIT),--limit $(GG_LIMIT),)

gg-score:         ## score the last run mechanically -> data/gg/report-<tag>.html
	uv run python -m eval.gg score --tag $(GG_TAG)

gg-report:        ## re-render a stored score file -> data/gg/report-<tag>.html (free, offline)
	uv run python -m eval.gg report --tag $(GG_TAG)

gg-eval: gg-build gg-run gg-score  ## the whole GG-recall eval end to end

# --- Deployment: AWS (docs/DEPLOYMENT.md) ------------------------------------
-include .env
SSH_KEY := $(patsubst ~/%,$(HOME)/%,$(SSH_KEY))

export TF_VAR_aws_profile         := $(AWS_PROFILE)
export TF_VAR_ssh_public_key_path := $(if $(SSH_KEY),$(SSH_KEY).pub)
export TUNNEL_TOKEN
export CONTACT_EMAIL

IMAGE_TAR    = /tmp/llm-lesung-image.tar.gz
REMOTE_TAR   = /app/llm-lesung-image.tar.gz

RESOLVE_HOST = HOST=$$(cd infra && terraform output -raw public_ip)
SSH          = ssh -i $(or $(SSH_KEY),$(error SSH_KEY is not set in .env)) ec2-user@$$HOST
SCP          = scp -i $(or $(SSH_KEY),$(error SSH_KEY is not set in .env))

infra-up:         ## provision the AWS instance (terraform apply)
	cd infra && terraform init -input=false && terraform apply

infra-ip:         ## write your current public IPv4 and IPv6 /64 into infra/terraform.tfvars (then: make infra-up)
	@IP="$$(curl -4 -fsS https://ifconfig.me)/32"; \
	sed -i "s|^my_ip .*|my_ip = \"$$IP\"|" infra/terraform.tfvars; \
	echo "my_ip = $$IP"; \
	IP6="$$(curl -6 -fsS --max-time 5 https://ifconfig.me)" || { echo "no IPv6 — my_ipv6 unchanged"; exit 0; }; \
	NET6="$$(python3 -c 'import ipaddress,sys; print(ipaddress.ip_network(sys.argv[1] + "/64", strict=False))' "$$IP6")"; \
	sed -i "s|^my_ipv6 .*|my_ipv6 = \"$$NET6\"|" infra/terraform.tfvars; \
	echo "my_ipv6 = $$NET6"

infra-down:       ## tear down all AWS resources (terraform destroy)
	cd infra && terraform destroy

deploy:           ## build the image locally, ship it to the instance, restart (starts the tunnel if TUNNEL_TOKEN is set)
	@$(RESOLVE_HOST); \
	docker buildx build --platform linux/amd64 --provenance=false --sbom=false \
		-t llm-lesung:latest --load . && \
	docker save llm-lesung:latest | gzip --rsyncable > $(IMAGE_TAR) && \
	rsync -h --progress --partial -e "ssh -i $(SSH_KEY)" \
		$(IMAGE_TAR) ec2-user@$$HOST:$(REMOTE_TAR) && \
	$(SSH) 'gunzip -c $(REMOTE_TAR) | docker load' && \
	$(SCP) compose.prod.yaml ec2-user@$$HOST:/app/compose.yaml && \
	printf 'COMPOSE_PROFILES=%s\nTUNNEL_TOKEN=%s\nCONTACT_EMAIL=%s\n' \
		"$${TUNNEL_TOKEN:+tunnel}" "$$TUNNEL_TOKEN" "$$CONTACT_EMAIL" | \
		$(SSH) 'umask 077 && cat > /app/.env' && \
	$(SSH) 'cd /app && docker compose up -d' && \
	echo "Deployed: http://$$HOST$${TUNNEL_TOKEN:+ (tunnel running)}"

push-db:          ## upload data/llm-lesung.db to the instance (atomic, no restart)
	@$(RESOLVE_HOST); \
	rsync -avz -e "ssh -i $(SSH_KEY)" data/llm-lesung.db ec2-user@$$HOST:/app/data/llm-lesung.db.tmp && \
	$(SSH) 'mv /app/data/llm-lesung.db.tmp /app/data/llm-lesung.db' && \
	echo "DB updated."

push-eval:        ## upload data/eval-public as a new release and switch to it atomically (no restart)
	@$(RESOLVE_HOST); REL=$$(date -u +%Y%m%dT%H%M%SZ); \
	test -d data/eval-public || { echo "no data/eval-public"; exit 1; }; \
	$(SSH) 'mkdir -p /app/data/eval-releases' && \
	rsync -az -e "ssh -i $(SSH_KEY)" data/eval-public/ ec2-user@$$HOST:/app/data/eval-releases/$$REL/ && \
	$(SSH) "cd /app/data && ln -sfn eval-releases/$$REL eval-public.tmp && mv -T eval-public.tmp eval-public \
		&& ls -1d eval-releases/* | head -n -3 | xargs -r rm -rf" && \
	echo "Eval release $$REL live (previous releases kept: 2)."

pull-feedback:    ## download the reader feedback files into data/feedback/
	@$(RESOLVE_HOST); mkdir -p data/feedback && \
	rsync -avz -e "ssh -i $(SSH_KEY)" ec2-user@$$HOST:/app/data/feedback/ data/feedback/

ssh-ec2:          ## open a shell on the instance
	@$(RESOLVE_HOST); $(SSH)

dockerlogs:       ## follow the container logs on the instance
	@$(RESOLVE_HOST); $(SSH) 'cd /app && docker compose logs --follow --tail 100'
