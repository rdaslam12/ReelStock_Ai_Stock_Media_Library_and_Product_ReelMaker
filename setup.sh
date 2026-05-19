#!/bin/bash
# ReelStock setup script
# Run once after cloning / unzipping the project

set -e

echo "=== ReelStock Setup ==="

# 1. Install dependencies
echo "[1/4] Installing Python packages..."
pip install -r requirements.txt

# 2. Copy .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[2/4] Created .env — please edit it and add your API keys"
else
    echo "[2/4] .env already exists"
fi

# 3. Run migrations
echo "[3/4] Running database migrations..."
python manage.py migrate

# 4. Create superuser if needed
echo "[4/4] Done!"
echo ""
echo "Next steps:"
echo "  1. Edit .env and add your HF_API_TOKEN and FAL_API_KEY"
echo "  2. Run: python manage.py createsuperuser"
echo "  3. Run: python manage.py runserver"
echo ""
echo "Then visit:"
echo "  http://127.0.0.1:8000/          — Home"
echo "  http://127.0.0.1:8000/generate/ — AI Image Generation"
echo "  http://127.0.0.1:8000/create/   — Product Reel Maker"
echo "  http://127.0.0.1:8000/admin/    — Django Admin"
