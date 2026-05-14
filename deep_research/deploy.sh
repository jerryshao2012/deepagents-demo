#!/bin/bash
set -e

# Parse command-line arguments
SYNC_FILES=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --sync-files)
      SYNC_FILES=true
      shift
      ;;
    --help|-h)
      echo "Usage: ./deploy.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --sync-files    Sync local files (docs/, output/, input/) to Azure File Share"
      echo "  --help, -h      Show this help message"
      echo ""
      echo "Examples:"
      echo "  ./deploy.sh                  # Deploy without syncing local files"
      echo "  ./deploy.sh --sync-files     # Deploy and sync local files"
      echo ""
      echo "Note: For manual file sync after deployment, use:"
      echo "  ./sync-files.sh"
      exit 0
      ;;
    *)
      echo "❌ Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Configuration
source ./env.sh

echo "🚀 Starting Deep Research Agent deployment with persistent storage..."

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

# 3. Increment API version
echo "🔢 Incrementing API version..."
python3 ./increment_version.py
NEW_VERSION=$(grep 'API_VERSION = ' webapp.py | grep -o '"[^"]*"' | tr -d '"')
echo "✅ New API version: $NEW_VERSION"

# 4. Build and push image
echo "🔨 Building Docker image..."
# Ensure we're in the correct directory (where Dockerfile is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
docker build --platform linux/amd64 -t $ACR_NAME.azurecr.io/deep-research-agent:latest .
az acr login --name $ACR_NAME
docker push $ACR_NAME.azurecr.io/deep-research-agent:latest

# 5. Create environment
echo "🌍 Creating Container Apps environment..."
if az containerapp env show --name $ENV_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Container Apps environment '$ENV_NAME' already exists. Skipping creation."
else
  az containerapp env create \
    --name $ENV_NAME \
    --resource-group $RESOURCE_GROUP \
    --location $LOCATION
fi

# 6. Create Key Vault and store secrets
echo "🔐 Setting up Key Vault..."
if az keyvault show --name $KV_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Key Vault '$KV_NAME' already exists. Skipping creation."
else
  az keyvault create --name $KV_NAME --resource-group $RESOURCE_GROUP --location $LOCATION
fi

# Store secrets in Key Vault
echo "🔑 Storing secrets in Key Vault..."
az keyvault secret set --vault-name $KV_NAME --name TAVILY-API-KEY --value "${TAVILY_API_KEY:-placeholder}" --only-show-errors || true
az keyvault secret set --vault-name $KV_NAME --name LANGCHAIN-API-KEY --value "${LANGCHAIN_API_KEY:-placeholder}" --only-show-errors || true
az keyvault secret set --vault-name $KV_NAME --name AZURE-OPENAI-ENDPOINT --value "${AZURE_OPENAI_ENDPOINT:-placeholder}" --only-show-errors || true
az keyvault secret set --vault-name $KV_NAME --name AZURE-OPENAI-DEPLOYMENT --value "${AZURE_OPENAI_DEPLOYMENT:-placeholder}" --only-show-errors || true
az keyvault secret set --vault-name $KV_NAME --name AZURE-OPENAI-API-KEY --value "${AZURE_OPENAI_API_KEY:-placeholder}" --only-show-errors || true
az keyvault secret set --vault-name $KV_NAME --name UPLOAD-API-KEY --value "${UPLOAD_API_KEY:-placeholder}" --only-show-errors || true
echo "✅ Secrets stored in Key Vault"

# 7. Setup Persistent Storage
echo ""
echo "📦 Setting up Azure Files persistent storage..."

# Check if storage account already exists
STORAGE_ACCOUNT_NAME="stdeepagents"
FILE_SHARE_NAME="deep-research-files"
MOUNT_PATH="/deps/deep_research/mnt"

# Try to find existing storage account with our naming pattern
EXISTING_STORAGE=$(az storage account list \
  --resource-group $RESOURCE_GROUP \
  --query "[?starts_with(name, 'stdeepagents')].name" \
  -o tsv 2>/dev/null || echo "")

