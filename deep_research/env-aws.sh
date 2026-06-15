export SEED="0312"
export APP_NAME="deep-research-agent-$SEED"

# AWS Configuration
export AWS_REGION="us-east-1"
export AWS_PAGER=""

# 1. Build and push Docker image (ECR)
export ECR_REPO_NAME="deep-research-agent-$SEED"

# 2. ECS Cluster Environment
export ECS_CLUSTER_NAME="cluster-deep-agents-$SEED"

# 3. ECS Service and Task deployment
export ECS_SERVICE_NAME="deep-research-agent-$SEED"
export ECS_TASK_FAMILY="deep-research-agent-$SEED"

# Secrets Management (Secrets Manager)
export SECRETS_MANAGER_NAME="kv-deep-agents-$SEED"

# Persistent Storage (Elastic File System - EFS)
export EFS_FILE_SYSTEM_NAME="efs-deep-agents-$SEED"

# 4. Agent URL (automatically populated by deploy-aws.sh)
export DEEP_RESEARCH_AGENT_URL="https://bh3z333bky.us-east-1.awsapprunner.com"
