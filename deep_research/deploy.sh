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
  echo "⏱️  Deployment Timing Summary"
  echo "═══════════════════════════════════════════════════════"
  for timing in "${STEP_TIMES[@]}"; do
    echo "   • $timing"
  done
  echo "───────────────────────────────────────────────────────"
  echo "   Total deployment time: ${TOTAL_DURATION}s"
  echo "═══════════════════════════════════════════════════════"
}

# Parse command-line arguments
SYNC_FILES=false
SKIP_BUILD=false
SKIP_KV_ACCESS=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --sync-files)
      SYNC_FILES=true
      shift
      ;;
    --skip-build)
      SKIP_BUILD=true
      shift
      ;;
    --skip-kv-access)
      SKIP_KV_ACCESS=true
      shift
      ;;
    --help|-h)
      echo "Usage: ./deploy.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --sync-files     Sync local files (docs/, output/, input/) to Azure File Share"
      echo "  --skip-build     Skip Docker build and use existing image in ACR"
      echo "  --skip-kv-access Skip Key Vault access policy updates (faster re-deployment)"
      echo "  --help, -h       Show this help message"
      echo ""
      echo "Examples:"
      echo "  ./deploy.sh                                    # Full deployment with build"
      echo "  ./deploy.sh --sync-files                       # Deploy with build and sync files"
      echo "  ./deploy.sh --skip-build                       # Deploy existing image without rebuild"
      echo "  ./deploy.sh --skip-build --sync-files          # Deploy existing image and sync files"
      echo "  ./deploy.sh --skip-build --skip-kv-access      # Fast re-deployment (no build, no KV access check)"
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

if [ "$SKIP_BUILD" = true ]; then
  echo "🚀 Starting Deep Research Agent deployment (using existing image)..."
else
  echo "🚀 Starting Deep Research Agent deployment with persistent storage..."
fi

# 1. Create resource group
start_step "Resource Group Setup"
if az group show --name $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Resource group '$RESOURCE_GROUP' already exists. Skipping creation."
else
  az group create --name $RESOURCE_GROUP --location $LOCATION
fi
end_step

# 2. Create ACR
start_step "Container Registry Setup"
if az acr show --name $ACR_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Container Registry '$ACR_NAME' already exists. Skipping creation."
else
  az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Standard --admin-enabled true
fi
end_step

# 3. Increment API version (only if building)
start_step "API Version Management"
if [ "$SKIP_BUILD" = false ]; then
  echo "🔢 Incrementing API version..."
  python3 ./increment_version.py
  NEW_VERSION=$(grep 'API_VERSION = ' webapp.py | grep -o '"[^"]*"' | tr -d '"')
  echo "✅ New API version: $NEW_VERSION"
else
  echo "⏭️  Skipping API version increment (--skip-build)"
  NEW_VERSION=$(grep 'API_VERSION = ' webapp.py | grep -o '"[^"]*"' | tr -d '"')
  echo "ℹ️  Current API version: $NEW_VERSION"
fi
end_step

# 4. Build and push image (optional)
start_step "Docker Image Build & Push"
if [ "$SKIP_BUILD" = false ]; then
  echo "🔨 Building Docker image..."
  # Ensure we're in the correct directory (where Dockerfile is located)
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$SCRIPT_DIR"
  docker build --platform linux/amd64 -t $ACR_NAME.azurecr.io/deep-research-agent:latest .
  az acr login --name $ACR_NAME
  docker push $ACR_NAME.azurecr.io/deep-research-agent:latest
  echo "✅ Image built and pushed successfully"
else
  echo "⏭️  Skipping Docker build (--skip-build)"
  echo "ℹ️  Using existing image: $ACR_NAME.azurecr.io/deep-research-agent:latest"
  
  # Verify image exists in ACR
  if ! az acr repository show-tags --name $ACR_NAME --repository deep-research-agent --query "contains(@, 'latest')" -o tsv 2>/dev/null | grep -q "true"; then
    echo "⚠️  WARNING: Image 'deep-research-agent:latest' not found in ACR!"
    echo "   Please run './deploy.sh' without --skip-build first to build and push the image."
    exit 1
  fi
  echo "✅ Verified image exists in ACR"