if [ -n "$EXISTING_STORAGE" ]; then
  echo "✅ Found existing storage account: $EXISTING_STORAGE"
  STORAGE_ACCOUNT_NAME=$EXISTING_STORAGE
  
  # Get storage key
  STORAGE_KEY=$(az storage account keys list \
    --account-name $STORAGE_ACCOUNT_NAME \
    --resource-group $RESOURCE_GROUP \
    --query '[0].value' -o tsv)
  
  # Check if file share exists
  EXISTING_SHARE=$(az storage share list \
    --account-name $STORAGE_ACCOUNT_NAME \
    --account-key $STORAGE_KEY \
    --query "[?name=='$FILE_SHARE_NAME'].name" \
    -o tsv 2>/dev/null || echo "")
  
  if [ -n "$EXISTING_SHARE" ]; then
    echo "✅ File share '$FILE_SHARE_NAME' already exists. Skipping creation."
  else
    echo "📁 Creating File Share: $FILE_SHARE_NAME (100GB quota)"
    az storage share create \
      --name $FILE_SHARE_NAME \
      --account-name $STORAGE_ACCOUNT_NAME \
      --account-key $STORAGE_KEY \
      --quota 100
  fi
else
  # Create new storage account
  echo "🗄️  Creating Storage Account: $STORAGE_ACCOUNT_NAME"
  az storage account create \
    --name $STORAGE_ACCOUNT_NAME \
    --resource-group $RESOURCE_GROUP \
    --location $LOCATION \
    --sku Standard_LRS \
    --kind StorageV2 \
    --allow-blob-public-access false
  
  # Get storage key
  STORAGE_KEY=$(az storage account keys list \
    --account-name $STORAGE_ACCOUNT_NAME \
    --resource-group $RESOURCE_GROUP \
    --query '[0].value' -o tsv)
  
  # Create File Share
  echo "📁 Creating File Share: $FILE_SHARE_NAME (100GB quota)"
  az storage share create \
    --name $FILE_SHARE_NAME \
    --account-name $STORAGE_ACCOUNT_NAME \
    --account-key $STORAGE_KEY \
    --quota 100
fi

# Check and create directory structure
echo "📂 Checking directory structure..."
for dir in "docs" "docs/policy" "output" "output/eval_history" "input" ".langgraph_api"; do
  EXISTING_DIR=$(az storage directory exists \
    --share-name $FILE_SHARE_NAME \
    --path "$dir" \
    --account-name $STORAGE_ACCOUNT_NAME \
    --account-key $STORAGE_KEY \
    --query "exists" \
    -o tsv 2>/dev/null || echo "false")
  
  if [ "$EXISTING_DIR" = "true" ]; then
    echo "  ✓ Directory '$dir' exists"
  else
    echo "  + Creating directory '$dir'"
    az storage directory create \
      --share-name $FILE_SHARE_NAME \
      --name "$dir" \
      --account-name $STORAGE_ACCOUNT_NAME \
      --account-key $STORAGE_KEY
  fi
done

# Sync local files to Azure File Share (if enabled and directories exist)
if [ "$SYNC_FILES" = true ]; then
  echo "🔄 Syncing local files to Azure File Share..."
  if [ -d "docs" ]; then
    echo "   Uploading docs/ directory..."
    az storage file upload-batch \
      --source docs \
      --destination docs \
      --account-name $STORAGE_ACCOUNT_NAME \
      --account-key $STORAGE_KEY \
      --share-name $FILE_SHARE_NAME \
      --overwrite 2>/dev/null || echo "   ⚠️  No files to upload in docs/"
  fi

  if [ -d "output" ]; then
    echo "   Uploading output/ directory..."
    az storage file upload-batch \
      --source output \
      --destination output \
      --account-name $STORAGE_ACCOUNT_NAME \
      --account-key $STORAGE_KEY \
      --share-name $FILE_SHARE_NAME \
      --overwrite 2>/dev/null || echo "   ⚠️  No files to upload in output/"
  fi

  if [ -d "input" ]; then
    echo "   Uploading input/ directory..."
    az storage file upload-batch \
      --source input \
      --destination input \
      --account-name $STORAGE_ACCOUNT_NAME \
      --account-key $STORAGE_KEY \
      --share-name $FILE_SHARE_NAME \
      --overwrite 2>/dev/null || echo "   ⚠️  No files to upload in input/"
  fi

  echo "✅ File sync complete"
else
  echo "💡 Tip: Use --sync-files flag to upload local files to Azure File Share"
  echo "   Or use ./sync-files.sh for manual sync after deployment"
fi

# Store storage credentials in Key Vault
echo "🔐 Storing storage credentials in Key Vault..."
az keyvault secret set --vault-name $KV_NAME --name STORAGE-ACCOUNT-NAME --value $STORAGE_ACCOUNT_NAME
az keyvault secret set --vault-name $KV_NAME --name STORAGE-ACCOUNT-KEY --value $STORAGE_KEY
az keyvault secret set --vault-name $KV_NAME --name FILE-SHARE-NAME --value $FILE_SHARE_NAME

