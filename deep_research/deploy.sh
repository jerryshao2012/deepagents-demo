#!/bin/bash
set -e

# Configuration
source ./env.sh

echo "🚀 Starting Deep Research Agent deployment..."

# 1. Create resource group
echo "📦 Creating resource group..."
if az group show --name $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Resource group '$RESOURCE_GROUP' already exists. Skipping creation."
else
  az group create --name $RESOURCE_GROUP --location $LOCATION
fi

# 2. Create ACR
echo "🐳 Creating Container Registry..."
if az acr show --name $ACR_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Container Registry '$ACR_NAME' already exists. Skipping creation."
else
  az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Standard --admin-enabled true
fi

# 3. Build and push image
echo "🔨 Building Docker image..."
# Ensure we're in the correct directory (where Dockerfile is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
docker build --platform linux/amd64 -t $ACR_NAME.azurecr.io/deep-research-agent:latest .
az acr login --name $ACR_NAME
docker push $ACR_NAME.azurecr.io/deep-research-agent:latest

# 4. Create environment
echo "🌍 Creating Container Apps environment..."
if az containerapp env show --name $ENV_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Container Apps environment '$ENV_NAME' already exists. Skipping creation."
else
  az containerapp env create \
    --name $ENV_NAME \
    --resource-group $RESOURCE_GROUP \
    --location $LOCATION
fi

# 5. Create Key Vault and store secrets
echo "🔐 Setting up Key Vault..."
if az keyvault show --name $KV_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Key Vault '$KV_NAME' already exists. Skipping creation."
else
  az keyvault create --name $KV_NAME --resource-group $RESOURCE_GROUP --location $LOCATION
fi
# Add your secrets here

# 6. Deploy or update agent
echo "🚀 Deploying agent..."

# Check if container app already exists
if az containerapp show --name $AGENT_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
  echo "📝 Container app already exists. Updating with new image..."
  
  # Update the container app with the new image
  az containerapp update \
    --name $AGENT_NAME \
    --resource-group $RESOURCE_GROUP \
    --image $ACR_NAME.azurecr.io/deep-research-agent:latest
  
  # Restart the container to pick up the new image
  echo "🔄 Restarting container to apply new image..."
  az containerapp update \
    --name $AGENT_NAME \
    --resource-group $RESOURCE_GROUP \
    --set-env-vars RESTART_TRIGGER="$(date +%s)"
else
  echo "✨ Creating new container app..."
  az containerapp create \
    --name $AGENT_NAME \
    --resource-group $RESOURCE_GROUP \
    --environment $ENV_NAME \
    --image $ACR_NAME.azurecr.io/deep-research-agent:latest \
    --registry-server $ACR_NAME.azurecr.io \
    --target-port 2024 \
    --ingress internal \
    --min-replicas 1 \
    --max-replicas 3 \
    --cpu 2.0 \
    --memory 4Gi
fi

echo "✅ Deployment complete!"
# Get the external FQDN
EXTERNAL_URL=$(az containerapp show --name $AGENT_NAME --resource-group $RESOURCE_GROUP --query properties.configuration.ingress.fqdn -o tsv)
echo "Agent FQDN: $EXTERNAL_URL"

# Test health endpoint
echo "Access: https://$EXTERNAL_URL/health"
curl -s "https://$EXTERNAL_URL/health" | head -10