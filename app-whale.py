from flask import Flask, render_template, request, Response

from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import os, yaml, math, time
import openai
from dotenv import load_dotenv

from timezonefinder import TimezoneFinder
from dateutil import tz
import pandas as pd
from io import StringIO
import geopandas as gpd
from shapely.geometry import Point
from shapely.ops import nearest_points
from math import atan2, degrees
from geopy import distance
import numpy as np
from scipy import optimize
import random
import requests
import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt

import copernicus_marine_client as copernicusmarine
import xarray as xr

app = Flask(__name__)

load_dotenv()
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

break_streaming = False

tools = [{
    "type": "function",
    "function": {
        "name": "change_barrels",
        "description": "Increase or decrease the number of sperm whale barrels",
        "parameters": {
            "type": "object",
            "properties": {
                "delta": {"type": "float", "description": "Change in sperm whale barrels (positive or negative"}
            }
        },
        "required": ["delta"],
    }
}, {
    "type": "function",
    "function": {
        "name": "set_sailing",
        "description": "Modify the direction of sailing and level of sails.",
        "parameters": {
            "type": "object",
            "properties": {
                "desireddirection": {"type": "string", "description": "Compass direction (e.g., north-west)"},
                "sailfullness": {"type": "float", "description": "Degree of sail extent (0 - 1)"},
            }
        },
        "required": ["desireddirection", "sailfullness"],
    }
}, {
    "type": "function",
    "function": {
        "name": "correct_location",
        "description": "Probabilistically reset location to the true location",
        "parameters": {
            "type": "object",
            "properties": {
                "successlikelihood": {"type": "float", "description": "Probability that adjustment will be accurate (0 - 1)"},
                "precision": {"type": "float", "description": "Expected error in location (km)"},
            }
        },
        "required": ["successlikelihood", "precision"],
    }
}]

def get_timezone(lat, lon):
    tf = TimezoneFinder()
    timezone_str = tf.timezone_at(lng=lon, lat=lat)
    return timezone_str

def get_currents(lat, lon):
    #copernicusmarine.login()
    start = (datetime.now() + timedelta(days=-1)).strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    if was_modified_more_than("whaling/currents.nc", 60 * 60 * 24):
        copernicusmarine.subset(
            dataset_id = "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m",
            variables = ["uo", "vo"],
            start_datetime = start,
            end_datetime = end,
            minimum_longitude = lon - 1./12,
            maximum_longitude = lon + 1./12, 
            minimum_latitude = lat - 1./12,
            maximum_latitude = lat + 1./12, 
            minimum_depth = 0,
            maximum_depth = 1,
            output_filename = "whaling/currents.nc",
            force_download = True,
            overwrite_output_data = True)
    
    ds = xr.open_dataset("whaling/currents.nc")
    return (ds.uo[-1, 0, 0, 0].values, ds.vo[-1, 0, 0, 0].values)

def was_modified_more_than(file_path, seconds):
    if not os.path.exists(file_path):
        return True
    
    # Get the current time
    current_time = time.time()

    # Get the time of the last modification of the file
    file_mod_time = os.path.getmtime(file_path)

    # Calculate the difference in seconds
    time_diff_seconds = current_time - file_mod_time

    return time_diff_seconds > seconds

