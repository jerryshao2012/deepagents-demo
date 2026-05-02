FROM langchain/langgraph-api:3.12

# Add local package
ADD . /deps/deep_research

# Install dependencies
RUN for dep in /deps/*; do \
      echo "Installing $dep"; \
      if [ -d "$dep" ]; then \
        (cd "$dep" && PYTHONDONTWRITEBYTECODE=1 uv pip install \
          --system --no-cache-dir -c /api/constraints.txt -e .); \
      fi; \
    done

# Configure LangGraph graphs
ENV LANGSERVE_GRAPHS='{"research": "/deps/deep_research/agent.py:agent"}'

# Ensure langgraph-api is preserved
RUN mkdir -p /api/langgraph_api /api/langgraph_runtime /api/langgraph_license && \
    touch /api/langgraph_api/__init__.py /api/langgraph_runtime/__init__.py \
          /api/langgraph_license/__init__.py
RUN PYTHONDONTWRITEBYTECODE=1 uv pip install --system --no-cache-dir \
    --no-deps -e /api

# Clean up build dependencies
RUN pip uninstall -y pip setuptools wheel && \
    rm -rf /usr/local/lib/python*/site-packages/pip* \
           /usr/local/lib/python*/site-packages/setuptools* \
           /usr/local/lib/python*/site-packages/wheel* && \
    find /usr/local/bin -name "pip*" -delete || true

WORKDIR /deps/deep_research