fi
end_step

# 5. Create environment
start_step "Container Apps Environment Setup"
if az containerapp env show --name $ENV_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Container Apps environment '$ENV_NAME' already exists. Skipping creation."
else
  az containerapp env create \
    --name $ENV_NAME \
    --resource-group $RESOURCE_GROUP \
    --location $LOCATION
fi
end_step

# 6. Create Key Vault and store secrets
start_step "Key Vault Setup & Secrets"
if az keyvault show --name $KV_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
  echo "✅ Key Vault '$KV_NAME' already exists. Skipping creation."
else
  az keyvault create --name $KV_NAME --resource-group $RESOURCE_GROUP --location $LOCATION
fi

# Enable RBAC authorization for Key Vault (if possible)
echo "🔑 Ensuring Key Vault access configuration..."
# Try to enable RBAC, but don't fail if it's already set or if we lack permissions
az keyvault update --name $KV_NAME --resource-group $RESOURCE_GROUP --enable-rbac-authorization true 2>/dev/null || true

# Store secrets in Key Vault (only if local values are set - avoids overwriting with 'placeholder')
# Run ./secrets.sh separately to seed real values into Key Vault
echo "🔑 Storing secrets in Key Vault (skipping secrets without local values)..."
SECRETS_UPDATED=0
if [ -n "${TAVILY_API_KEY:-}" ]; then
  az keyvault secret set --vault-name $KV_NAME --name TAVILY-API-KEY --value "$TAVILY_API_KEY" --only-show-errors || true
  echo "  ✓ TAVILY-API-KEY updated"
  SECRETS_UPDATED=$((SECRETS_UPDATED + 1))
else
  echo "  ⏭️  TAVILY_API_KEY not set locally - keeping existing KV value"
fi
if [ -n "${LANGCHAIN_API_KEY:-}" ]; then
  az keyvault secret set --vault-name $KV_NAME --name LANGCHAIN-API-KEY --value "$LANGCHAIN_API_KEY" --only-show-errors || true
  echo "  ✓ LANGCHAIN-API-KEY updated"
  SECRETS_UPDATED=$((SECRETS_UPDATED + 1))
else
  echo "  ⏭️  LANGCHAIN_API_KEY not set locally - keeping existing KV value"
fi
if [ -n "${AZURE_OPENAI_ENDPOINT:-}" ]; then
  az keyvault secret set --vault-name $KV_NAME --name AZURE-OPENAI-ENDPOINT --value "$AZURE_OPENAI_ENDPOINT" --only-show-errors || true
  echo "  ✓ AZURE-OPENAI-ENDPOINT updated"
  SECRETS_UPDATED=$((SECRETS_UPDATED + 1))
else
  echo "  ⏭️  AZURE_OPENAI_ENDPOINT not set locally - keeping existing KV value"
fi
if [ -n "${AZURE_OPENAI_DEPLOYMENT:-}" ]; then
  az keyvault secret set --vault-name $KV_NAME --name AZURE-OPENAI-DEPLOYMENT --value "$AZURE_OPENAI_DEPLOYMENT" --only-show-errors || true
  echo "  ✓ AZURE-OPENAI-DEPLOYMENT updated"
  SECRETS_UPDATED=$((SECRETS_UPDATED + 1))
else
  echo "  ⏭️  AZURE_OPENAI_DEPLOYMENT not set locally - keeping existing KV value"
fi
if [ -n "${AZURE_OPENAI_API_KEY:-}" ]; then
  az keyvault secret set --vault-name $KV_NAME --name AZURE-OPENAI-API-KEY --value "$AZURE_OPENAI_API_KEY" --only-show-errors || true
  echo "  ✓ AZURE-OPENAI-API-KEY updated"
  SECRETS_UPDATED=$((SECRETS_UPDATED + 1))
