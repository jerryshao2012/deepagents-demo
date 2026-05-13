#!/bin/bash
# Sync local files to Azure File Share
# Usage: ./sync-files.sh

set -e

# Source environment variables
source ./env.sh

echo "🔄 Syncing local files to Azure File Share..."
echo ""

# Get storage credentials from Key Vault
echo "🔐 Retrieving storage credentials from Key Vault..."
STORAGE_ACCOUNT_NAME=$(az keyvault secret show \
  --vault-name $KV_NAME \
  --name STORAGE-ACCOUNT-NAME \
  --query value -o tsv)

STORAGE_KEY=$(az keyvault secret show \
  --vault-name $KV_NAME \
  --name STORAGE-ACCOUNT-KEY \
  --query value -o tsv)

FILE_SHARE_NAME=$(az keyvault secret show \
  --vault-name $KV_NAME \
  --name FILE-SHARE-NAME \
  --query value -o tsv)

echo "✅ Storage Account: $STORAGE_ACCOUNT_NAME"
echo "✅ File Share: $FILE_SHARE_NAME"
echo ""

# Sync docs directory
if [ -d "docs" ]; then
  echo "📁 Uploading docs/ directory..."
  az storage file upload-batch \
    --source docs \
    --destination docs \
    --account-name $STORAGE_ACCOUNT_NAME \
    --account-key $STORAGE_KEY \
    --share-name $FILE_SHARE_NAME \
    --overwrite 2>/dev/null && echo "   ✅ docs/ synced" || echo "   ⚠️  No files in docs/"
else
  echo "   ⚠️  docs/ directory not found, skipping..."
fi

# Sync output directory
if [ -d "output" ]; then
  echo "📁 Uploading output/ directory..."
  az storage file upload-batch \
    --source output \
    --destination output \
    --account-name $STORAGE_ACCOUNT_NAME \
    --account-key $STORAGE_KEY \
    --share-name $FILE_SHARE_NAME \
    --overwrite 2>/dev/null && echo "   ✅ output/ synced" || echo "   ⚠️  No files in output/"
else
  echo "   ⚠️  output/ directory not found, skipping..."
fi

# Sync input directory
if [ -d "input" ]; then
  echo "📁 Uploading input/ directory..."
  az storage file upload-batch \
    --source input \
    --destination input \
    --account-name $STORAGE_ACCOUNT_NAME \
    --account-key $STORAGE_KEY \
    --share-name $FILE_SHARE_NAME \
    --overwrite 2>/dev/null && echo "   ✅ input/ synced" || echo "   ⚠️  No files in input/"
else
  echo "   ⚠️  input/ directory not found, skipping..."
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "✅ File sync complete!"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "📊 Verify uploaded files:"
echo "   az storage file list \\"
echo "     --share-name $FILE_SHARE_NAME \\"
echo "     --path docs/policy \\"
echo "     --account-name $STORAGE_ACCOUNT_NAME \\"
echo "     --account-key <key> \\"
echo "     --output table"
echo ""
echo "🧪 Check from container:"
echo "   az containerapp exec \\"
echo "     --name $AGENT_NAME \\"
echo "     --resource-group $RESOURCE_GROUP \\"
echo "     --command 'ls -la /deps/deep_research/mnt/docs/policy/'"
echo "═══════════════════════════════════════════════════════"