def calc_ship_speed(wind_direction, wind_speed,
                    wave_direction, wave_height, wave_period,
                    desired_direction, sail_fullness):
    """
    Calculates the ship's speed given current position, local weather conditions, and user controls.
    
    Parameters:
    lat0 (float): The ship's latitude.
    lon0 (float): The ship's longitude.
    wind_direction (float): Wind direction in radians. 0 radian indicates wind is coming from the west, towards the +longitude direction.
    wind_speed (float): Wind speed in knots.
    wave_direction (float): Wave direction in radians, same convention as wind_direction.
    wave_height (float): Wave height in feet.
    wave_period (float): Wave period in seconds.
    desired_direction (float): The user's desired direction for the ship in radians.
    sail_fullness (float): The user's desired sail fullness, as a value between 0 and 1 (0 for sails completely furled, 1 for sails fully extended).
    
    Returns:
    ship speed (float): The determined speed of the ship.
    """
    ship_efficiency = 0.65 # knots
    ship_lowbound = 3. # knots
    ship_hullspeed = 10. # knots
    ship_highbound = ship_hullspeed / ship_efficiency # knots
    sqr_waveheight_frequency_danger = 30**2 # 30 ft per minute
    closehaul = math.pi / 6
    
    if np.isnan(wave_direction) or np.isnan(wave_height) or np.isnan(wave_period):
        ship_efficiency_adj = ship_efficiency
    else:
        ship_efficiency_adj = ship_efficiency - (ship_efficiency / sqr_waveheight_frequency_danger) * (wave_height**2) * np.abs(np.sin(wave_direction - desired_direction)) / (wave_period / 60)
    if ship_efficiency_adj < 0:
        return 0
    
    theta = wind_direction - desired_direction
    if theta > math.pi:
        theta -= 2*math.pi
    elif theta < -math.pi:
        theta += 2*math.pi
        
    if (theta < -math.pi + closehaul) or (theta > math.pi - closehaul):
        return 0
    
    theta_adj = theta * math.pi / (math.pi - closehaul)
    res = optimize.minimize_scalar(lambda tack: -(np.cos(theta_adj - tack) + np.cos(tack)) / 2,
                                   bounds=(-math.pi, math.pi), method='bounded')
    return -res.fun * ship_efficiency * wind_speed * (1 - np.exp(-wind_speed/ship_lowbound)) * np.exp(-wind_speed / ship_highbound) * (1.0 / np.exp(-1.0)) * sail_fullness

def get_weather(lat, lon):
    ## e.g., https://www.ndbc.noaa.gov/radial_search.php?lat1=41.2852961&lon1=-70.094363&uom=E&dist=50&ot=A&time=1
    for radius in [5, 10, 20, 40, 80]:
        print(f"Weather at {radius}")
        url = f"https://www.ndbc.noaa.gov/radial_search.php?lat1={lat}&lon1={lon}&uom=E&dist={radius}&ot=A&time=1"
        response = requests.get(url)
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            div = soup.find('pre', class_='wide-content')
            if not div:
                print("No div: " + url)
                continue
            header = soup.find('span', class_="obshdr")
            rows = div.find_all("span", class_="data-row")
            return header.text.strip() + "\n" + "\n".join([row.text.strip() for row in rows])
        else:
            print("No response")
            # e.g., "NTKM3    O 0330  41.29  -70.10    5 274  270   5.1   9.9     -     -     -   -  30.10     -  49.6  51.1     -     -    -     -     -     -      -     -     -      -  ---- -----        -       -       -       -      -      -              -"
            # LAT: Latitude of the buoy.
            # LON: Longitude of the buoy.
            # DIST: Distance to nearest requested waypoint/destination.
            # HDG: Heading towards requested waypoint/destination.
            # WDIR: Wind direction (in degrees true, from which it is blowing).
            # WSPD: Wind speed (in knots).
            # GST: Peak 5 or 8 second gust speed (in knots).
            # WVHT: Significant wave height (average height of the highest one-third of the waves).
            # DPD: Dominant wave period (in seconds) - the period with the maximum wave energy.
            # APD: Average wave period (in seconds) of all waves.
            # MWD: The direction from which the waves at the dominant period (DPD) are coming.
            # PRES: Atmospheric pressure (in inches).
            # PTDY: Atmospheric pressure tendency (pressure change in the past three hours).
            # ATMP: Air temperature (in degrees Fahrenheit).
            # WTMP: Water temperature (in degrees Fahrenheit).
            # DEWP: Dewpoint temperature (in degrees Fahrenheit).
            # VIS: Visibility (in nautical miles).
            # TCC: Total cloud cover (in eighths).
            # TIDE: Tide level (measure of water height in relation to a reference point, such as a datum).
            # S1HT, S1PD, S1DIR: Swell 1 height, period, and direction respectively.
            # S2HT, S2PD, S2DIR: Swell 2 height, period, and direction respectively.
            # Ice: Ice concentration (the Proportion of sea surface covered by ice).
            # Sea: Sea level (height of the tide-surface above the datum).
            # SwH, SwP, SwD: Significant wave height, period, and direction respectively.
            # WWH, WWP, WWD: Wind wave height, period, and direction respectively.
            # STEEPNESS: A parameter derived from the wave spectrum representing the sharpness of the wavefronts.
            
