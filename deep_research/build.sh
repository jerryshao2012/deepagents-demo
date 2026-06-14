#!/bin/bash
set -e

# Timer tracking
TOTAL_START_TIME=$(date +%s)
STEP_TIMES=()

# Function to track step timing
start_step() {
  STEP_NAME="$1"
  STEP_START=$(date +%s)
  echo "⏱️  Starting: $STEP_NAME"
}

end_step() {
  STEP_END=$(date +%s)
  DURATION=$((STEP_END - STEP_START))
  STEP_TIMES+=("$STEP_NAME: ${DURATION}s")
  echo "✅ Completed: $STEP_NAME (${DURATION}s)"
  echo ""
}

print_timing_summary() {
  TOTAL_END=$(date +%s)
  TOTAL_DURATION=$((TOTAL_END - TOTAL_START_TIME))
  echo ""
  echo "═══════════════════════════════════════════════════════"
  echo "⏱️  Build Timing Summary"
  echo "═══════════════════════════════════════════════════════"
  for timing in "${STEP_TIMES[@]}"; do
    echo "   • $timing"
  done
  echo "───────────────────────────────────────────────────────"
  echo "   Total build time: ${TOTAL_DURATION}s"
  echo "═══════════════════════════════════════════════════════"
}

# Configuration
source ./env.sh

echo "🚀 Starting Deep Research Agent build..."

# 1. Set Azure Subscription
start_step "Set Azure Subscription"
AZURE_SUBSCRIPTION_ID="66fadccd-d26d-4dd0-b108-46b3c581cdb3"
az account set --subscription $AZURE_SUBSCRIPTION_ID
echo "✅ Subscription set to $AZURE_SUBSCRIPTION_ID"
end_step

# 2. Create resource group
start_step "Resource Group Setup"
if az group show --name $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Resource group '$RESOURCE_GROUP' already exists. Skipping creation."
else
  az group create --name $RESOURCE_GROUP --location $LOCATION
fi
end_step

# 3. Azure Provider Registration
start_step "Azure Provider Registration"
echo "📝 Registering required Azure providers..."
az provider register -n Microsoft.OperationalInsights --wait
az provider register -n Microsoft.App --wait
az provider register -n Microsoft.KeyVault --wait
az provider register -n Microsoft.Storage --wait
az provider register -n Microsoft.ManagedIdentity --wait
echo "✅ Providers registered."
end_step

# 4. Create ACR
start_step "Container Registry Setup"
if az acr show --name $ACR_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Container Registry '$ACR_NAME' already exists. Skipping creation."
else
  az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Standard --admin-enabled true
fi
end_step

# 5. Increment API version
start_step "API Version Management"
echo "🔢 Incrementing API version..."
python3 ./increment_version.py
NEW_VERSION=$(grep 'API_VERSION = ' webapp.py | grep -o '"[^"]*"' | tr -d '"')
echo "✅ New API version: $NEW_VERSION"
end_step

# 6. Build and push image
start_step "Docker Image Build & Push"
echo "🔨 Building Docker image..."
# Ensure we're in the correct directory (where Dockerfile is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
docker build --platform linux/amd64 -t $ACR_NAME.azurecr.io/deep-research-agent:latest .
az acr login --name $ACR_NAME
docker push $ACR_NAME.azurecr.io/deep-research-agent:latest
echo "✅ Image built and pushed successfully"
end_step

print_timing_summary
