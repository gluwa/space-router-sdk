#!/bin/bash
# Setup script for Space Router with SQLite backend

# Create a python virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate the virtual environment
source venv/bin/activate

# Install dependencies for all components
echo "Installing dependencies..."
(cd coordination-api && pip install -r requirements.txt)
(cd proxy-gateway && pip install -r requirements.txt)
(cd home-node && pip install -r requirements.txt)

# Setup environment variables for SQLite
echo "Creating .env files for SQLite mode..."

# Coordination API
cat > coordination-api/.env << EOL
SR_USE_SQLITE=true
SR_SQLITE_DB_PATH=space_router.db
SR_INTERNAL_API_SECRET=dev-secret
EOL

# Proxy Gateway
cat > proxy-gateway/.env << EOL
SR_COORDINATION_API_URL=http://localhost:8000
SR_COORDINATION_API_SECRET=dev-secret
SR_USE_SQLITE=true
EOL

# Home Node
cat > home-node/.env << EOL
SR_COORDINATION_API_URL=http://localhost:8000
SR_PUBLIC_IP=127.0.0.1
SR_NODE_LABEL=local-dev-node
SR_NODE_REGION=local
EOL

echo "Setup complete! To start the services:"
echo "1. Start Coordination API: cd coordination-api && python -m app.main"
echo "2. Start Home Node: cd home-node && python -m app.main"
echo "3. Start Proxy Gateway: cd proxy-gateway && python -m app.main"
