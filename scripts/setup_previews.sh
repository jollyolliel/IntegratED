#!/usr/bin/env bash
# One-time Google Cloud and GitHub setup for PR previews (ADR 0013,
# docs/operations/previews.md). Run it by hand, one step at a time, as the project
# owner. Each step is safe to run again.
#
#   ./scripts/setup_previews.sh narrow-prod        # 1. prod deployer: only deploy.yml on master
#   ./scripts/setup_previews.sh project            # 2. preview project, accounts, IAP, budget
#   ./scripts/setup_previews.sh oauth FILE         # 3. attach the OAuth client made in the console
#   ./scripts/setup_previews.sh reviewer EMAIL...  # 4. who may open previews
#   ./scripts/setup_previews.sh enable             # 5. set the repo variables: previews are on
#
# `project` needs BILLING_ACCOUNT (gcloud billing accounts list). Every other value
# has a default below and can be overridden from the environment.
set -euo pipefail

REPO="${REPO:-jollyolliel/IntegratED}"
PROD_PROJECT="${PROD_PROJECT:-$(gh variable get GCP_PROJECT_ID --repo "$REPO")}"
PROD_DEPLOYER="${PROD_DEPLOYER:-$(gh variable get DEPLOY_SERVICE_ACCOUNT --repo "$REPO")}"
WIF_PROVIDER="${WIF_PROVIDER:-$(gh variable get WIF_PROVIDER --repo "$REPO")}"
# projects/<number>/locations/global/workloadIdentityPools/<pool>/providers/<provider>
POOL="${WIF_PROVIDER%/providers/*}"
POOL_ID="${POOL##*/}"
PROVIDER_ID="${WIF_PROVIDER##*/}"

PREVIEW_PROJECT="${PREVIEW_PROJECT:-integrated-preview}"
REGION="${REGION:-$(gh variable get GCP_REGION --repo "$REPO")}"
AR_REPO="${AR_REPO:-previews}"
BUDGET="${BUDGET:-10}"
DEPLOYER="preview-deployer@$PREVIEW_PROJECT.iam.gserviceaccount.com"
RUNTIME="preview-runtime@$PREVIEW_PROJECT.iam.gserviceaccount.com"

OLD_PROD_MEMBER="principalSet://iam.googleapis.com/$POOL/attribute.repository/$REPO"
NEW_PROD_MEMBER="principalSet://iam.googleapis.com/$POOL/attribute.workflow_ref/$REPO/.github/workflows/deploy.yml@refs/heads/master"

prod_policy() {
    gcloud iam service-accounts get-iam-policy "$PROD_DEPLOYER" --project "$PROD_PROJECT" --format=json
}

# The repository-wide binding lets any workflow on any branch deploy production. A PR can
# add or edit a workflow, so this must be narrowed before preview.yml runs PR code. A branch
# condition is not enough: claude.yml also asks for a token, and its runs count as master.
narrow_prod() {
    gcloud iam workload-identity-pools providers update-oidc "$PROVIDER_ID" \
        --project "$PROD_PROJECT" --location global --workload-identity-pool "$POOL_ID" \
        --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.workflow_ref=assertion.workflow_ref"
    gcloud iam service-accounts add-iam-policy-binding "$PROD_DEPLOYER" --project "$PROD_PROJECT" \
        --role roles/iam.workloadIdentityUser --member "$NEW_PROD_MEMBER" > /dev/null
    # Read into a variable first: inside an `if`, a failed read would pass as "not there".
    policy=$(prod_policy)
    if grep -qF "\"$OLD_PROD_MEMBER\"" <<< "$policy"; then
        gcloud iam service-accounts remove-iam-policy-binding "$PROD_DEPLOYER" --project "$PROD_PROJECT" \
            --role roles/iam.workloadIdentityUser --member "$OLD_PROD_MEMBER" > /dev/null
    fi
    cat <<EOF
The prod deployer now trusts only deploy.yml on master. IAM changes take a few minutes.
Check that the next push to master still deploys. To undo:
  gcloud iam service-accounts add-iam-policy-binding $PROD_DEPLOYER --project $PROD_PROJECT \\
    --role roles/iam.workloadIdentityUser --member '$OLD_PROD_MEMBER'
EOF
}

