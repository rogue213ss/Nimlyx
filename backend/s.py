import requests
r = requests.get("https://store.steampowered.com/api/appdetails?appids=4570720&l=english&cc=us")
print(r.json())