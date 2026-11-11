
import json


TEMPLATE_FILE = "template.html"
OUTPUT_FILE = "output.html"
LOGO_URLS_FILE = "team_logos.json"

all_logo_urls = {}
with open(LOGO_URLS_FILE, "r") as f:
    all_logo_urls = json.load(f)

def html_for_team(rank: int, team: str, record: str) -> str:
    return f"""
    <div class="table-row">
            <div class="rank-border"></div>
            <div class="rank">#{rank}</div>
            <div class="team-info">
                <img class="logo" src="{all_logo_urls.get(team, '')}" alt="{team} logo" loading="lazy">
                <span class="team-name">{team}</span>
            </div>
            <div class="record">{record}</div>
        </div>
    """    

def generate_graphic(model):
    with open(TEMPLATE_FILE, "r") as f:
        template = f.read()

    team_data = model.get_top_25()
    left_rows = ""
    right_rows = ""
    for team_info in team_data:
        row_html = html_for_team(team_info["rank"], team_info["team"], team_info["record"])
        if team_info["rank"] <= 13:
            left_rows += row_html
        else:
            right_rows += row_html

    output_html = template.replace("{{ left_rows }}", left_rows).replace("{{ right_rows }}", right_rows).replace("{{ current_week }}", str(model.current_week))

    with open(OUTPUT_FILE, "w") as f:
        f.write(output_html)