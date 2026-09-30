IMAGE ?= k8s-gitops-app:local

.PHONY: install lint test run image manifests
install:
	pip install -r requirements-dev.txt
lint:
	ruff check . && ruff format --check .
test:
	pytest
run:
	uvicorn app.main:app --reload --port 8080
image:
	docker build -t $(IMAGE) .
manifests:
	@for env in dev prod; do kustomize build deploy/overlays/$$env | kubeconform -strict -summary; done
