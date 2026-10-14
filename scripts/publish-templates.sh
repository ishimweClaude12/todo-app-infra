#!/usr/bin/env bash
# Publish the nested templates so the root template can reach them.
#
# CloudFormation Git sync deploys a single template file and does not run
# `aws cloudformation package`, so a nested stack's TemplateURL has to be a real
# S3 URL. This script uploads every template except the root to the foundation
# artifact bucket under a versioned prefix, and rewrites TemplatesPrefix in the
# deployment file to match. Commit and push, and Git sync deploys the new set.
#
# The default prefix is a hash of the nested templates' contents, so the same
# set of templates always maps to the same prefix. Unchanged templates leave the
# deployment file untouched, which is what lets CI run this on every push.
#
#   scripts/publish-templates.sh            # prefix infra-templates/<content hash>
#   scripts/publish-templates.sh my-prefix  # explicit prefix
set -euo pipefail

PROJECT="${PROJECT:-todo-app}"
AWS_REGION="${AWS_REGION:-us-east-1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_TEMPLATE="infrastructure.yaml"
DEPLOYMENT_FILE="$REPO_ROOT/.cfn/infrastructure.deployment.yaml"

if [[ -n "${1:-}" ]]; then
  PREFIX="$1"
else
  # Hash file names and contents of every nested template (root excluded).
  HASH=$(cd "$REPO_ROOT/templates" \
    && find . -maxdepth 1 -name '*.yaml' ! -name "$ROOT_TEMPLATE" -print0 \
    | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -c1-12)
  PREFIX="infra-templates/${HASH}"
fi

BUCKET=$(aws cloudformation list-exports \
  --query "Exports[?Name=='${PROJECT}-artifact-bucket-name'].Value" \
  --output text --region "$AWS_REGION")

if [[ -z "$BUCKET" || "$BUCKET" == "None" ]]; then
  echo "Could not resolve the ${PROJECT}-artifact-bucket-name export." >&2
  echo "Deploy the foundation stack first." >&2
  exit 1
fi

echo "Validating templates..."
for t in "$REPO_ROOT"/templates/*.yaml; do
  aws cloudformation validate-template \
    --template-body "file://$t" --region "$AWS_REGION" >/dev/null
  echo "  ok  $(basename "$t")"
done

echo "Publishing to s3://${BUCKET}/${PREFIX}/ ..."
aws s3 sync "$REPO_ROOT/templates/" "s3://${BUCKET}/${PREFIX}/" \
  --exclude '*' --include '*.yaml' --exclude "$ROOT_TEMPLATE" \
  --region "$AWS_REGION"

# Point the deployment file at the prefix just published.
if [[ -f "$DEPLOYMENT_FILE" ]]; then
  sed -i.bak -E "s|^([[:space:]]*TemplatesPrefix:[[:space:]]*).*$|\1${PREFIX}|" "$DEPLOYMENT_FILE"
  rm -f "${DEPLOYMENT_FILE}.bak"
  echo "Set TemplatesPrefix: ${PREFIX} in .cfn/infrastructure.deployment.yaml"
fi

echo
echo "Done. Commit the deployment file and push to let Git sync deploy:"
echo "  git add .cfn/infrastructure.deployment.yaml templates && git commit && git push"