else
  echo "  ⏭️  AZURE_OPENAI_API_KEY not set locally - keeping existing KV value"
fi
if [ -n "${UPLOAD_API_KEY:-}" ]; then
  az keyvault secret set --vault-name $KV_NAME --name UPLOAD-API-KEY --value "$UPLOAD_API_KEY" --only-show-errors || true
  echo "  ✓ UPLOAD-API-KEY updated"
  SECRETS_UPDATED=$((SECRETS_UPDATED + 1))
else
  echo "  ⏭️  UPLOAD_API_KEY not set locally - keeping existing KV value"
fi
if [ $SECRETS_UPDATED -gt 0 ]; then
  echo "✅ Key Vault secret update complete ($SECRETS_UPDATED secrets updated)"
else
  echo "✅ No secrets updated (all using existing KV values)"
fi
echo "💡 Tip: Run ./secrets.sh to update all API keys in Key Vault"
end_step

# 7. Setup Persistent Storage
start_step "Persistent Storage Setup"
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
end_step

# 8. Deploy or update agent
start_step "Container App Deployment"
echo "🚀 Deploying agent..."

# Prepare environment variables with persistent storage paths
# Note: Sensitive values will be injected via Key Vault secret references
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
    
  # 8a. Ensure managed identity exists and has permissions (skip if --skip-kv-access)
  if [ "$SKIP_KV_ACCESS" = false ]; then
    echo "🔐 Ensuring managed identity and permissions..."
    
    # Enable SystemAssigned identity if not already enabled
    az containerapp identity assign \
      --name $AGENT_NAME \
      --resource-group $RESOURCE_GROUP \
      --system-assigned \
      --only-show-errors > /dev/null
      
    # Get the principal ID
    PRINCIPAL_ID=$(az containerapp show \
      --name $AGENT_NAME \
      --resource-group $RESOURCE_GROUP \
      --query "identity.principalId" \
      -o tsv)
      
    if [ -n "$PRINCIPAL_ID" ]; then
      # Function to grant Key Vault access to an identity (optimized with skip check)
      echo "🔐 Ensuring identity '$PRINCIPAL_ID' has access to Key Vault '$KV_NAME'..."
      
      # Check if RBAC is enabled
      RBAC_ENABLED=$(az keyvault show --name "$KV_NAME" --query "properties.enableRbacAuthorization" -o tsv 2>/dev/null || echo "false")
      
      if [ "$RBAC_ENABLED" = "true" ]; then
        echo "   Using RBAC for authorization..."
        KV_ID=$(az keyvault show --name "$KV_NAME" --query id -o tsv)
        # Check if role assignment already exists
        EXISTING_ROLE=$(az role assignment list \
          --assignee "$PRINCIPAL_ID" \
          --scope "$KV_ID" \
          --role "Key Vault Secrets User" \
          --query "length(@)" -o tsv 2>/dev/null || echo "0")
        
        if [ "$EXISTING_ROLE" = "0" ]; then
          az role assignment create \
            --role "Key Vault Secrets User" \
            --assignee-object-id "$PRINCIPAL_ID" \
            --scope "$KV_ID" \
            --assignee-principal-type ServicePrincipal \
            2>/dev/null || echo "   ✓ Role assignment completed"
        else
          echo "   ✓ RBAC role already assigned, skipping"
        fi
      else
        echo "   Using Access Policies for authorization..."
        # Access policies don't have easy skip check, so we'll just set it
        az keyvault set-policy \
          --name "$KV_NAME" \
          --secret-permissions get list \
          --object-id "$PRINCIPAL_ID" \
          --only-show-errors 2>/dev/null || echo "   ⚠️  Could not set access policy. Ensure you have permissions."
      fi
    else
      echo "⚠️  Could not find principal ID for managed identity."
    fi
  else
    echo "⏭️  Skipping Key Vault access check (--skip-kv-access)"
  fi

  # Update image, secrets, env vars, and volume mounts in a single YAML update
  # (Multiple separate az containerapp update calls overwrite each other's env arrays)
  echo "⚙️  Applying comprehensive configuration update..."
  UPDATE_YAML=$(mktemp /tmp/update-config-XXXXXX.yaml 2>/dev/null || mktemp)
  RESTART_TRIGGER=$(date +%s)
  cat > "$UPDATE_YAML" <<EOF
