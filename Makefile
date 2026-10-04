# ReadLayer task runner. Cloud targets verify the gcloud identity first (see CLAUDE.local.md).

PROJECT  := readlayer-sourabh-26
ACCOUNT  := sourabhlocalllm@gmail.com
REGION   := asia-south1
SERVICE  := readlayer-api
SA       := $(SERVICE)@$(PROJECT).iam.gserviceaccount.com

# Isolated gcloud config, and override the shell profile's credentials with this project's ADC.
export CLOUDSDK_CONFIG := $(HOME)/.config/gcloud-readlayer
export GOOGLE_APPLICATION_CREDENTIALS := $(CLOUDSDK_CONFIG)/application_default_credentials.json

API := cd apps/api &&

.PHONY: dev dev-api dev-web test smoke check-gcp setup-gcp deploy-api deploy-web

# Local only: API (:8000, dev auth bypass, reads Firestore + graph with this project's ADC) and
# web (:5173, proxies /v1). Ctrl-C stops both. The API refuses the bypass on Cloud Run.
dev: check-gcp
	DEV_AUTH_BYPASS=true $(MAKE) -j2 dev-api dev-web

dev-api:
	$(API) uv run fastapi dev app/main.py

dev-web:
	pnpm --filter web dev

test:
	$(API) uv run ruff check . && uv run ruff format --check . && uv run pytest -q
	pnpm -r typecheck
	pnpm -r test

smoke:
	$(API) uv run python -m scripts.smoke_llm

check-gcp:
	@actual="$$(gcloud config list --format='value(core.account,core.project)' | tr '\t' ' ')"; \
	if [ "$$actual" != "$(ACCOUNT) $(PROJECT)" ]; then \
		echo "gcloud identity mismatch: got '$$actual', want '$(ACCOUNT) $(PROJECT)'"; exit 1; \
	fi

# One-time: least-privilege runtime identity and the log-hash salt (DESIGN §11.5).
setup-gcp: check-gcp
	gcloud iam service-accounts create $(SERVICE) --display-name="ReadLayer API runtime"
	for role in roles/aiplatform.user roles/datastore.user roles/logging.logWriter; do \
		gcloud projects add-iam-policy-binding $(PROJECT) --member=serviceAccount:$(SA) \
			--role=$$role --condition=None --quiet >/dev/null || exit 1; done
	openssl rand -hex 32 | tr -d '\n' | gcloud secrets create uid-hash-salt --data-file=- \
		--replication-policy=user-managed --locations=$(REGION)
	gcloud secrets add-iam-policy-binding uid-hash-salt --member=serviceAccount:$(SA) \
		--role=roles/secretmanager.secretAccessor

deploy-api: check-gcp
	gcloud run deploy $(SERVICE) --source apps/api --region $(REGION) \
		--service-account $(SA) --allow-unauthenticated \
		--min-instances 0 --max-instances 3 --cpu 1 --memory 1Gi \
		--env-vars-file apps/api/deploy.env.yaml \
		--set-secrets UID_HASH_SALT=uid-hash-salt:latest

deploy-web: check-gcp
	pnpm --filter web build
	pnpm exec firebase deploy --only hosting --project $(PROJECT)