echo "✅ Persistent storage setup complete"

# 8. Deploy or update agent
echo "🚀 Deploying agent..."

# Prepare environment variables with persistent storage paths
ENV_VARS=(
  VERIFY_SSL=false
  LOG_LEVEL=INFO
  LANGCHAIN_TRACING_V2=true
  LANGSMITH_ENDPOINT=https://api.smith.langchain.com
  LANGCHAIN_PROJECT=deep-research-production
  ENABLE_EVAL_TRACKING=true
  MODEL_TPM=120000
  MODEL_RPM=500
  GRAPH_RECURSION_LIMIT=200
  MAX_CONCURRENT_RESEARCH_UNITS=3
  MAX_RESEARCHER_ITERATIONS=3
  MAX_GLOB_DEPTH=3
  MAX_FILES_TO_READ=20
  MAX_TOTAL_SIZE_MB=50
  MODEL_MAX_RETRIES=5
  MODEL_INITIAL_BACKOFF=1.0
  MODEL_MAX_BACKOFF=60.0
  MODEL_BACKOFF_MULTIPLIER=2.0
  MODEL_RETRY_JITTER=true
  AZURE_OPENAI_API_VERSION=2025-04-01-preview
  MEMORY_TYPE=cosmosdb
  COSMOSDB_DB_NAME=deep-research-checkpoints
  COSMOSDB_CONTAINER_NAME=checkpoints
  REPORTS_OUTPUT_FOLDER=$MOUNT_PATH/output
  EVAL_HISTORY_FILE=$MOUNT_PATH/output/eval_history/server_runs.jsonl
  DOC_FOLDER=$MOUNT_PATH/docs
  INPUT_FOLDER=$MOUNT_PATH/input
)

# Build env-vars string for az CLI
ENV_VARS_STRING=""
for var in "${ENV_VARS[@]}"; do
  if [ -z "$ENV_VARS_STRING" ]; then
    ENV_VARS_STRING="$var"
  else
    ENV_VARS_STRING="$ENV_VARS_STRING $var"
  fi
done

# Register storage at the Container Apps Environment level (idempotent)
echo "📎 Registering Azure File Share storage with Container Apps environment..."
az containerapp env storage set \
  --name $ENV_NAME \
  --resource-group $RESOURCE_GROUP \
  --storage-name azure-file-storage \
  --azure-file-account-name $STORAGE_ACCOUNT_NAME \
  --azure-file-account-key "$STORAGE_KEY" \
  --azure-file-share-name $FILE_SHARE_NAME \
  --access-mode ReadWrite \
  --only-show-errors || echo "⚠️  Storage registration may already exist, continuing..."
echo "✅ Environment storage registered"

# Check if container app already exists
if az containerapp show --name $AGENT_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
  echo "📝 Container app already exists. Updating..."
    
  # Update image and environment variables
  echo "⚙️  Updating image and environment variables..."
  az containerapp update \
    --name $AGENT_NAME \
    --resource-group $RESOURCE_GROUP \
    --image $ACR_NAME.azurecr.io/deep-research-agent:latest \
    --set-env-vars $ENV_VARS_STRING RESTART_TRIGGER="$(date +%s)" \
    --remove-env-vars \
      properties.configuration.secrets \
      properties.configuration.ingress.external \
      properties.configuration.ingress.targetPort \
      properties.configuration.ingress.transport \
      properties.template.storages \
    2>/dev/null || true

  # Configure persistent storage volume mount using YAML
  # (--set is hijacked by the containerapp extension and cannot be used for ARM paths)
  echo "📎 Configuring persistent storage volume mount via YAML..."
  VOLUME_YAML=$(mktemp /tmp/volume-config-XXXXXX.yaml)
  cat > "$VOLUME_YAML" <<EOF
properties:
  template:
    volumes:
      - name: persistent-storage
        storageName: azure-file-storage
        storageType: AzureFile
    containers:
      - name: deep-research-agent
        image: $ACR_NAME.azurecr.io/deep-research-agent:latest
        resources:
          cpu: 2.0
          memory: 4Gi
        volumeMounts:
          - volumeName: persistent-storage
            mountPath: $MOUNT_PATH