properties:
  configuration:
    secrets:
      - name: tavily-api-key
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/TAVILY-API-KEY
        identity: system
      - name: langchain-api-key
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/LANGCHAIN-API-KEY
        identity: system
      - name: azure-openai-endpoint
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/AZURE-OPENAI-ENDPOINT
        identity: system
      - name: azure-openai-deployment
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/AZURE-OPENAI-DEPLOYMENT
        identity: system
      - name: azure-openai-api-key
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/AZURE-OPENAI-API-KEY
        identity: system
      - name: upload-api-key
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/UPLOAD-API-KEY
        identity: system
      - name: storage-account-name
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/STORAGE-ACCOUNT-NAME
        identity: system
      - name: storage-account-key
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/STORAGE-ACCOUNT-KEY
        identity: system
      - name: file-share-name
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/FILE-SHARE-NAME
        identity: system
      - name: acr-password
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/ACR-PASSWORD
        identity: system
    registries:
      - server: ${ACR_NAME}.azurecr.io
        username: ${ACR_NAME}
        passwordSecretRef: acr-password
  template:
    volumes:
      - name: persistent-storage
        storageName: azure-file-storage
        storageType: AzureFile
    containers:
      - name: deep-research-agent
        image: ${ACR_NAME}.azurecr.io/deep-research-agent:latest
        resources:
          cpu: 2.0
          memory: 4Gi
        env:
          - name: RESTART_TRIGGER
            value: "${RESTART_TRIGGER}"
          - name: VERIFY_SSL
            value: "false"
          - name: LOG_LEVEL
            value: INFO
          - name: LANGCHAIN_TRACING_V2
            value: "true"
          - name: LANGSMITH_ENDPOINT
            value: https://api.smith.langchain.com
          - name: LANGCHAIN_PROJECT
            value: deep-research-production
          - name: ENABLE_EVAL_TRACKING
            value: "true"
          - name: MODEL_TPM
            value: "120000"
          - name: MODEL_RPM
            value: "500"
          - name: GRAPH_RECURSION_LIMIT
            value: "200"
          - name: MAX_CONCURRENT_RESEARCH_UNITS
            value: "3"
          - name: MAX_RESEARCHER_ITERATIONS
            value: "3"
          - name: MAX_GLOB_DEPTH
            value: "3"
          - name: MAX_FILES_TO_READ
            value: "20"
          - name: MAX_TOTAL_SIZE_MB
            value: "50"
          - name: MODEL_MAX_RETRIES
            value: "5"
          - name: MODEL_INITIAL_BACKOFF
            value: "1.0"
          - name: MODEL_MAX_BACKOFF
            value: "60.0"
          - name: MODEL_BACKOFF_MULTIPLIER
            value: "2.0"
          - name: MODEL_RETRY_JITTER
            value: "true"
          - name: AZURE_OPENAI_API_VERSION
            value: 2025-04-01-preview
          - name: MEMORY_TYPE
            value: cosmosdb
          - name: COSMOSDB_DB_NAME
            value: deep-research-checkpoints
          - name: COSMOSDB_CONTAINER_NAME
            value: checkpoints
          - name: REPORTS_OUTPUT_FOLDER
            value: ${MOUNT_PATH}/output
          - name: EVAL_HISTORY_FILE
            value: ${MOUNT_PATH}/output/eval_history/server_runs.jsonl
          - name: DOC_FOLDER
            value: ${MOUNT_PATH}/docs
          - name: INPUT_FOLDER
            value: ${MOUNT_PATH}/input
          - name: TAVILY_API_KEY
            secretRef: tavily-api-key
          - name: LANGCHAIN_API_KEY
            secretRef: langchain-api-key
          - name: AZURE_OPENAI_ENDPOINT
            secretRef: azure-openai-endpoint
          - name: AZURE_OPENAI_DEPLOYMENT
            secretRef: azure-openai-deployment
          - name: AZURE_OPENAI_API_KEY
            secretRef: azure-openai-api-key
          - name: UPLOAD_API_KEY
            secretRef: upload-api-key
          - name: STORAGE_ACCOUNT_NAME
            secretRef: storage-account-name
          - name: STORAGE_ACCOUNT_KEY
            secretRef: storage-account-key
          - name: FILE_SHARE_NAME
            secretRef: file-share-name
        volumeMounts:
          - volumeName: persistent-storage
            mountPath: $MOUNT_PATH
