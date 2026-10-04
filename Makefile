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
WEB_APP  := readlayer-web
HOSTING  := https://$(PROJECT).web.app,https://$(PROJECT).firebaseapp.com
JAVA21   := $(HOME)/.sdkman/candidates/java/21.0.12-amzn
SECRETS  := UID_HASH_SALT=uid-hash-salt:latest,TAVILY_API_KEY=tavily-api-key:latest,YOUTUBE_API_KEY=youtube-api-key:latest

.PHONY: dev dev-api dev-web test test-emulator smoke check-gcp setup-gcp web-config deploy-api \
	deploy-web deploy-rules

# Local only: API (:8000, real Firebase sign-in, reads Firestore + graph with this project's ADC)
# and web (:5173, proxies /v1). Ctrl-C stops both. Needs apps/web/.env.local (make web-config).
# For curl without a token, run the API with DEV_AUTH_BYPASS=true (refused on Cloud Run).
dev: check-gcp
	$(MAKE) -j2 dev-api dev-web

dev-api:
	$(API) uv run fastapi dev app/main.py

dev-web:
	pnpm --filter web dev

test:
	$(API) uv run ruff check . && uv run ruff format --check . && uv run pytest -q
	pnpm -r typecheck
	pnpm -r test

# Firestore + Auth emulators (Java 21): export/delete, transactions, deny-all rules.
test-emulator:
	JAVA_HOME=$(JAVA21) PATH=$(JAVA21)/bin:$$PATH pnpm exec firebase emulators:exec \
		--project demo-readlayer --only firestore,auth "cd apps/api && uv run pytest -q -m emulator"

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

# Firebase web config (public by design, kept out of git) for local dev and the Hosting build,
# and the API origin for the Hosting build. Writes apps/web/.env.local and .env.production.local.
web-config: check-gcp
	@app_id="$$(pnpm exec firebase apps:list WEB --project $(PROJECT) --json \
		| python3 -c "import json,sys; a=[x for x in json.load(sys.stdin)['result'] if x['displayName']=='$(WEB_APP)']; print(a[0]['appId'] if a else '')")"; \
	test -n "$$app_id" || { echo "no Firebase web app named $(WEB_APP)"; exit 1; }; \
	pnpm exec firebase apps:sdkconfig WEB "$$app_id" --project $(PROJECT) --json \
		| python3 -c "import json,sys; c=json.load(sys.stdin)['result']['sdkConfig']; \
print('\n'.join(f'VITE_FIREBASE_{k}={c[v]}' for k,v in [('API_KEY','apiKey'),('AUTH_DOMAIN','authDomain'),('PROJECT_ID','projectId'),('APP_ID','appId')]))" \
		> apps/web/.env.local
	@echo "VITE_API_BASE=$$(gcloud run services describe $(SERVICE) --region $(REGION) --format='value(status.url)')" \
		> apps/web/.env.production.local
	@echo "wrote apps/web/.env.local and apps/web/.env.production.local (gitignored)"

# Hosting origins only for CORS; secrets from Secret Manager, never env files or the image.
deploy-api: check-gcp
	gcloud run deploy $(SERVICE) --source apps/api --region $(REGION) \
		--service-account $(SA) --allow-unauthenticated \
		--min-instances 0 --max-instances 3 --cpu 1 --memory 1Gi \
		--env-vars-file apps/api/deploy.env.yaml \
		--set-secrets $(SECRETS)

deploy-web: check-gcp
	test -f apps/web/.env.local -a -f apps/web/.env.production.local || $(MAKE) web-config
	pnpm --filter web build
	pnpm exec firebase deploy --only hosting --project $(PROJECT)

# Deny-all Firestore rules (DESIGN §11.4).
deploy-rules: check-gcp
	pnpm exec firebase deploy --only firestore:rules --project $(PROJECT)