project() {
    : "${BILLING_ACCOUNT:?set BILLING_ACCOUNT (gcloud billing accounts list)}"
    gcloud projects describe "$PREVIEW_PROJECT" > /dev/null 2>&1 \
        || gcloud projects create "$PREVIEW_PROJECT" --name="IntegratED Preview"
    gcloud billing projects link "$PREVIEW_PROJECT" --billing-account "$BILLING_ACCOUNT" > /dev/null
    gcloud services enable --project "$PREVIEW_PROJECT" \
        run.googleapis.com artifactregistry.googleapis.com iap.googleapis.com iam.googleapis.com \
        iamcredentials.googleapis.com sts.googleapis.com cloudresourcemanager.googleapis.com \
        billingbudgets.googleapis.com

    gcloud artifacts repositories describe "$AR_REPO" --project "$PREVIEW_PROJECT" --location "$REGION" > /dev/null 2>&1 \
        || gcloud artifacts repositories create "$AR_REPO" --project "$PREVIEW_PROJECT" --location "$REGION" \
            --repository-format docker

    for account in preview-deployer preview-runtime; do
        gcloud iam service-accounts describe "$account@$PREVIEW_PROJECT.iam.gserviceaccount.com" \
            --project "$PREVIEW_PROJECT" > /dev/null 2>&1 \
            || gcloud iam service-accounts create "$account" --project "$PREVIEW_PROJECT"
    done
    # The runtime account is given no role, on purpose: it is what the PR's code runs as.
    # run.developer cannot change a service's IAM policy, so even a rewritten workflow
    # cannot make a preview public.
    gcloud projects add-iam-policy-binding "$PREVIEW_PROJECT" --condition=None \
        --member "serviceAccount:$DEPLOYER" --role roles/run.developer > /dev/null
    gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --project "$PREVIEW_PROJECT" --location "$REGION" \
        --member "serviceAccount:$DEPLOYER" --role roles/artifactregistry.repoAdmin > /dev/null
    gcloud iam service-accounts add-iam-policy-binding "$RUNTIME" --project "$PREVIEW_PROJECT" \
        --member "serviceAccount:$DEPLOYER" --role roles/iam.serviceAccountUser > /dev/null
    # Any branch of this repository may act as the preview deployer: it reaches only this project.
    gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" --project "$PREVIEW_PROJECT" \
        --member "$OLD_PROD_MEMBER" --role roles/iam.workloadIdentityUser > /dev/null

    # IAP calls each service as its own service agent. Granted project-wide, so a new
    # pr-<N> service needs no IAM change (which the deployer could not make).
    gcloud beta services identity create --service iap.googleapis.com --project "$PREVIEW_PROJECT"
    number=$(gcloud projects describe "$PREVIEW_PROJECT" --format='value(projectNumber)')
    gcloud projects add-iam-policy-binding "$PREVIEW_PROJECT" --condition=None \
        --member "serviceAccount:service-$number@gcp-sa-iap.iam.gserviceaccount.com" \
        --role roles/run.invoker > /dev/null

    # An alert by email, not a spending cap; --max-instances=1 is what bounds each service.
    if ! gcloud billing budgets list --billing-account "$BILLING_ACCOUNT" --format='value(displayName)' \
        | grep -qx "integrated-preview"; then
        gcloud billing budgets create --billing-account "$BILLING_ACCOUNT" --display-name integrated-preview \
            --budget-amount "$BUDGET" --filter-projects "projects/$number" \
            --threshold-rule percent=0.5 --threshold-rule percent=1.0
    fi
    cat <<EOF

Now make the OAuth client in the console (project $PREVIEW_PROJECT). A project outside a
Google Cloud organization cannot use IAP's built-in client.
  1. Google Auth Platform > Branding: create the consent screen, audience "External".
     While it is in "Testing", add every reviewer as a test user.
  2. Clients > Create client > Web application. Copy the client ID and secret, then edit the
     client and add this authorised redirect URI, with your client ID in it:
       https://iap.googleapis.com/v1/oauth/clientIds/CLIENT_ID:handleRedirect
  3. Save this to a file OUTSIDE the repository, run the 'oauth' step on it, then delete it:
       access_settings:
         oauth_settings:
           client_id: CLIENT_ID
           client_secret: CLIENT_SECRET
EOF
}

oauth() {
    [ -f "${1:-}" ] || { echo "usage: $0 oauth SETTINGS_FILE" >&2; exit 2; }
    gcloud iap settings set "$1" --project "$PREVIEW_PROJECT"
    echo "Attached. Delete $1 now: it holds the client secret."
}

reviewer() {
    [ "$#" -gt 0 ] || { echo "usage: $0 reviewer EMAIL..." >&2; exit 2; }
    for email in "$@"; do
        gcloud projects add-iam-policy-binding "$PREVIEW_PROJECT" --condition=None \
            --member "user:$email" --role roles/iap.httpsResourceAccessor > /dev/null
        echo "$email can open previews."
    done
}

# Last, because these variables are what switch preview.yml on.
enable() {
    policy=$(prod_policy)  # a failed read stops here rather than passing the check
    if grep -qF "\"$OLD_PROD_MEMBER\"" <<< "$policy" || ! grep -qF "\"$NEW_PROD_MEMBER\"" <<< "$policy"; then
        echo "Refusing: the prod deployer still trusts every workflow. Run '$0 narrow-prod' first." >&2
        exit 1
    fi
    gh variable set PREVIEW_REGION --repo "$REPO" --body "$REGION"
    gh variable set PREVIEW_ARTIFACT_REPO --repo "$REPO" --body "$AR_REPO"
    gh variable set PREVIEW_DEPLOY_SERVICE_ACCOUNT --repo "$REPO" --body "$DEPLOYER"
    gh variable set PREVIEW_RUNTIME_SERVICE_ACCOUNT --repo "$REPO" --body "$RUNTIME"
    gh variable set PREVIEW_PROJECT_ID --repo "$REPO" --body "$PREVIEW_PROJECT"
    echo "Previews are on. The next PR push gets one."
}

case "${1:-}" in
    narrow-prod) narrow_prod ;;
    project) project ;;
    oauth) shift; oauth "$@" ;;
    reviewer) shift; reviewer "$@" ;;
    enable) enable ;;
    *) sed -n '2,15p' "$0"; exit 2 ;;
esac