EOF
  az containerapp update \
    --name $AGENT_NAME \
    --resource-group $RESOURCE_GROUP \
    --yaml "$UPDATE_YAML"
  rm -f "$UPDATE_YAML"

  echo "🔄 Container updated with all configuration (secrets, env vars, volume mount)."
else
  echo "✨ Creating new container app..."
  
  # First, assign Key Vault Reader role to the managed identity
  echo "🔐 Assigning Key Vault access to managed identity..."
  MANAGED_IDENTITY_PRINCIPAL_ID=$(az identity show \
    --name "${AGENT_NAME}-identity" \
    --resource-group $RESOURCE_GROUP \
    --query principalId \
    -o tsv 2>/dev/null || echo "")
  
  if [ -z "$MANAGED_IDENTITY_PRINCIPAL_ID" ]; then
    echo "   Creating user-assigned managed identity..."
    az identity create \
      --name "${AGENT_NAME}-identity" \
      --resource-group $RESOURCE_GROUP
    MANAGED_IDENTITY_PRINCIPAL_ID=$(az identity show \
      --name "${AGENT_NAME}-identity" \
      --resource-group $RESOURCE_GROUP \
      --query principalId \
      -o tsv)
  fi
  
  # Assign Key Vault Secrets User role (check if already assigned)
  echo "   Assigning 'Key Vault Secrets User' role..."
  KV_SCOPE=$(az keyvault show --name $KV_NAME --query id -o tsv)
  EXISTING_ROLE=$(az role assignment list \
    --assignee "$MANAGED_IDENTITY_PRINCIPAL_ID" \
    --scope "$KV_SCOPE" \
    --role "Key Vault Secrets User" \
    --query "length(@)" -o tsv 2>/dev/null || echo "0")
  
  if [ "$EXISTING_ROLE" = "0" ]; then
    az role assignment create \
      --role "Key Vault Secrets User" \
      --assignee-object-id "$MANAGED_IDENTITY_PRINCIPAL_ID" \
      --scope "$KV_SCOPE" \
      --assignee-principal-type ServicePrincipal
    echo "   ✓ Role assigned successfully"
  else
    echo "   ✓ Role already assigned, skipping"
  fi
  
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
    --env-vars $ENV_VARS_STRING \
    --user-assigned ${AGENT_NAME}-identity

  # Apply comprehensive configuration: secrets, env vars, and volume mounts in one update
  echo "⚙️  Applying comprehensive configuration..."
  UPDATE_YAML=$(mktemp /tmp/update-config-XXXXXX.yaml 2>/dev/null || mktemp)
  cat > "$UPDATE_YAML" <<EOF