def calculate_distance(row, lat, lon):
    row_location = (row['Latitude'], row['Longitude'])
    return distance.distance(row_location, (lat, lon)).km

def get_compass_direction(lat0, lon0, lat1, lon1):
    y_diff = lat1 - lat0
    x_diff = lon1 - lon0
    angle = degrees(atan2(y_diff, x_diff))

    directions = [
        'north', 'north-northeast', 'northeast', 'east-northeast',
        'east', 'east-southeast', 'southeast', 'south-southeast',
        'south', 'south-southwest', 'southwest', 'west-southwest',
        'west', 'west-northwest', 'northwest', 'north-northwest',
        'north']
    index = round(angle / 22.5) % 16
    return directions[index]

def get_closest_point(shppath, lat, lon):
    print(shppath)
    gdf = gpd.read_file(shppath)
    point = Point(lon, lat)
    gdf['nearest_point'] = gdf.geometry.apply(lambda geom: nearest_points(point, geom)[1])
    gdf['distance'] = gdf.nearest_point.apply(lambda p: p.distance(point))
    nearest_index = gdf['distance'].idxmin()
    attributes = gdf.loc[nearest_index]
    distance = attributes['distance']
    nearest_point = attributes['nearest_point']
    direction = get_compass_direction(nearest_point.y, nearest_point.x, point.y, point.x)
    
    return(dict(lat=nearest_point.y, lon=nearest_point.x, dist=distance, attr=attributes, direct=direction))
    
def get_closest_info(lat, lon):
    landpt = get_closest_point('whaling/ne_10m_land/ne_10m_land.shp', lat, lon)
    islandpt = get_closest_point('whaling/ne_10m_minor_islands/ne_10m_minor_islands.shp', lat, lon)
    countrypt = get_closest_point('whaling/1815/cntry1815.shp', lat, lon)
    
    df = pd.read_csv("whaling/histcities.csv")
    df['Distance'] = df.apply(calculate_distance, axis=1, args=(lat, lon))
    closest_location_row = df.loc[df['Distance'].idxmin()]

    visible = []
    if islandpt['dist'] < 10:
        visible.append(islandpt)
    if landpt['dist'] < 10:
        visible.append(landpt)

    if closest_location_row['Distance'] < countrypt['dist'] + 50:
        reference = dict(dist=closest_location_row['Distance'], direct=get_compass_direction(closest_location_row['Latitude'], closest_location_row['Longitude'], lat, lon), title="{0} ({1}), {2}".format(closest_location_row['City'], closest_location_row['OtherName'], closest_location_row['Country']))
    else:
        reference = dict(dist=countrypt['dist'], direct=countrypt['direct'], title=countrypt['attr']['NAME'])

    if islandpt['dist'] < 50 or landpt['dist'] < 50:
        table = "nearshore"
    elif lat < -25 or lon > 135 or lon < -98:
        table = "whalingground"
    else:
        table = "enroute"
        
    return visible, reference, table