EOF
  az containerapp update \
    --name $AGENT_NAME \
    --resource-group $RESOURCE_GROUP \
    --yaml "$VOLUME_YAML"
  rm -f "$VOLUME_YAML"

  echo "🔄 Container updated with persistent storage volume mount."
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
    --transport auto \
    --min-replicas 1 \
    --max-replicas 5 \
    --cpu 2.0 \
    --memory 4Gi \
    --env-vars $ENV_VARS_STRING

  # Add volume mount after creation using YAML
  echo "📎 Configuring persistent storage volume mount via YAML..."
  VOLUME_YAML=$(mktemp /tmp/volume-config-XXXXXX.yaml)
  cat > "$VOLUME_YAML" <<EOF
properties:
  template:
    volumes:
      - name: persistent-storage
        storageName: azure-file-storage
        storageType: AzureFile
    containers:
      - name: deep-research-agent
        image: $ACR_NAME.azurecr.io/deep-research-agent:latest
        resources:
          cpu: 2.0
          memory: 4Gi
        volumeMounts:
          - volumeName: persistent-storage
            mountPath: $MOUNT_PATH
EOF
  az containerapp update \
    --name $AGENT_NAME \
    --resource-group $RESOURCE_GROUP \
    --yaml "$VOLUME_YAML"
  rm -f "$VOLUME_YAML"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "✅ Deployment Complete!"
echo "═══════════════════════════════════════════════════════"

# Get the FQDN
EXTERNAL_URL=$(az containerapp show --name $AGENT_NAME --resource-group $RESOURCE_GROUP --query properties.configuration.ingress.fqdn -o tsv)
echo "🌐 Agent URL: https://$EXTERNAL_URL"
echo "🏥 Health Check: https://$EXTERNAL_URL/health"
echo ""
echo "💾 Persistent Storage Configuration:"
echo "   • Storage Account: $STORAGE_ACCOUNT_NAME"
echo "   • File Share: $FILE_SHARE_NAME"
echo "   • Mount Path: $MOUNT_PATH"
echo "   • docs/ → $MOUNT_PATH/docs/"
echo "   • output/ → $MOUNT_PATH/output/"
echo "   • input/ → $MOUNT_PATH/input/"
echo "   • .langgraph_api/ → $MOUNT_PATH/.langgraph_api/"
echo ""
echo "🧪 Verify Persistence:"
echo "   az containerapp exec --name $AGENT_NAME --resource-group $RESOURCE_GROUP --command '/bin/sh'"
echo "   # Inside container: ls -la $MOUNT_PATH/"
echo ""
echo "📊 Next Steps:"
echo "   • Test API: curl -s https://$EXTERNAL_URL/health"
echo "   • View logs: az containerapp logs show --name $AGENT_NAME --resource-group $RESOURCE_GROUP --tail 50"
echo "   • Monitor: https://portal.azure.com/#@/resource/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/overview"
echo "═══════════════════════════════════════════════════════"

# Test health endpoint with version verification
echo ""
echo "🔍 Testing health endpoint (waiting for container to start)..."

MAX_RETRIES=30
RETRY_INTERVAL=10
VERSION_MATCHED=false

for i in $(seq 1 $MAX_RETRIES); do
  echo -n "   Attempt $i/$MAX_RETRIES... "
  
  HEALTH_RESPONSE=$(curl -s --max-time 5 "https://$EXTERNAL_URL/health" 2>/dev/null || echo "")
  
  if [ -z "$HEALTH_RESPONSE" ]; then
    echo "❌ No response (container may still be starting)"
  else
    # Extract version from response
    RESPONSE_VERSION=$(echo "$HEALTH_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('version', ''))" 2>/dev/null || echo "")
    
    if [ "$RESPONSE_VERSION" = "$NEW_VERSION" ]; then
      echo "✅ Version $RESPONSE_VERSION matched!"
      VERSION_MATCHED=true
      echo ""
      echo "📊 Health Check Response:"
      echo "$HEALTH_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$HEALTH_RESPONSE"
      break
    else
      echo "⚠️  Version mismatch (expected: $NEW_VERSION, got: ${RESPONSE_VERSION:-unknown})"
    fi
  fi
  
  if [ $i -lt $MAX_RETRIES ]; then
    echo "   Waiting ${RETRY_INTERVAL}s before next attempt..."
    sleep $RETRY_INTERVAL
  fi
done

if [ "$VERSION_MATCHED" = false ]; then
  echo ""
  echo "⚠️  WARNING: Container started but version mismatch detected!"
  echo "   Expected version: $NEW_VERSION"
  echo "   The container may still be deploying or using an old image."
  echo "   Check deployment status: az containerapp revision list --name $AGENT_NAME --resource-group $RESOURCE_GROUP"
else
  echo ""
  echo "✅ Deployment verified successfully!"
fi