properties:
  configuration:
    secrets:
      - name: tavily-api-key
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/TAVILY-API-KEY
        identity: system
      - name: langchain-api-key
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/LANGCHAIN-API-KEY
        identity: system
      - name: azure-openai-endpoint
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/AZURE-OPENAI-ENDPOINT
        identity: system
      - name: azure-openai-deployment
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/AZURE-OPENAI-DEPLOYMENT
        identity: system
      - name: azure-openai-api-key
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/AZURE-OPENAI-API-KEY
        identity: system
      - name: upload-api-key
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/UPLOAD-API-KEY
        identity: system
      - name: storage-account-name
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/STORAGE-ACCOUNT-NAME
        identity: system
      - name: storage-account-key
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/STORAGE-ACCOUNT-KEY
        identity: system
      - name: file-share-name
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/FILE-SHARE-NAME
        identity: system
      - name: acr-password
        keyVaultUrl: https://${KV_NAME}.vault.azure.net/secrets/ACR-PASSWORD
        identity: system
    registries:
      - server: ${ACR_NAME}.azurecr.io
        username: ${ACR_NAME}
        passwordSecretRef: acr-password
  template:
    volumes:
      - name: persistent-storage
        storageName: azure-file-storage
        storageType: AzureFile
    containers:
      - name: deep-research-agent
        image: ${ACR_NAME}.azurecr.io/deep-research-agent:latest
        resources:
          cpu: 2.0
          memory: 4Gi
        env:
          - name: VERIFY_SSL
            value: "false"
          - name: LOG_LEVEL
            value: INFO
          - name: LANGCHAIN_TRACING_V2
            value: "true"
          - name: LANGSMITH_ENDPOINT
            value: https://api.smith.langchain.com
          - name: LANGCHAIN_PROJECT
            value: deep-research-production
          - name: ENABLE_EVAL_TRACKING
            value: "true"
          - name: MODEL_TPM
            value: "120000"
          - name: MODEL_RPM
            value: "500"
          - name: GRAPH_RECURSION_LIMIT
            value: "200"
          - name: MAX_CONCURRENT_RESEARCH_UNITS
            value: "3"
          - name: MAX_RESEARCHER_ITERATIONS
            value: "3"
          - name: MAX_GLOB_DEPTH
            value: "3"
          - name: MAX_FILES_TO_READ
            value: "20"
          - name: MAX_TOTAL_SIZE_MB
            value: "50"
          - name: MODEL_MAX_RETRIES
            value: "5"
          - name: MODEL_INITIAL_BACKOFF
            value: "1.0"
          - name: MODEL_MAX_BACKOFF
            value: "60.0"
          - name: MODEL_BACKOFF_MULTIPLIER
            value: "2.0"
          - name: MODEL_RETRY_JITTER
            value: "true"
          - name: AZURE_OPENAI_API_VERSION
            value: 2025-04-01-preview
          - name: MEMORY_TYPE
            value: cosmosdb
          - name: COSMOSDB_DB_NAME
            value: deep-research-checkpoints
          - name: COSMOSDB_CONTAINER_NAME
            value: checkpoints
          - name: REPORTS_OUTPUT_FOLDER
            value: $MOUNT_PATH/output
          - name: EVAL_HISTORY_FILE
            value: $MOUNT_PATH/output/eval_history/server_runs.jsonl
          - name: DOC_FOLDER
            value: $MOUNT_PATH/docs
          - name: INPUT_FOLDER
            value: $MOUNT_PATH/input
          - name: TAVILY_API_KEY
            secretRef: tavily-api-key
          - name: LANGCHAIN_API_KEY
            secretRef: langchain-api-key
          - name: AZURE_OPENAI_ENDPOINT
            secretRef: azure-openai-endpoint
          - name: AZURE_OPENAI_DEPLOYMENT
            secretRef: azure-openai-deployment
          - name: AZURE_OPENAI_API_KEY
            secretRef: azure-openai-api-key
          - name: UPLOAD_API_KEY
            secretRef: upload-api-key
          - name: STORAGE_ACCOUNT_NAME
            secretRef: storage-account-name
          - name: STORAGE_ACCOUNT_KEY
            secretRef: storage-account-key
          - name: FILE_SHARE_NAME
            secretRef: file-share-name
        volumeMounts:
          - volumeName: persistent-storage
            mountPath: $MOUNT_PATH
EOF
  az containerapp update \
    --name $AGENT_NAME \
    --resource-group $RESOURCE_GROUP \
    --yaml "$UPDATE_YAML"
  rm -f "$UPDATE_YAML"
fi
end_step

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
start_step "Health Check Verification"
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
end_step

# Print timing summary before exit
print_timing_summary