def get_random_encounter(table):
    ## Random encounter table
    tables = dict(nearshore = [("nothing", 0.6),
                               ("general", 0.3),
                               ("whaleevent", 0.05),
                               ("animals", .05),
                               ("rolltwice", 0.05)],
                  enroute = [("nothing", 0.7),
                             ("general", 0.2),
                             ("whaleevent", 0.05),
                             ("animals", .05),
                             ("land", .1),
                             ("rolltwice", 0.05)],
                  whalingground = [("nothing", 0.3),
                                   ("general", 0.35),
                                   ("whaleevent", 0.3),
                                   ("animals", .05),
                                   ("land", .05),
                                   ("rolltwice", 0.05)],
                  whaleevent = [
                      ("Sight a sperm whale", 0.15),
                      ("Sight a Blue whale", 0.05),
                      ("Sight a Humpback whale", 0.08),
                      ("Sighting Moby Dick", 0.01),
                      ("Bounty - find a whale carcass", 0.08),
                      ("Lose a whaleboat due to destructive whale", 0.02),
                      ("Man overboard during a whale hunt", 0.03)],
                  general = [
                      ("Sight another ship: whaling ship", 0.1),
                      ("Sight another ship: merchant vessel", 0.1),
                      ("Sight another ship: naval ship", 0.05),
                      ("Sight another ship: shipwreck", 0.02),
                      ("Sight another ship: lost or disoriented", 0.05),
                      ("Sight another ship: hostile", 0.03),
                      ("Becalmed - no winds for days", 0.12),
                      ("Bounty - find an unexpected resource", 0.08),
                      ("Encounter natives - friendly", 0.05),
                      ("Encounter natives - hostile", 0.02),
                      ("Encounter strange phenomenon - St. Elmo's fire", 0.05),
                      ("Crewman injured", 0.03),
                      ("Crewman falls overboard", 0.04),
                      ("animals", 0.08),
                      ("A hurricane", 0.02),
                      ("land", 0.05),
                      ("Heat stroke fells a sailor", 0.03),
                      ("Find a message in a bottle", 0.01),
                      ("Stored provisions spoil", 0.04),
                      ("Sickness breaks out among the crew", 0.05),
                      ("Sight icebergs or an ice floe", 0.03),
                      ("Sperm oil casks spring a leak", 0.04),
                      ("Encounter with pirates", 0.02),
                      ("Hit a reef or sandbar", 0.03),
                      ("Seagulls flock, indicating nearby land or a carcass", 0.06),
                      ("Read a sign from a prophetic dream or omen", 0.05),
                      ("Mutiny or dissatisfaction among the crew", 0.04),
                      ("Sighting of an exotic foreign vessel", 0.06),
                      ("Discover a stowaway", 0.03),
                      ("Other (unspecified) event happens", .05)],
                  animals = [
                      ("Sighting of oceanic wildlife (non-whale)", 0.5),
                      ("giant squid", .09),
                      ("giant octopus", .11),
                      ("cachalot whale", .14),
                      ("porpoise", .01),
                      ("orca whale", .01),
                      ("manta ray", .01),
                      ("baleen whale", .01),
                      ("dolphin pod", .01),
                      ("fantasyencounter", .05)],
                  fantasyencounter = [
                      # 3rd ed encounter tables
                      ("juvenile bronze dragon", .04),
                      ("dragon turtle", .04),
                      ("1d4+2 sea cats", .11),
                      ("1d4+2 huge sharks", .17),
                      ("water naga", .11),
                      ("1d4 merrow (ogre)", .06),
                      ("aquatic elf", .01),
                      ("merfolk", .01),
                      ("nixie (sprite)", .01),
                      ("kuo-toa", .01),
                      ("triton", .01),
                      ("sea hag", .01),
                      ("kraken", .01),
                      ("scrag (sea troll)", .01),
                      ("locathah", .01),
                      ("sahuagin", .01),
                      ("elasmosaurus", .01),
                      ("nokk (seahorse)", .01), # frozen 2
                      ("tamatoa", .01), # moana
                      ("kakamora", .01), # moana
                      ("cetus (sea monster)", .01), # myth
                      # 1st ed monsters
                      ("water elemental", .01),
                      ("giant eel", .01),
                      ("giant gar", .01),
                      ("hippocampus", .01),
                      ("giant lamprey", .01),
                      ("morkoth", .01),
                      ("giant portuguese man-of-war", .01),
                      ("giant turtle", .01),
                      # odyssey
                      ("scylla", .01),
                      ("charybdis", .01),
                      # Christian folklore
                      ("ghost ship", .01),
                      ("Aspidochelone", .01),
                      ("other (unspecified) mythical animal encountered", .05)],
                  land = [
                      ("Sighting land", 0.5),
                      ("deserted island", .1),
                      ("island of savages", .1),
                      ("island with cast-away", .05),
                      ("fantasy land", .05)],
                  fantasyland = [
                      ("maelstrom", .1),
                      ("island of Solomon", .01),
                      ("Atlantis", .01),
                      ("Bermuda Triangle", .01),
                      ("Edge of the world", .01),
                      ("Home of the wind", .01),
                      ("cyclops island", .01),
                      ("island of sirens", .01),
                      ("Circe's island", .01),
                      ("island of lotus-eaters", .01),
                      ("other (unspecified) mythical land encountered", .05)])
                      
    events = [entry[0] for entry in tables[table]]
    probs = np.array([entry[1] for entry in tables[table]])
    probs = probs / probs.sum()
    event = np.random.choice(events, p=probs)

    if event in tables.keys():
        return get_random_encounter(event)
    elif event == "rolltwice":
        return get_random_encounter(table) + " AND " + get_random_encounter(table)
    else:
        return event

