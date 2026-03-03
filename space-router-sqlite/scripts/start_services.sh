#!/bin/bash
# Script to start all Space Router services for local development

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Please run setup_sqlite.sh first."
    exit 1
fi

# Activate the virtual environment
source venv/bin/activate

# Start Coordination API
echo "Starting Coordination API..."
cd coordination-api
python -m app.main &
COORD_PID=$!
cd ..
sleep 3  # Wait for API to start

# Start Home Node
echo "Starting Home Node..."
cd home-node
python -m app.main &
HOME_PID=$!
cd ..
sleep 2

# Start Proxy Gateway
echo "Starting Proxy Gateway..."
cd proxy-gateway
python -m app.main &
PROXY_PID=$!
cd ..

echo "All services started!"
echo "Coordination API running with PID: $COORD_PID"
echo "Home Node running with PID: $HOME_PID"
echo "Proxy Gateway running with PID: $PROXY_PID"
echo ""
echo "To test, create an API key and make a request:"
echo "curl -X POST http://localhost:8000/api-keys -H \"Content-Type: application/json\" -d '{\"name\": \"Test Agent\"}'"
echo "curl -x \"http://YOUR_API_KEY@localhost:8080\" http://httpbin.org/ip"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for Ctrl+C and then cleanup
trap "kill $COORD_PID $HOME_PID $PROXY_PID; echo 'Services stopped'; exit" INT TERM

# Wait indefinitely
wait
