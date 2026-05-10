cd /d C:\Users\joete\odds-board

python scripts\fetch_paddypower_fight_urls.py
python scripts\fetch_ufc_props_paddypower.py
python scripts\filter_props.py

git add ufc\data\paddypower_fight_urls.json ufc\data\props.json ufc\data\props_filtered.json
git commit -m "Update PaddyPower data from local scraper"
git pull --rebase origin main
git push

pause