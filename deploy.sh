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

# Restart the web service first -- this must succeed regardless of
# whether the Q2 cluster steps below can, since the site itself must
# never go down because of new, unproven queue infra.
sudo systemctl restart uon_alumni

# Install/refresh the Q2 cluster's systemd unit -- version-controlled in
# this repo (qcluster.service) same as everything else here, so a unit
# file change is a normal reviewable diff, not a manual one-off edit on
# the box. Wrapped in an if/else, not run bare: a failing command inside
# an if-condition does NOT trigger this script's `set -e` at the top,
# so a failure here (e.g. armando_salazar's sudoers doesn't cover these
# specific commands yet -- unverified, no VPS access to check directly)
# is loud in the deploy log instead of silently aborting the rest of
# this script, which would otherwise also cancel the uon_alumni restart
# just above it on a completely unrelated failure.
if sudo cp qcluster.service /etc/systemd/system/qcluster.service \
    && sudo systemctl daemon-reload \
    && sudo systemctl enable qcluster \
    && sudo systemctl restart qcluster; then
    echo "qcluster: installed and running."
else
    echo "::warning::qcluster.service setup failed -- background task queue is NOT running. Check that armando_salazar's sudoers covers cp/daemon-reload/enable/restart for qcluster, then rerun deploy."
fi