def get_state():
    df = pd.read_csv("whaling/provisions.csv")
    with open("whaling/statelog.yml", 'r') as fp:
        state = yaml.safe_load(fp)
        state['provisions'] = '; '.join([df.Provisions[ii] + ": " + str(state[df.key[ii]]) + " " + df.units[ii] for ii in range(len(df))])
        return state

def add_state(state, dd):
    with open("whaling/statelog.yml", 'a') as fp:
        for key in dd:
            fp.write(f"{key}: {dd[key]}\n")
            state[key] = dd[key]

    return state

def update_location(state, weatherlines):
    df = pd.read_csv(StringIO(weatherlines[0] + "\n" + "\n".join(weatherlines[2:])), sep="\s+", engine='python', na_values='-')

    if state['sailing'] in ['in port', 'anchor']:
        state['WDIR'] = np.nanmean(df['WDIR'])
        state['WSPD'] = np.nanmean(df['WSPD'])
        return state # no update

    uo, vo = get_currents(state['latitude'], state['longitude'])
    timenow = time.time()
    northward = vo * (timenow - state['lastlocationtime']) # m
    eastward = uo * (timenow - state['lastlocationtime'])
    
    if state['sailing'] == 'drifting':
        newloc = distance.distance(meters=eastward).destination(distance.distance(meters=northward).destination((state['latitude'], state['longitude']), bearing=0), bearing=90)
        return add_state(state, dict(latitude=newloc.latitude, longitude=newloc.longitude))


    directions = [
        'north', 'north-northeast', 'northeast', 'east-northeast',
        'east', 'east-southeast', 'southeast', 'south-southeast',
        'south', 'south-southwest', 'southwest', 'west-southwest',
        'west', 'west-northwest', 'northwest', 'north-northwest']
    # Weather data: If say 0, I want -90; If say 90, I want -180
    # Desired direction: If say north (0), I want 90, If say east (90), I want 0
    mwd = np.nanmean(df['MWD'])
    wvht = np.nanmean(df['WVHT'])
    dpd = np.nanmean(df['DPD'])

    desireddirection = directions.index(state['desireddirection']) * 22.5 # clockwise from north
    truedirection = desireddirection + np.random.normal(0, 5.)
    speed = calc_ship_speed((-90 - np.nanmean(df['WDIR'])) * math.pi / 180., np.nanmean(df['WSPD']), (-90 - mwd) * math.pi / 180, wvht, dpd,
                            (90 - truedirection) * math.pi / 180, state['sailfullness'])
    dist = speed * 0.514444 * (timenow - state['lastlocationtime'])
    
    reconned = distance.distance(meters=dist).destination((state['reconnedlatitude'], state['reconnedlongitude']), bearing=desireddirection)

    baseloc = distance.distance(meters=np.random.normal(dist, np.sqrt(dist))).destination((state['latitude'], state['longitude']), bearing=truedirection)
    newloc = distance.distance(meters=np.random.normal(eastward, np.sqrt(np.abs(eastward)) / 10)).destination(distance.distance(meters=np.random.normal(northward, np.sqrt(np.abs(northward)) / 10)).destination(baseloc, bearing=0), bearing=90)

    state = add_state(state, dict(reconnedlatitude=reconned.latitude, reconnedlongitude=reconned.longitude,
                                  latitude=newloc.latitude, longitude=newloc.longitude, lastlocationtime=timenow))
    state['speed'] = speed
    state['WDIR'] = np.nanmean(df['WDIR'])
    state['WSPD'] = np.nanmean(df['WSPD'])
    return state

