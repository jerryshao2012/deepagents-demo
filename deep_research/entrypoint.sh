#!/bin/bash
set -e

# Path where Azure File Share is mounted
MOUNT_PATH="/deps/deep_research/mnt"

echo "═══════════════════════════════════════════════════════"
echo "🔧 Entrypoint: Configuring persistent storage..."
echo "   Mount path: $MOUNT_PATH"
echo "   Mount exists: $([ -d "$MOUNT_PATH" ] && echo 'YES' || echo 'NO')"
echo "   Mount contents: $(ls -la "$MOUNT_PATH" 2>/dev/null || echo 'N/A')"
echo "═══════════════════════════════════════════════════════"

# Function to setup persistent directory using symlinks
setup_persistent_dir() {
    local dir_name=$1
    local local_path="/deps/deep_research/$dir_name"
    local mount_path="$MOUNT_PATH/$dir_name"

    echo "🔍 Checking persistence for $dir_name..."
    echo "   local_path=$local_path (exists=$([ -e "$local_path" ] && echo 'yes' || echo 'no'), symlink=$([ -L "$local_path" ] && echo 'yes' || echo 'no'))"
    echo "   mount_path=$mount_path (exists=$([ -d "$mount_path" ] && echo 'yes' || echo 'no'))"

    if [ -d "$MOUNT_PATH" ]; then
        # Create directory on mount if it doesn't exist
        mkdir -p "$mount_path"
        
        # If local directory exists and is not a symlink, sync its content to mount then remove it
        if [ -d "$local_path" ] && [ ! -L "$local_path" ]; then
            echo "📦 Syncing existing $dir_name content to persistent storage..."
            cp -r "$local_path/." "$mount_path/" 2>/dev/null || true
            rm -rf "$local_path"
        fi
        
        # Remove stale symlink if it points to wrong target
        if [ -L "$local_path" ]; then
            current_target=$(readlink "$local_path")
            if [ "$current_target" != "$mount_path" ]; then
                echo "🔄 Removing stale symlink ($current_target → $mount_path)"
                rm -f "$local_path"
            fi
        fi
        
        # Create symlink from local path to mount path
        if [ ! -L "$local_path" ]; then
            ln -sfn "$mount_path" "$local_path"
        fi
        echo "✅ $dir_name → $mount_path (symlinked)"
    else
        echo "⚠️  Mount path $MOUNT_PATH not found. $dir_name will remain ephemeral."
        mkdir -p "$local_path"
    fi
}

# Setup persistence for all required directories
setup_persistent_dir "docs"
setup_persistent_dir "output"
setup_persistent_dir "input"
setup_persistent_dir ".langgraph_api"

echo ""
echo "📋 Final state:"
ls -la /deps/deep_research/ | grep -E "^[dl]" || true
echo "═══════════════════════════════════════════════════════"

# Execute the passed command (e.g., langgraph dev)
echo "🚀 Starting application: $@"
exec "$@"
