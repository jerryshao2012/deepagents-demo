#!/bin/zsh

# Verify Ollama installation and model availability

# Check if Ollama is installed
if ! command -v ollama &> /dev/null
then
    echo "Ollama could not be found. Installing Ollama..."
    # Install Ollama
    echo "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    
    if [ $? -ne 0 ]; then
        echo "Failed to install Ollama. Please check your internet connection and try again."
        exit 1
    fi
fi

# Check Ollama version
echo "Checking Ollama version..."
ollama --version

# Check if the specified model exists
MODEL_NAME="glm-4.7-flash:latest"
echo "Checking if model $MODEL_NAME exists..."
ollama list | grep -q "$MODEL_NAME"

if [ $? -ne 0 ]; then
    echo "Model $MODEL_NAME not found. Pulling model..."
    ollama pull $MODEL_NAME
    
    if [ $? -ne 0 ]; then
        echo "Failed to pull model $MODEL_NAME. Please check your internet connection and model name."
        exit 1
    fi
fi

# Check if Ollama service is running
echo "Checking Ollama service status..."
ps aux | grep -v grep | grep ollama > /dev/null

if [ $? -ne 0 ]; then
    echo "Ollama service is not running. Starting Ollama..."
    # Start Ollama service (command may vary based on OS)
    # For macOS/Linux, you might need to start it differently
    # This is a general approach
    nohup ollama serve > ollama.log 2>&1 &
    
    # Wait a moment for the service to start
    sleep 5
fi

# Verify API endpoint
echo "Verifying Ollama API endpoint..."
curl -s http://localhost:11434/api/version

if [ $? -ne 0 ]; then
    echo "Ollama API is not responding. Please check the service."
    exit 1
fi

echo "Ollama verification completed successfully."