def make_map(state):
    lat = state['latitude']
    lon = state['longitude']
    
    land = gpd.read_file('whaling/ne_10m_land/ne_10m_land.shp')
    island = gpd.read_file('whaling/ne_10m_minor_islands/ne_10m_minor_islands.shp')
    reef = gpd.read_file('whaling/ne_10m_reefs/ne_10m_reefs.shp')
    country = gpd.read_file('whaling/1815/cntry1815.shp')
    histcities_df = pd.read_csv("whaling/histcities.csv")
    histcities = gpd.GeoDataFrame(histcities_df, geometry=gpd.points_from_xy(histcities_df.Longitude, histcities_df.Latitude))
    histcities.crs = land.crs
    
    point = gpd.GeoDataFrame(geometry=[Point(lon, lat)], crs=land.crs)
    circle = point.geometry.buffer(16.0934 / 110).unary_union # 10 mi
    land_subset = land.loc[land.geometry.intersects(circle)]
    island_subset = island.loc[island.geometry.intersects(circle)]
    reef_subset = reef.loc[reef.geometry.intersects(circle)]
    country_subset = country.loc[country.geometry.intersects(circle)]
    histcities_subset = histcities.loc[histcities.geometry.intersects(circle)]

    fig, ax = plt.subplots(figsize=(10, 10))
    if not land_subset.empty:
        land_subset.plot(ax=ax, color='tan')
    if not island_subset.empty:
        island_subset.plot(ax=ax, color='brown')
    if not reef_subset.empty:
        reef_subset.plot(ax=ax, color='green')
    if not country_subset.empty:
        country_subset.plot(ax=ax, edgecolor='black', facecolor='none', linewidth=1)
    if not histcities_subset.empty:
        histcities_subset.plot(ax=ax, color='red', markersize=5)

    if 'WDIR' in state and 'WSPD' in state:
        dist = state['WSPD'] * 0.514444 * 60 * 60 # 1 hour
        in1hr = distance.distance(meters=dist).destination((lat, lon), bearing=state['WDIR'] - 180)
        ax.arrow(lon, lat, in1hr.longitude - lon, in1hr.latitude - lat, head_width=0.03, head_length=0.05, fc='black', ec='black')        
        
    ax.scatter(lon, lat, color='blue')

    if 'speed' in state:
        directions = [
            'north', 'north-northeast', 'northeast', 'east-northeast',
            'east', 'east-southeast', 'southeast', 'south-southeast',
            'south', 'south-southwest', 'southwest', 'west-southwest',
            'west', 'west-northwest', 'northwest', 'north-northwest']
        desireddirection = directions.index(state['desireddirection']) * 22.5 # clockwise from north
        dist = state['speed'] * 0.514444 * 60 * 60 # 1 hour
        in1hr = distance.distance(meters=dist).destination((lat, lon), bearing=desireddirection)
        ax.arrow(lon, lat, in1hr.longitude - lon, in1hr.latitude - lat, head_width=0.03, head_length=0.05, fc='blue', ec='blue')
        
    minx, miny, maxx, maxy = circle.bounds
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    plt.savefig('whaling/viewpoint.png', dpi=300, bbox_inches='tight')

    plt.close(fig)
    ax.clear()

@app.route('/', methods=['GET', 'POST'])
def index():
    welcome = ""
    for content in stream(None, []):
        welcome += content
    print(welcome)
    return render_template('index.html', welcome=welcome)

