#!/bin/bash
set -e

cd /home/armando_salazar/webapps/uon_alumni_II

git fetch origin
git reset --hard origin/main
echo "Deployed commit: $(git rev-parse HEAD)"

# Clean untracked files (including generated CSS), but keep uploaded media
git clean -fd -e media

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
npm install

# Build Tailwind CSS
npx @tailwindcss/cli -i ./static/src/input.css -o ./static/css/output.css --minify

# Set allowed hosts
export ALLOWED_HOSTS="www.uonalumni.or.ke,uonalumni.or.ke"

# Django commands
python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Restart service
sudo systemctl restart uon_alumni
