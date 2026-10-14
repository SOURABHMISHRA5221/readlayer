# ReadLayer task runner. Cloud targets verify the gcloud identity first (see CLAUDE.local.md).

PROJECT  := readlayer-sourabh-26
# The project's Google account, kept out of git: `.gcp.local.mk` (gitignored) holds
# `ACCOUNT := <address>` (the value is in CLAUDE.local.md).
-include .gcp.local.mk
REGION   := asia-south1
SERVICE  := readlayer-api
SA       := $(SERVICE)@$(PROJECT).iam.gserviceaccount.com

# Isolated gcloud config, and override the shell profile's credentials with this project's ADC.
export CLOUDSDK_CONFIG := $(HOME)/.config/gcloud-readlayer
export GOOGLE_APPLICATION_CREDENTIALS := $(CLOUDSDK_CONFIG)/application_default_credentials.json

API := cd apps/api &&
WEB_APP  := readlayer-web
HOSTING  := https://$(PROJECT).web.app,https://$(PROJECT).firebaseapp.com
# M8: the Gloss extension's fixed id (public key in apps/extension/manifest.base.json).
EXT_ID   := lnfamfbeffepopbmedfenfmgljoacbmg
JAVA21   := $(HOME)/.sdkman/candidates/java/21.0.12-amzn
# Decision 50: Cloud Scheduler calls the outlet collection with an OIDC token for this account.
FEED_SA  := feed-job@$(PROJECT).iam.gserviceaccount.com
FEED_URL := https://readlayer-api-d2sfihz3za-el.a.run.app/v1/internal/feeds/collect
FEED_JOB := readlayer-feed-collect
SECRETS  := UID_HASH_SALT=uid-hash-salt:latest,TAVILY_API_KEY=tavily-api-key:latest,YOUTUBE_API_KEY=youtube-api-key:latest

.PHONY: dev dev-api dev-web dev-emulator test test-emulator smoke check-gcp setup-gcp web-config deploy-api \
	deploy-web deploy-rules deploy-guard setup-feed-job run-feed-job extension-zip

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
# Local end-to-end harness (M7): emulators seeded read-only from production; no production writes.
dev-emulator: check-gcp
	apps/api/scripts/dev_emulator.sh

test-emulator:
	JAVA_HOME=$(JAVA21) PATH=$(JAVA21)/bin:$$PATH pnpm exec firebase emulators:exec \
		--project demo-readlayer --only firestore,auth "cd apps/api && uv run pytest -q -m emulator"

smoke:
	$(API) uv run python -m scripts.smoke_llm

check-gcp:
	@test -n "$(ACCOUNT)" || { echo "ACCOUNT unset: create .gcp.local.mk (see CLAUDE.local.md)"; exit 1; }
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

# One-time (decision 50, needs Sourabh's yes): the outlet collection's caller identity (no roles:
# the API checks the token itself) and one job at 06:00 and 18:00 IST. The API must already run
# with FEED_JOB_SA_EMAIL / FEED_JOB_AUDIENCE (deploy.env.yaml) = FEED_SA / FEED_URL.
setup-feed-job: check-gcp
	gcloud services enable cloudscheduler.googleapis.com
	gcloud iam service-accounts create feed-job --display-name="ReadLayer outlet collection (Scheduler)"
	gcloud scheduler jobs create http $(FEED_JOB) --location=$(REGION) \
		--schedule="0 6,18 * * *" --time-zone="Asia/Kolkata" --uri=$(FEED_URL) --http-method=POST \
		--oidc-service-account-email=$(FEED_SA) --oidc-token-audience=$(FEED_URL) \
		--attempt-deadline=300s --max-retry-attempts=1

# A manual run of the same job (same token, same endpoint).
run-feed-job: check-gcp
	gcloud scheduler jobs run $(FEED_JOB) --location=$(REGION)

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

# M8: the extension as a zip for a GitHub release (judges unzip it and "Load unpacked"). The build
# needs no cloud access: apps/extension/.env.production holds public URLs only.
extension-zip:
	pnpm --filter extension build
	rm -f apps/extension/gloss-extension.zip
	cd apps/extension/dist && zip -qr ../gloss-extension.zip .
	@echo "wrote apps/extension/gloss-extension.zip"

# Hosting origins only for CORS; secrets from Secret Manager, never env files or the image.
# Startup CPU boost: extra CPU while an instance starts, which roughly halves cold starts.
# Refuse to start a deploy while another is in flight: a deploy on this machine (still uploading,
# so not yet visible in the cloud), a Cloud Build in progress, or a Cloud Run rollout of the API.
# Two overlapping deploys of the same source happened once in M4; the second only wasted a build.
deploy-guard: check-gcp
	@busy=""; \
	local="$$(pgrep -fl '[g]cloud.* run deploy|[f]irebase.* deploy' || true)"; \
	[ -z "$$local" ] || busy="$$busy\n  deploy running on this machine:\n$$local"; \
	builds="$$(gcloud builds list --ongoing --region $(REGION) --format='value(id,status)'; \
		gcloud builds list --ongoing --format='value(id,status)')"; \
	[ -z "$$builds" ] || busy="$$busy\n  Cloud Builds in progress:\n$$builds"; \
	ready="$$(gcloud run services describe $(SERVICE) --region $(REGION) \
		--format='value(status.conditions[0].status)')"; \
	[ "$$ready" != "Unknown" ] || busy="$$busy\n  Cloud Run $(SERVICE) is mid-rollout"; \
	if [ -n "$$busy" ]; then printf "deploy refused:$$busy\n"; exit 1; fi; \
	echo "deploy guard: nothing in flight"

deploy-api: deploy-guard
	gcloud run deploy $(SERVICE) --source apps/api --region $(REGION) \
		--service-account $(SA) --allow-unauthenticated \
		--min-instances 0 --max-instances 3 --cpu 1 --memory 1Gi --cpu-boost \
		--env-vars-file apps/api/deploy.env.yaml \
		--set-secrets $(SECRETS)

# The link box copy follows the API's video switch (media plan 5R8): read from the same file the
# API deploys with, passed to the build (process env beats .env files in Vite), never stored.
deploy-web: deploy-guard
	test -f apps/web/.env.local -a -f apps/web/.env.production.local || $(MAKE) web-config
	@video="$$(sed -En 's/^MEDIA_VIDEO_ENABLED: *"?(true|false)"? *$$/\1/p' apps/api/deploy.env.yaml)"; \
	test -n "$$video" || { echo "MEDIA_VIDEO_ENABLED missing from apps/api/deploy.env.yaml"; exit 1; }; \
	echo "web build: VITE_MEDIA_VIDEO=$$video"; \
	VITE_MEDIA_VIDEO="$$video" pnpm --filter web build
	pnpm exec firebase deploy --only hosting --project $(PROJECT)

# Deny-all Firestore rules (DESIGN §11.4).
deploy-rules: check-gcp
	pnpm exec firebase deploy --only firestore:rules --project $(PROJECT)