def stream(input_text, past_messages):
    global break_streaming
    break_streaming = False

    state = get_state()
    
    timezone = get_timezone(state['latitude'], state['longitude'])
    now = datetime.now(tz=tz.gettz(timezone))
    dt = now.strftime("%d %b 18%y, %H:%M:%S")
    
    visible, reference, table = get_closest_info(state['latitude'], state['longitude'])
    if visible:
        visibletext = " and ".join(["Land {0:.0f} km {1}".format(visitem['dist'], visitem['direct']) for visitem in visible])
    else:
        visibletext = "None"
    locationtext = "{0:.0f} km {1} from {2}".format(reference['dist'], reference['direct'], reference['title'])

    randenc = get_random_encounter(table)
    weathertext = get_weather(state['latitude'], state['longitude'])
    weatherlines = weathertext.splitlines()
    weather = weatherlines[0] + "\n" + random.choice(weatherlines[1:])

    state = update_location(state, weatherlines)
    make_map(state)
    
    if state['sailing'] == 'in port':
        sailing_state = "The ship is currently docked in a port."
    elif state['sailing'] == 'sailing':
        sailing_state = "The ship is currently under sail."
    elif state['sailing'] == 'drifting':
        sailing_state = "The ship is currently drifting with the currents."
    elif state['sailing'] == 'anchor':
        sailing_state = "The ship is currently anchored off-shore."
    else:
        sailing_state = "The ship is currently " + state['sailing'] + "."
    
    system = f"""
You are an expert game master (GM), using your deep knowledge of history, literature, geography, ocean navigation, and interactive story-telling to weave a real-time simulation of the adventures of a whaling ship, based on Moby Dick. The game takes place slowly over each day. The main character is Ahab, who sets the course, asks you questions, and responds to events."""

    gminfo = f"""
GM-only information:

Datetime: {dt}
Day of voyage: 1

{sailing_state}
Sperm oil: {state['spermoil_barrels']} barrels
Remain provisions: {state['provisions']}

True Location: {state['latitude']:.2f}, {state['longitude']:.2f} ({locationtext})
Reconned location: {state['latitude']:.2f}, {state['longitude']:.2f}

Land Visible: {visibletext}
Weather: {weather}"""

    directions_basic = 'Provide a short description of the boat\'s view, including the state of the sea and weather, and the view of any nearby land.' # (e.g. "[Calm? stormy? whitecap?] seas, [gentle? steady? gusty?] wind from the [direction]. [interesting sky color or clouds on the horizon?] [If land is visible given current conditions, describe it. Otherwise, say that there is no land in sight.]")'
    if randenc == 'nothing':
        directions = 'Nothing unexpected happens today. ' + directions_basic
    else:
        directions = f"""Event for today: {randenc}

        {directions_basic}. Then introduce the event for today a little before the action starts by what Ahab seas/hears on his rounds or brought to him by one of the crew members of the Pequod (e.g., "Around sundown, Stubb is on-deck joking. You notice a flickering light far off starboard (which turns out to be a ship on fire). What do you do?"
"""
    
    print(system)
    print(gminfo)
    print(directions)
    
    # LAT, LON (D west-southwest off city/coast of country)
    # LAT +- Y, LON +- X, D +- Z off ...)
    messages = [{"role": "system", "content": system}]
    messages = [{"role": "user", "content": gminfo + "\n\n" + directions}]
    if past_messages:
        for message in past_messages:
            messages.append(message)
    if input_text is not None:
        messages.append({"role": "user", "content": f"{input_text}"})

    for line in yield_completion(messages):
        yield line
        if break_streaming:
            break
        
def yield_completion(messages):
    yielding_text = False
    while not yielding_text:
        completion = openai.ChatCompletion.create(model="gpt-3.5-turbo-1106", messages=messages,
                                                  stream=True, max_tokens=500, temperature=1)

        for line in completion:
            if 'tool_calls' in line['choices'][0]['delta']:
                for tool_call in line['choices'][0]['delta']['tool_calls']:
                    if tool_call['function']['name'] == "change_barrels":
                        TODO
                    if tool_call['function']['name'] == "set_sailing":
                        TODO
                    if tool_call['function']['name'] == "correct_location":
                        TODO
            if 'content' in line['choices'][0]['delta']:
                yield line['choices'][0]['delta']['content']
                yeilding_text = True
        
@app.route('/stop-stream', methods=['POST'])
def stop_stream():
    global break_streaming
    break_streaming = True
    return {"status": "success", "message": "Streaming stopped"}
        
@app.route('/completion', methods=['GET', 'POST'])
def completion_api():
    if request.method == "POST":
        data = request.form
        soup = BeautifulSoup(data['past_messages'], 'html.parser')
        past_messages = []
        for div in soup.find_all('div'):
            print(div['class'])
            if div['class'][0] == 'usermessage':
                past_messages.append({"role": "user", "content": div.text.strip()})
            elif div['class'][0] == 'appmessage':
                past_messages.append({"role": "assistant", "content": div.text.strip()})
        return Response(stream(data['input_text'], past_messages), mimetype='text/event-stream')
    else:
        return Response(None, mimetype='text/event-stream')

# def messages_to_functions(messages):


#     completion = openai.ChatCompletion.create(model="gpt-4-1106-preview", messages=messages, tools=tools)
#     for tool_call in completion.json()["choices"][0]["message"]['tool_calls']:
        

    
if __name__ == '__main__':
    #app.run(debug=True)

    state = get_state()
    weathertext = get_weather(state['latitude'], state['longitude'])
    weatherlines = weathertext.splitlines()
    state = update_location(state, weatherlines)
    print(state)
    make_map(state)
